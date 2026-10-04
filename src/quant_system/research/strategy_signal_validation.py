"""Qlib signal diagnostics over saved definition decisions and exact holding labels.

Read-only research: no factor recomputation, portfolio replay, order, provider or
LLM call. A rolling fitted challenger never changes the frozen strategy recipe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from quant_system.research.qlib_evaluation import _fit_predict, _signal_metrics

CONTRACT = "quant_system.strategy_signal_validation/v1"
SCOPE = "retrospective_signal_validation"
ROLLING_PERIODS = {"monthly": (48, 12, 6), "weekly": (104, 26, 13), "daily": (504, 126, 126)}


def _day(value):
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _number(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def holding_pairs(prices: pd.DataFrame, result: dict) -> tuple[pd.DataFrame, list[str], dict]:
    """Pair each saved score with its actual next rebalance's exit opening price."""
    records = result.get("signals", [])
    if not isinstance(records, list):
        raise ValueError("signal_validation_invalid_signals")
    frame = prices.copy()
    if not {"timestamp", "symbol", "open"}.issubset(frame):
        raise ValueError("signal_validation_prices_missing_fields")
    frame["date"] = pd.to_datetime(frame.timestamp, utc=True).dt.strftime("%Y-%m-%d")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("signal_validation_duplicate_quotes")
    if frame.empty:
        raise ValueError("signal_validation_empty_prices")
    watermark = min(frame.date.max(), _day(result["end"]))
    opens = frame.set_index(["date", "symbol"]).open
    declared = [str(item["factor_id"]) for item in result.get("definition", {}).get("factors", [])]
    recorded = sorted(
        {
            str(key)
            for period in records
            for row in period.get("scores", [])
            for key in (row.get("components") or {})
        }
    )
    components = list(dict.fromkeys(declared or recorded))
    columns = [
        "datetime",
        "instrument",
        "label_start",
        "label_end",
        "label",
        "score",
        *["component:" + key for key in components],
    ]
    coverage = {
        "signal_periods": len(records),
        "mature_periods": 0,
        "samples": 0,
        "excluded_rows": 0,
        "unmatured_periods": 0,
        "missing_price_rows": 0,
        "missing_component_rows": 0,
        "data_watermark": watermark,
    }
    rows = []
    dates = [_day(period["trade_date"]) for period in records]
    if dates != sorted(set(dates)):
        raise ValueError("signal_validation_duplicate_or_unordered_trade_dates")
    for index, current in enumerate(records):
        scores = current.get("scores", [])
        if len({row["symbol"] for row in scores}) != len(scores):
            raise ValueError("signal_validation_duplicate_scores")
        if index == len(records) - 1 or dates[index + 1] > watermark:
            coverage["unmatured_periods"] += 1
            continue
        signal, entry, exit_day = _day(current["signal_date"]), dates[index], dates[index + 1]
        if not signal < entry < exit_day:
            raise ValueError("signal_validation_invalid_signal_label_timing")
        mature_count = 0
        for row in scores:
            score = _number(row.get("score"))
            symbol = str(row["symbol"])
            left = opens.get((entry, symbol))
            right = opens.get((exit_day, symbol))
            if score is None:
                coverage["excluded_rows"] += 1
                continue
            if (
                left is None
                or right is None
                or not np.isfinite([left, right]).all()
                or left <= 0
                or right <= 0
            ):
                coverage["excluded_rows"] += 1
                coverage["missing_price_rows"] += 1
                continue
            parts = row.get("components") or {}
            values = {"component:" + key: _number(parts.get(key)) for key in components}
            if components and any(value is None for value in values.values()):
                coverage["excluded_rows"] += 1
                coverage["missing_component_rows"] += 1
                continue
            if components and not math.isclose(
                sum(values.values()), score, rel_tol=1e-8, abs_tol=1e-10
            ):
                raise ValueError("signal_validation_components_do_not_sum_to_score")
            rows.append(
                {
                    "datetime": signal,
                    "instrument": symbol,
                    "label_start": entry,
                    "label_end": exit_day,
                    "label": float(right / left - 1),
                    "score": score,
                    **values,
                }
            )
            mature_count += 1
        if mature_count:
            coverage["mature_periods"] += 1
    pairs = pd.DataFrame(rows, columns=columns)
    coverage["samples"] = len(pairs)
    return pairs, components, coverage


