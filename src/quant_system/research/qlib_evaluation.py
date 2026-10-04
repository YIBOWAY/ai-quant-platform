"""Fixed-protocol Qlib rolling evaluation over supplied, real market observations.

No formula search, orders, account writes or LLM calls occur here. Historical
formula selection and rolling-model holdout performance are reported separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import tempfile
from itertools import chain, islice
from pathlib import Path

import numpy as np
import pandas as pd

BASELINE_FEATURES = ("momentum", "volatility", "liquidity")
TRAIN_DAYS = 504
VALID_DAYS = 126
TEST_DAYS = 126
PURGE_DAYS = 2


def _date(value) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _number(value) -> float | None:
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _inputs(prices: pd.DataFrame, features: pd.DataFrame):
    bars = prices.copy()
    required = {"timestamp", "symbol", "open", "provider", "price_adjustment"}
    if not required.issubset(bars):
        raise ValueError("evaluation_prices_missing_columns")
    if set(bars["provider"].dropna()) != {"futu"} or bars["provider"].isna().any():
        raise ValueError("evaluation_requires_real_futu_prices")
    if set(bars["price_adjustment"].dropna()) != {"qfq"} or bars["price_adjustment"].isna().any():
        raise ValueError("evaluation_requires_qfq_prices")
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True).dt.tz_localize(None)
    bars["symbol"] = bars["symbol"].astype(str).str.upper()
    if bars.duplicated(["timestamp", "symbol"]).any():
        raise ValueError("evaluation_duplicate_price_rows")
    bars["open"] = pd.to_numeric(bars["open"], errors="coerce")
    if not np.isfinite(bars["open"]).all() or (bars["open"] <= 0).any():
        raise ValueError("evaluation_invalid_open_prices")
    frame = features.copy()
    if not isinstance(frame.index, pd.MultiIndex) or list(frame.index.names) != [
        "datetime",
        "instrument",
    ]:
        raise ValueError("evaluation_invalid_feature_index")
    frame.index = pd.MultiIndex.from_arrays(
        [
            pd.to_datetime(frame.index.get_level_values("datetime"), utc=True).tz_localize(None),
            frame.index.get_level_values("instrument").astype(str).str.upper(),
        ],
        names=["datetime", "instrument"],
    )
    if frame.index.has_duplicates or frame.columns.has_duplicates:
        raise ValueError("evaluation_duplicate_features")
    frame = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    if not set(BASELINE_FEATURES).issubset(frame):
        raise ValueError("evaluation_baseline_features_missing")
    opens = bars.pivot(index="timestamp", columns="symbol", values="open").sort_index()
    calendar = pd.DatetimeIndex(opens.index)
    # Shift on the common observed market calendar, not on each symbol's
    # nonmissing rows: a missing session must not become a later entry price.
    labels = (opens.shift(-2) / opens.shift(-1) - 1).stack(future_stack=True)
    labels.index.names = ["datetime", "instrument"]
    labels.name = "label"
    return bars, frame.sort_index(), labels.dropna(), calendar


def _scope(start, end, selection_end):
    if selection_end is None:
        return "rolling_model_oos_with_selection_caveat"
    cutoff = pd.Timestamp(selection_end)
    if pd.Timestamp(end) <= cutoff:
        return "historical_reanalysis"
    if pd.Timestamp(start) <= cutoff:
        return "mixed"
    # A date cutoff records selection history, not unseen-data provenance.
    return "post_selection_reanalysis"


def _signal_metrics(prediction: pd.Series, labels: pd.Series) -> dict:
    from qlib.contrib.eva.alpha import calc_ic  # noqa: PLC0415

    aligned = pd.concat([prediction.rename("prediction"), labels], axis=1).dropna()
    if aligned.empty:
        return {
            "n_rows": 0,
            "n_dates": 0,
            "ic": None,
            "rank_ic": None,
            "ic_ir": None,
            "rank_ic_ir": None,
            "daily": [],
        }
    ic, rank_ic = calc_ic(aligned["prediction"], aligned["label"])

    def ratio(series):
        std = series.std(ddof=1)
        return _number(series.mean() / std) if std > 0 else None

    return {
        "n_rows": len(aligned),
        "n_dates": int(ic.notna().sum()),
        "ic": _number(ic.mean()),
        "rank_ic": _number(rank_ic.mean()),
        "ic_ir": ratio(ic),
        "rank_ic_ir": ratio(rank_ic),
        "daily": [
            {"date": _date(day), "ic": _number(ic.loc[day]), "rank_ic": _number(rank_ic.loc[day])}
            for day in ic.index
        ],
    }


def _portfolio(prices, prediction, calendar):
    from quant_system.research.reference_backtests import evaluate_predictions  # noqa: PLC0415

    first = calendar.get_loc(prediction.index.get_level_values("datetime").min())
    last = calendar.get_loc(prediction.index.get_level_values("datetime").max())
    return evaluate_predictions(
        prices,
        prediction,
        start=calendar[first + 1],
        end=calendar[last + 2],
        top_n=3,
        terminal_valuation="open",
    )


def _coverage(prediction, calendar):
    dates = pd.DatetimeIndex(prediction.index.get_level_values("datetime").unique()).sort_values()
    expected = calendar[(calendar >= dates[0]) & (calendar <= dates[-1])]
    missing = expected.difference(dates)
    return {
        "is_contiguous": len(missing) == 0,
        "n_dates": len(dates),
        "expected_dates": len(expected),
        "missing_dates": [_date(day) for day in missing],
    }


def _selection_partitions(predictions, labels, selection_end):
    if selection_end is None:
        return {}
    baseline = predictions["baseline"]
    days = baseline.index.get_level_values("datetime")
    historical = days <= pd.Timestamp(selection_end)
    partitions = {}
    for name, mask in (("historical", historical), ("post_selection_reanalysis", ~historical)):
        selected = baseline.loc[mask]
        dates = selected.index.get_level_values("datetime")
        row = {
            "status": "available" if len(selected) else "unavailable",
            "n_dates": dates.nunique(),
            "n_rows": len(selected),
            "start": _date(dates.min()) if len(dates) else None,
            "end": _date(dates.max()) if len(dates) else None,
            "baseline_signal_metrics": _signal_metrics(selected, labels),
            "augmented_signal_metrics": None,
            "portfolio_status": "not_computed",
            "note": "本分区只计算信号统计，未计算独立成本后组合表现。",
        }
        if "augmented" in predictions:
            row["augmented_signal_metrics"] = _signal_metrics(
                predictions["augmented"].reindex(selected.index), labels
            )
        partitions[name] = row
    return partitions


def _fit_predict(common, columns, segments):
    from qlib.contrib.model.linear import LinearModel  # noqa: PLC0415
    from qlib.data.dataset import DatasetH  # noqa: PLC0415
    from qlib.data.dataset.handler import DataHandlerLP  # noqa: PLC0415
    from qlib.data.dataset.loader import StaticDataLoader  # noqa: PLC0415
    from qlib.data.dataset.processor import ZScoreNorm  # noqa: PLC0415

    normalizer = ZScoreNorm(*segments["train"], fields_group="feature")
    loader = StaticDataLoader(
        {"feature": common[columns].copy(), "label": common[["label"]].copy()}, join="inner"
    )
    handler = DataHandlerLP(data_loader=loader, infer_processors=[normalizer])
    dataset = DatasetH(handler=handler, segments=segments)
    model = LinearModel(estimator="ridge", alpha=1.0, include_valid=False)
    model.fit(dataset)
    return (
        {part: model.predict(dataset, segment=part) for part in ("valid", "test")},
        {
            "features": columns,
            "coefficients": [float(x) for x in model.coef_],
            "intercept": float(model.intercept_),
            "normalization_mean": [float(x) for x in normalizer.mean_train],
            "normalization_std": [float(x) for x in normalizer.std_train],
        },
    )


def _case(prices, features, labels, calendar, baseline, augmented, selection_end, case_id):
    from qlib.workflow.task.gen import RollingGen  # noqa: PLC0415

    columns = list(dict.fromkeys([*baseline, *(augmented or [])]))
    common = features[columns].join(labels, how="inner").dropna()
    count = common.groupby(level="datetime").size()
    # Both models see exactly the same rows. Days too small for Top-3 are not
    # used by either side to create a differently sized selection portfolio.
    common = common.loc[common.index.get_level_values("datetime").isin(count[count >= 3].index)]
    unavailable = {"status": "unavailable", "reason": "insufficient_common_history", "folds": []}
    if common.empty or len(calendar) < 3:
        return unavailable, []
    duplicate_of = next(
        (
            column
            for column in baseline
            if augmented is not None
            and case_id in common
            and common[column].equals(common[case_id])
        ),
        None,
    )
    start_idx = calendar.get_loc(common.index.get_level_values("datetime").min())
    valid_start = start_idx + TRAIN_DAYS + PURGE_DAYS
    test_start = valid_start + VALID_DAYS + PURGE_DAYS
    mature_end = calendar[-3]
    if test_start >= len(calendar) - 2:
        return unavailable, []
    task = {
        "dataset": {
            "kwargs": {
                "segments": {
                    "train": (calendar[start_idx], calendar[start_idx + TRAIN_DAYS - 1]),
                    "valid": (calendar[valid_start], calendar[valid_start + VALID_DAYS - 1]),
                    "test": (
                        calendar[test_start],
                        calendar[min(test_start + TEST_DAYS - 1, len(calendar) - 3)],
                    ),
                }
            }
        }
    }
    generator = RollingGen(
        # Explicit two-session gaps avoid Qlib's truncate assertion at index 0.
        # The maturity checks below verify both splits without fictitious dates.
        step=TEST_DAYS,
        rtype="sliding",
        trunc_days=None,
        ds_extra_mod_func=None,
    )
    # Eager RollingGen.generate() probes one task beyond the calendar. In the
    # pinned Qlib, an exact end landing yields None and then a TypeError. Consume
    # only the real number of mature folds from its native sliding iterator.
    fold_count = (len(calendar) - 3 - test_start) // TEST_DAYS + 1
    tasks = chain([task], islice(generator.gen_following_tasks(task, mature_end), fold_count - 1))
    folds, predictions, audit_rows = [], {"baseline": [], "augmented": []}, []
    for index, fold_task in enumerate(tasks):
        segments = fold_task["dataset"]["kwargs"]["segments"]
        segments["test"] = (segments["test"][0], min(segments["test"][1] or mature_end, mature_end))
        if segments["test"][0] > segments["test"][1]:
            continue
        # Explicitly check label maturity, including the train/validation split.
        for left, right in (("train", "valid"), ("valid", "test")):
            if calendar.get_loc(segments[left][1]) + 2 >= calendar.get_loc(segments[right][0]):
                raise ValueError("evaluation_label_leakage")
        fold = {
            "fold": index,
            "status": "ready",
            "segments": {},
            "evaluation_scope": _scope(*segments["test"], selection_end),
        }
        for part, (left, right) in segments.items():
            subset = common.loc[pd.IndexSlice[left:right, :], :]
            fold["segments"][part] = {
                "start": _date(left),
                "end": _date(right),
                "n_rows": len(subset),
                "n_dates": subset.index.get_level_values("datetime").nunique(),
            }
        if (
            fold["segments"]["train"]["n_dates"] != TRAIN_DAYS
            or fold["segments"]["valid"]["n_dates"] != VALID_DAYS
            or fold["segments"]["test"]["n_rows"] < 3
        ):
            fold.update(status="unavailable", reason="empty_common_segment")
            folds.append(fold)
            continue
        baseline_prediction, baseline_model = _fit_predict(common, baseline, segments)
        augmented_prediction, augmented_model = (
            _fit_predict(common, augmented, segments) if augmented is not None else (None, None)
        )
        fold["baseline_model"] = baseline_model
        fold["augmented_model"] = augmented_model
        fold["baseline_signals"] = {}
        fold["augmented_signals"] = {}
        for part in ("valid", "test"):
            base = baseline_prediction[part]
            extra = augmented_prediction[part] if augmented_prediction is not None else None
            if extra is not None and not base.index.equals(extra.index):
                raise ValueError("evaluation_paired_samples_differ")
            fold["baseline_signals"][part] = _signal_metrics(base, labels)
            if extra is not None:
                fold["augmented_signals"][part] = _signal_metrics(extra, labels)
            for key, value in base.items():
                audit_rows.append(
                    {
                        "comparison_id": case_id,
                        "fold": index,
                        "partition": part,
                        "datetime": _date(key[0]),
                        "instrument": key[1],
                        "label": float(labels.loc[key]),
                        "baseline": float(value),
                        "augmented": float(extra.loc[key]) if extra is not None else None,
                        "selection_partition": (
                            "historical" if key[0] <= pd.Timestamp(selection_end)
                            else "post_selection_reanalysis"
                        )
                        if selection_end is not None
                        else None,
                    }
                )
        predictions["baseline"].append(baseline_prediction["test"])
        if augmented_prediction is not None:
            predictions["augmented"].append(augmented_prediction["test"])
        folds.append(fold)
    if not predictions["baseline"]:
        return {**unavailable, "folds": folds}, audit_rows
    result = {
        "status": "ready" if all(f["status"] == "ready" for f in folds) else "partial",
        "folds": folds,
        "baseline_features": baseline,
        "augmented_features": augmented,
        "duplicate_of": duplicate_of,
        "note": (
            f"与基线 {duplicate_of} 在共同有效样本中完全相同，不提供新增信号信息；"
            "复制特征会改变 Ridge 的有效正则化，因此指标变化不代表新增信息贡献。"
        )
        if duplicate_of
        else None,
    }
    combined = {}
    for side in ("baseline", "augmented"):
        if not predictions[side]:
            continue
        prediction = pd.concat(predictions[side]).sort_index()
        if prediction.index.has_duplicates:
            raise ValueError("evaluation_overlapping_test_predictions")
        combined[side] = prediction
        coverage = _coverage(prediction, calendar)
        portfolio = (
            _portfolio(prices, prediction, calendar)
            if coverage["is_contiguous"]
            else {
                "status": "unavailable",
                "reason": "non_contiguous_test_predictions",
                "metrics": {},
                "benchmark_metrics": {},
                "curve": [],
            }
        )
        result[side] = {
            **portfolio,
            "signal_metrics": _signal_metrics(prediction, labels),
            "prediction_coverage": coverage,
        }
        if result[side].get("status") == "unavailable":
            result.update(status="unavailable", reason=result[side].get("reason"))
    dates = pd.concat(predictions["baseline"]).index.get_level_values("datetime")
    result["evaluation_scope"] = _scope(dates.min(), dates.max(), selection_end)
    result["partitions"] = _selection_partitions(combined, labels, selection_end)
    return result, audit_rows


def evaluate_qlib_study(prices, features, *, selection_end=None, candidate_ids=None) -> dict:
    """Evaluate fixed models; returned predictions preserve labels and paired samples."""
    import qlib  # noqa: PLC0415

    prices, features, labels, calendar = _inputs(prices, features)
    cutoff = _date(selection_end) if selection_end is not None else None
    candidates = (
        list(features.columns) if candidate_ids is None else list(dict.fromkeys(candidate_ids))
    )
    if any(not isinstance(key, str) or key not in features for key in candidates):
        raise ValueError("evaluation_candidate_missing")
    output = {
        "status": "unavailable",
        "selection_end": cutoff,
        "evaluation_scope": "rolling_model_oos_with_selection_caveat",
        "folds": [],
        "methodology": {
            "engine": "Qlib",
            "qlib_version": qlib.__version__,
            "components": ["RollingGen", "DatasetH", "StaticDataLoader", "LinearModel", "calc_ic"],
            "model": "ridge",
            "alpha": 1.0,
            "include_valid": False,
            "normalization": "training_only_zscore",
            "train_days": TRAIN_DAYS,
            "valid_days": VALID_DAYS,
            "test_days": TEST_DAYS,
            "step_days": TEST_DAYS,
            "purge_days": PURGE_DAYS,
            "label": "next_next_open / next_open - 1",
            "terminal_valuation": "last_label_exit_open",
            "terminal_liquidation": False,
            "terminal_note": "策略与基准仅按末期标签退出日开盘价盯市，未平仓、不计虚构退出费用。",
            "selection_end_known": cutoff is not None,
            "unseen_holdout_verified": False,
            "research_usage_boundary_status": "not_proven_by_selection_end",
            "selection_end_semantics": "original_request_data_end_not_research_freeze",
            "selection_note": (
                "滚动模型测试不证明公式发现样本外有效；原记录的数据截止日期不是公式冻结时间。"
                "后续日期也只作复核，未提供冻结与数据使用边界证据。"
            ),
        },
        "baseline": {},
        "comparisons": [],
        "predictions": [],
    }
    # Qlib's RollingGen uses D.calendar; this temporary provider contains only
    # the supplied observed calendar. StaticDataLoader owns the actual features.
    with tempfile.TemporaryDirectory(prefix="qlib-evaluation-") as raw:
        calendars = Path(raw) / "calendars"
        calendars.mkdir()
        text = "\n".join(_date(day) for day in calendar) + "\n"
        (calendars / "day.txt").write_text(text)
        (calendars / "day_future.txt").write_text(text)
        qlib.init(
            provider_uri=raw,
            region="us",
            expression_cache=None,
            dataset_cache=None,
            logging_level=logging.ERROR,
        )
        baseline, records = _case(
            prices, features, labels, calendar, list(BASELINE_FEATURES), None, cutoff, "baseline"
        )
        output["baseline"] = {
            **baseline.get("baseline", {}),
            "status": baseline["status"],
            "partitions": baseline.get("partitions", {}),
        }
        if baseline.get("reason"):
            output["baseline"]["reason"] = baseline["reason"]
        output["folds"] = baseline["folds"]
        output["predictions"].extend(records)
        output["evaluation_scope"] = baseline.get(
            "evaluation_scope", _scope(calendar[0], calendar[-1], cutoff)
        )
        for factor_id in candidates:
            base_columns = [key for key in BASELINE_FEATURES if key != factor_id]
            extra_columns = [*base_columns, factor_id]
            comparison, records = _case(
                prices, features, labels, calendar, base_columns, extra_columns, cutoff, factor_id
            )
            comparison.update(
                factor_id=factor_id,
                baseline_features=base_columns,
                augmented_features=extra_columns,
            )
            comparison.setdefault("duplicate_of", None)
            comparison.setdefault("note", None)
            comparison["baseline_metrics"] = comparison.get("baseline", {}).get("metrics", {})
            comparison["augmented_metrics"] = comparison.get("augmented", {}).get("metrics", {})
            comparison["delta"] = {
                key: _number(comparison["augmented_metrics"][key] - value)
                for key, value in comparison["baseline_metrics"].items()
                if isinstance(value, (int, float))
                and isinstance(comparison["augmented_metrics"].get(key), (int, float))
            }
            output["comparisons"].append(comparison)
            output["predictions"].extend(records)
    states = [output["baseline"]["status"], *(row["status"] for row in output["comparisons"])]
    output["status"] = (
        "ready"
        if all(state == "ready" for state in states)
        else (
            "partial" if any(state in {"ready", "partial"} for state in states) else "unavailable"
        )
    )
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Fixed-protocol Qlib research evaluation")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    request_path = args.input_dir / "request.json"
    request = json.loads(request_path.read_text()) if request_path.exists() else {}
    prices_path, features_path = (
        args.input_dir / "prices.parquet",
        args.input_dir / "features.parquet",
    )
    result = evaluate_qlib_study(
        pd.read_parquet(prices_path),
        pd.read_parquet(features_path),
        selection_end=request.get("selection_end"),
        candidate_ids=request.get("candidate_ids"),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    predictions = pd.DataFrame(result.pop("predictions"))
    prediction_path = args.output.with_name(args.output.stem + "-predictions.parquet")
    predictions.to_parquet(prediction_path, index=False)
    result["artifacts"] = {
        "predictions": prediction_path.name,
        "predictions_sha256": hashlib.sha256(prediction_path.read_bytes()).hexdigest(),
    }
    result["inputs"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (prices_path, features_path)
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "folds": len(result["folds"]),
                "comparisons": len(result["comparisons"]),
            }
        )
    )
    return 0 if result["status"] in {"ready", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