def signal_metrics(frame: pd.DataFrame, column="score") -> dict:
    if frame.empty:
        return {
            "status": "unavailable",
            "samples": 0,
            "periods": 0,
            "ic": None,
            "rank_ic": None,
            "ic_ir": None,
            "rank_ic_ir": None,
        }
    values = frame.copy()
    values["datetime"] = pd.to_datetime(values.datetime)
    values = values.set_index(["datetime", "instrument"]).sort_index()
    raw = _signal_metrics(values[column], values.label)
    return {
        "status": "available" if raw["rank_ic"] is not None else "unavailable",
        "samples": raw["n_rows"],
        "periods": raw["n_dates"],
        **{key: raw[key] for key in ("ic", "rank_ic", "ic_ir", "rank_ic_ir")},
    }


def partition_metrics(pairs, result, column="score"):
    splits = {}
    for key, section in result.get("splits", {}).items():
        if not section.get("start") or not section.get("end"):
            continue
        start, end = _day(section["start"]), _day(section["end"])
        subset = pairs.loc[(pairs.datetime >= start) & (pairs.label_end <= end)]
        splits[key] = {"start": start, "end": end, "scope": SCOPE, **signal_metrics(subset, column)}
    frequency = result.get("definition", {}).get("rebalance", "monthly")
    recent_count = {"monthly": 12, "weekly": 26, "daily": 63}.get(frequency, 12)
    dates = sorted(pairs.datetime.unique())[-recent_count:]
    recent = pairs.loc[pairs.datetime.isin(dates)]
    return {
        "all": signal_metrics(pairs, column),
        "splits": splits,
        "recent": {
            "requested_periods": recent_count,
            "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None,
            **signal_metrics(recent, column),
        },
    }


def component_correlations(pairs, components):
    columns = ["component:" + key for key in components]
    matrices = [
        group[columns].corr(method="pearson", min_periods=3).to_numpy()
        for _, group in pairs.groupby("datetime")
        if len(group) >= 3
    ]
    if not columns or not matrices:
        return {
            "status": "unavailable",
            "features": components,
            "matrix": [],
            "periods": 0,
            "reason": "components_not_recorded_or_insufficient_cross_sections",
        }
    data = np.stack(matrices)
    counts = np.isfinite(data).sum(axis=0)
    total = np.nansum(data, axis=0)
    means = np.divide(total, counts, out=np.full_like(total, np.nan), where=counts > 0)
    return {
        "status": "available",
        "features": components,
        "method": "mean of per-signal-date Pearson correlations on the same complete rows",
        "periods": len(matrices),
        "pair_period_counts": counts.tolist(),
        "matrix": [[_number(value) for value in row] for row in means],
    }


def leave_one_out(pairs, components):
    full = signal_metrics(pairs)
    output = []
    for key in components:
        reduced = pairs.assign(without_factor=pairs.score - pairs["component:" + key])
        without = signal_metrics(reduced, "without_factor")
        delta = (
            full["rank_ic"] - without["rank_ic"]
            if full["rank_ic"] is not None and without["rank_ic"] is not None
            else None
        )
        output.append(
            {
                "factor_id": key,
                "full_score": full,
                "without_factor": without,
                "rank_ic_delta_full_minus_without": delta,
                "paired_samples": len(pairs),
                "scope": "signal_increment_only_not_portfolio_return_increment",
            }
        )
    return output


def rolling_slices(pairs, frequency):
    """Fixed observed-period windows with explicit train/valid label maturity."""
    train_count, valid_count, test_count = ROLLING_PERIODS[frequency]
    dates = sorted(pairs.datetime.unique())
    gap = 2
    for offset in range(0, len(dates), test_count):
        valid_index = offset + train_count + gap
        test_index = valid_index + valid_count + gap
        if test_index >= len(dates):
            break
        groups = {
            "train": dates[offset : offset + train_count],
            "valid": dates[valid_index : valid_index + valid_count],
            "test": dates[test_index : test_index + test_count],
        }
        frame = {
            key: pairs.loc[pairs.datetime.isin(selected)].copy() for key, selected in groups.items()
        }
        # Do not use the nominal gap as proof: verify every label's actual exit.
        frame["train"] = frame["train"].loc[frame["train"].label_end < groups["valid"][0]]
        frame["valid"] = frame["valid"].loc[frame["valid"].label_end < groups["test"][0]]
        if (
            frame["train"].datetime.nunique() < train_count
            or frame["valid"].datetime.nunique() < valid_count
        ):
            continue
        yield frame


def ridge_challenger(pairs, components, result):
    frequency = result.get("definition", {}).get("rebalance", "monthly")
    protocol = {
        "frequency": frequency,
        "train_periods": ROLLING_PERIODS.get(frequency, (0, 0, 0))[0],
        "valid_periods": ROLLING_PERIODS.get(frequency, (0, 0, 0))[1],
        "test_periods": ROLLING_PERIODS.get(frequency, (0, 0, 0))[2],
        "purge_periods": 2,
        "normalization": "training_only_zscore",
        "include_valid_in_fit": False,
        "hyperparameter_search": False,
    }
    output = {
        "status": "unavailable",
        "model": "Qlib LinearModel ridge",
        "alpha": 1.0,
        "protocol": protocol,
        "folds": [],
        "matched_samples": 0,
        "scope": "retrospective_rolling_out_of_fit_not_truly_forward",
        "portfolio_status": "not_computed",
        "replaces_strategy": False,
    }
    if result.get("definition", {}).get("kind") != "factor_blend" or len(components) < 2:
        return {**output, "reason": "requires_multiple_recorded_factor_components"}
    if frequency not in ROLLING_PERIODS:
        return {**output, "reason": "unsupported_rebalance_frequency"}
    # Both sides must share all components and have a usable cross section.
    counts = pairs.groupby("datetime").size()
    common_pairs = pairs.loc[pairs.datetime.isin(counts[counts >= 3].index)]
    slices = list(rolling_slices(common_pairs, frequency))
    if not slices:
        return {**output, "reason": "insufficient_mature_common_history_for_fixed_windows"}
    import qlib

    predictions = []
    columns = ["component:" + key for key in components]
    with tempfile.TemporaryDirectory(prefix="strategy-signal-ridge-") as raw:
        calendars = Path(raw) / "calendars"
        calendars.mkdir()
        calendar = "\n".join(sorted(common_pairs.datetime.unique())) + "\n"
        (calendars / "day.txt").write_text(calendar)
        (calendars / "day_future.txt").write_text(calendar)
        qlib.init(
            provider_uri=raw,
            region="us",
            kernels=1,
            expression_cache=None,
            dataset_cache=None,
            logging_level=logging.ERROR,
        )
        for index, frames in enumerate(slices):
            all_rows = pd.concat(list(frames.values())).copy()
            all_rows["datetime"] = pd.to_datetime(all_rows.datetime)
            common = all_rows.set_index(["datetime", "instrument"]).sort_index()
            segments = {
                key: (pd.Timestamp(frame.datetime.min()), pd.Timestamp(frame.datetime.max()))
                for key, frame in frames.items()
            }
            # The existing helper fits Qlib DatasetH/LinearModel with alpha=1;
            # its normalizer sees only the training segment.
            predicted, trained = _fit_predict(common, columns, segments)
            expected = frames["test"].copy()
            expected["datetime"] = pd.to_datetime(expected.datetime)
            expected = expected.set_index(["datetime", "instrument"]).sort_index()
            prediction = predicted["test"].sort_index()
            if not prediction.index.equals(expected.index) or not np.isfinite(prediction).all():
                raise ValueError("signal_validation_ridge_prediction_index_or_values_invalid")
            expected["ridge"] = prediction
            expected = expected.reset_index()
            expected["datetime"] = expected.datetime.dt.strftime("%Y-%m-%d")
            predictions.append(expected)
            output["folds"].append(
                {
                    "fold": index + 1,
                    "status": "trained",
                    "segments": {
                        key: {
                            "start": _day(start),
                            "end": _day(end),
                            "periods": frames[key].datetime.nunique(),
                            "samples": len(frames[key]),
                            "label_maturity_max": frames[key].label_end.max(),
                        }
                        for key, (start, end) in segments.items()
                    },
                    "trained_model": trained,
                    "fixed_score_metrics": signal_metrics(expected),
                    "ridge_metrics": signal_metrics(expected, "ridge"),
                }
            )
    combined = pd.concat(predictions, ignore_index=True)
    if combined.duplicated(["datetime", "instrument"]).any():
        raise ValueError("signal_validation_duplicate_ridge_predictions")
    fixed, ridge = signal_metrics(combined), signal_metrics(combined, "ridge")
    output.update(
        status="available",
        fold_count=len(output["folds"]),
        matched_samples=len(combined),
        fixed_score_metrics=fixed,
        ridge_metrics=ridge,
        rank_ic_delta=(
            ridge["rank_ic"] - fixed["rank_ic"]
            if ridge["rank_ic"] is not None and fixed["rank_ic"] is not None
            else None
        ),
        predictions=combined[
            ["datetime", "instrument", "label_end", "score", "ridge", "label"]
        ].to_dict(orient="records"),
    )
    return output


def validate_signals(prices: pd.DataFrame, result: dict) -> dict:
    profile = result.get("profile", {})
    family = profile.get("family") or (
        result.get("definition", {}).get("profile_snapshot") or {}
    ).get("family")
    base = {
        "contract": CONTRACT,
        "engine": "Qlib calc_ic",
        "scope": SCOPE,
        "definition_digest": result.get("definition_digest"),
        "methodology": {
            "label": "next actual trade_date open / current trade_date open - 1",
            "components": "saved normalized weighted contributions; same complete rows",
            "leave_one_out": "full score minus one saved contribution, no rule refit",
            "portfolio_increment": "not_computed",
            "selection_direction": result.get("definition", {}).get("selection", "top"),
            "forward_observation": "not_established_by_historical_analysis",
            "note": "已看历史仅作研发与回顾性信号验证；真正前瞻只从策略冻结后新数据积累。",
        },
    }
    if family in {"rsi_reversion", "index_trend"}:
        return {
            **base,
            "status": "not_applicable",
            "reason": "single_index_timing_has_no_cross_sectional_ranking",
        }
    if result.get("status") != "available":
        return {**base, "status": "unavailable", "reason": "saved_strategy_result_unavailable"}
    pairs, components, coverage = holding_pairs(prices, result)
    if pairs.empty:
        return {
            **base,
            "status": "unavailable",
            "coverage": coverage,
            "reason": "no_mature_complete_signal_labels",
        }
    output = {
        **base,
        "status": "available",
        "coverage": coverage,
        "score": partition_metrics(pairs, result),
        "components": [
            {"factor_id": key, **partition_metrics(pairs, result, "component:" + key)}
            for key in components
        ],
        "component_status": "available" if components else "not_recorded",
        "correlations": component_correlations(pairs, components),
        "leave_one_out": leave_one_out(pairs, components),
    }
    try:
        output["ridge"] = ridge_challenger(pairs, components, result)
    except Exception as exc:  # noqa: BLE001 - retain completed Qlib signals on model failure
        output["ridge"] = {
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "model": "Qlib LinearModel ridge",
            "portfolio_status": "not_computed",
            "replaces_strategy": False,
        }
        output["status"] = "partial"
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prices", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output = validate_signals(pd.read_parquet(args.prices), json.loads(args.result.read_text()))
    except Exception as exc:  # noqa: BLE001 - never leave an old success file after failure
        args.output.write_text(
            json.dumps(
                {
                    "contract": CONTRACT,
                    "status": "failed",
                    "engine": "Qlib calc_ic",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        raise
    output["source"] = {
        "prices_sha256": _digest(args.prices),
        "result_sha256": _digest(args.result),
        "validation_source_sha256": _digest(__file__),
        "fit_metrics_source_sha256": _digest(Path(__file__).with_name("qlib_evaluation.py")),
    }
    commit = Path("/opt/qlib/.hqa-upstream-commit")
    output["qlib_commit"] = commit.read_text().strip() if commit.is_file() else None
    args.output.write_text(json.dumps(output, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
