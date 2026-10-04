#!/usr/bin/env python3
"""One frozen public price-signal pilot, not an OSAP panel replication.

Consumes the unchanged wide-input manifest/loader. No downloads, parameter
search, admission, simulated activation, or writes to the source data exist.
Signals and future open-to-open labels are saved separately. This does not fill
the unavailable OSAP Mom12m/Accruals/AssetGrowth stock-panel delivery requirement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

METHODS = ("Mom12m", "STreversal", "generic_monthly_realized_volatility")
CONFIG = {
    "schema": "public_price_pilot/v1",
    "start_month": "2016-01",
    "end_month": "2024-12",
    "methods": {
        "Mom12m": "close[t-1]/close[t-12]-1; all 12 intervening monthly checkpoints required",
        "STreversal": "-(close[t]/close[t-1]-1)",
        "generic_monthly_realized_volatility": (
            "negative std(ddof=1) of all daily close returns in completed signal month t; "
            "min 15; no missing session or prior close"
        ),
    },
    "label": "first XNYS open of t+2 / first XNYS open of t+1 - 1",
    "formation": (
        "all finite signal values among frozen month-end mother members; "
        "future labels never select or reorder groups"
    ),
    "ties": "quintile ties use entity_id then symbol; RankIC uses average ranks",
    "quintiles": 5,
    "group_return": "equal weight; unavailable if any assigned member lacks label",
    "nw": (
        "Newey-West existing plug-in lag, horizon=1 monthly; "
        "min 60 observed months; calendar gaps retained"
    ),
    "source_note": (
        "Mom/ST follow supplied public formulas; volatility is explicitly generic, "
        "not the unavailable original RealizedVol.py"
    ),
    "not_osap_replication": True,
    "net_strategy_returns": False,
    "admission_authority": False,
    "limitations": [
        "open-to-open adjusted-price return is not CRSP monthly total return",
        "no transaction costs, short availability or terminal delisting return imputation",
        "original OSAP panel and Accruals/AssetGrowth gaps remain open",
    ],
}


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)


def month_sessions(calendar):
    calendar = pd.DatetimeIndex(calendar).sort_values()
    periods = pd.period_range(str(calendar[0].date())[:7], str(calendar[-1].date())[:7], freq="M")
    labels = calendar.strftime("%Y-%m")
    return {str(p): calendar[labels == str(p)] for p in periods}


def monthly_signal_values(close, calendar):
    sessions = month_sessions(calendar)
    daily = close.reindex(calendar).astype(float)
    ends = pd.Series(
        {
            month: daily.reindex(days).iloc[-1] if len(days) else np.nan
            for month, days in sessions.items()
        },
        dtype=float,
    )
    result = pd.DataFrame(index=ends.index)
    complete = ends.shift(1).rolling(12, min_periods=12).count().eq(12)
    result["Mom12m"] = (ends.shift(1) / ends.shift(12) - 1).where(complete)
    result["STreversal"] = -(ends / ends.shift(1) - 1)
    result["Mom12m_reason"] = np.where(
        result.Mom12m.notna(), "", "month_end_gap_in_12_month_window"
    )
    result["STreversal_reason"] = np.where(
        result.STreversal.notna(), "", "current_or_prior_month_end_missing"
    )
    returns = daily.pct_change(fill_method=None)
    volatility, reasons = [], []
    for days in sessions.values():
        values = returns.reindex(days)
        if len(values) < 15:
            volatility.append(np.nan)
            reasons.append("fewer_than_15_monthly_sessions")
        elif not np.isfinite(values).all():
            volatility.append(np.nan)
            reasons.append("daily_gap_or_first_return_prior_close_missing")
        else:
            volatility.append(-float(values.std(ddof=1)))
            reasons.append("")
    result[METHODS[2]], result[METHODS[2] + "_reason"] = volatility, reasons
    return result


def monthly_forward_labels(opens, calendar):
    sessions = month_sessions(calendar)
    rows = []
    for month in sessions:
        period = pd.Period(month, freq="M")
        entry_days, exit_days = sessions.get(str(period + 1), []), sessions.get(str(period + 2), [])
        row = {
            "month": month,
            "entry_date": None,
            "exit_date": None,
            "forward_return": np.nan,
            "label_reason": "",
        }
        if not len(entry_days) or not len(exit_days):
            row["label_reason"] = "future_calendar_missing"
        else:
            entry, exit_day = entry_days[0], exit_days[0]
            row.update(entry_date=entry.date().isoformat(), exit_date=exit_day.date().isoformat())
            first, last = opens.get(entry, np.nan), opens.get(exit_day, np.nan)
            if not np.isfinite(first) or first <= 0:
                row["label_reason"] = "entry_open_missing"
            elif not np.isfinite(last) or last <= 0:
                row["label_reason"] = "exit_open_missing"
            else:
                row["forward_return"] = float(last / first - 1)
        rows.append(row)
    return pd.DataFrame(rows).set_index("month")


def assign_quintiles(signals):
    result = signals.copy()
    result["quintile"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    ranked = result[result.value.notna()].sort_values(["value", "entity_id", "symbol"])
    if len(ranked) >= 5:
        result.loc[ranked.index, "quintile"] = np.arange(len(ranked)) * 5 // len(ranked) + 1
    return result


def month_statistics(joined):
    paired = joined.dropna(subset=["value", "forward_return"])
    rank_ic = None
    if len(paired) >= 2 and paired.value.nunique() > 1 and paired.forward_return.nunique() > 1:
        rank_ic = float(paired.value.rank().corr(paired.forward_return.rank()))
    output = {
        "mother_count": len(joined),
        "signal_count": int(joined.value.notna().sum()),
        "paired_count": len(paired),
        "rank_ic": rank_ic,
    }
    for q in range(1, 6):
        bucket = joined[joined.quintile.eq(q).fillna(False)]
        count = int(bucket.forward_return.notna().sum())
        output[f"Q{q}_formation_count"] = len(bucket)
        output[f"Q{q}_label_count"] = count
        output[f"Q{q}_label_coverage"] = count / len(bucket) if len(bucket) else None
        output[f"Q{q}_return"] = (
            float(bucket.forward_return.mean()) if len(bucket) and count == len(bucket) else None
        )
    output["q5_q1"] = (
        output["Q5_return"] - output["Q1_return"]
        if output["Q5_return"] is not None and output["Q1_return"] is not None
        else None
    )
    return output


def run(manifest_path, output):
    from quant_system.factors import evaluation
    from quant_system.research import wide_universe

    started_config = {
        **CONFIG,
        "input_manifest_sha256": file_sha(manifest_path),
        "script_sha256": file_sha(__file__),
        "loader_sha256": file_sha(wide_universe.__file__),
        "statistics_sha256": file_sha(evaluation.__file__),
        "pandas_version": pd.__version__,
    }
    write_json(output / "frozen-config.json", started_config)
    wide = wide_universe.load_wide_universe(manifest_path, mode="formal")
    write_json(output / "input-audit.json", wide.report)
    shutil_manifest = output / "input-manifest-snapshot.json"
    shutil_manifest.write_bytes(Path(manifest_path).read_bytes())
    mother = pd.read_csv(wide.manifest["membership"]["path"])
    mother["month_end"] = pd.to_datetime(mother.month_end, utc=True)
    mother["month"] = mother.month_end.dt.strftime("%Y-%m")
    mother = mother[mother.month.between(CONFIG["start_month"], CONFIG["end_month"])].copy()
    if mother.duplicated(["month", "entity_id"]).any():
        raise ValueError("duplicate_mother_entity")
    eligible_month_ends = wide.membership[wide.membership.signal_ts.isin(mother.month_end.unique())]
    eligible = set(
        zip(
            eligible_month_ends.signal_ts,
            eligible_month_ends.entity_id,
            eligible_month_ends.symbol,
            strict=True,
        )
    )
    frames = {
        symbol: frame.set_index("timestamp") for symbol, frame in wide.ohlcv.groupby("symbol")
    }
    feature_cache, label_cache = {}, {}
    for symbol, frame in frames.items():
        feature_cache[symbol] = monthly_signal_values(frame.close, wide.calendar)
        label_cache[symbol] = monthly_forward_labels(frame.open, wide.calendar)
    signal_rows, label_rows = [], []
    exclusions = wide.manifest.get("exclusions", {})
    for member in mother.itertuples(index=False):
        symbol, month = member.ticker_as_of, member.month
        base = {
            "month": month,
            "signal_date": member.month_end.date().isoformat(),
            "entity_id": member.entity_id,
            "symbol": symbol,
        }
        reason = ""
        if symbol in exclusions:
            reason = "quarantined:" + exclusions[symbol]["reason"]
        elif symbol not in frames:
            reason = "selected_price_file_missing"
        elif (member.month_end, member.entity_id, symbol) not in eligible:
            reason = "identity_not_eligible_at_signal"
        elif pd.isna(pd.to_datetime(member.snapshot_date_used, utc=True)):
            reason = "membership_knowledge_missing"
        elif pd.to_datetime(member.snapshot_date_used, utc=True) > member.month_end:
            reason = "membership_knowledge_after_signal"
        for method in METHODS:
            value, missing = np.nan, reason
            if not missing:
                values = feature_cache[symbol]
                value = values.loc[month, method]
                missing = values.loc[month, method + "_reason"]
            signal_rows.append(
                {
                    **base,
                    "factor": method,
                    "value": value,
                    "signal_status": "available" if pd.notna(value) else "unavailable",
                    "missing_reason": missing,
                    "source": wide.manifest["prices"].get(symbol, {}).get("source"),
                }
            )
        if symbol in label_cache:
            label = label_cache[symbol].loc[month].to_dict()
        else:
            label = {
                "entry_date": None,
                "exit_date": None,
                "forward_return": np.nan,
                "label_reason": "price_file_unavailable",
            }
        label_rows.append({**base, **label})
    signals, labels = pd.DataFrame(signal_rows), pd.DataFrame(label_rows)
    formed, monthly = [], []
    for (month, method), group in signals.groupby(["month", "factor"], sort=True):
        ranked = assign_quintiles(group)
        formed.append(ranked)
        pairs = ranked.merge(
            labels[labels.month == month][["entity_id", "symbol", "forward_return"]],
            on=["entity_id", "symbol"],
            how="left",
            validate="one_to_one",
        )
        monthly.append({"month": month, "factor": method, **month_statistics(pairs)})
    signals = pd.concat(formed, ignore_index=True)
    stats = pd.DataFrame(monthly)
    signals.to_parquet(output / "signals.parquet", index=False)
    signals.to_csv(output / "signals.csv", index=False)
    labels.to_parquet(output / "future-labels.parquet", index=False)
    labels.to_csv(output / "future-labels.csv", index=False)
    stats.to_csv(output / "monthly-statistics.csv", index=False)
    coverage = stats[["month", "factor", "mother_count", "signal_count", "paired_count"]].copy()
    coverage["signal_fraction"] = coverage.signal_count / coverage.mother_count
    coverage["paired_fraction"] = coverage.paired_count / coverage.mother_count
    coverage.to_csv(output / "monthly-coverage.csv", index=False)
    summaries = []
    full_months = pd.period_range(CONFIG["start_month"], CONFIG["end_month"], freq="M").astype(str)
    for method in METHODS:
        rows = stats[stats.factor == method].set_index("month").reindex(full_months)
        result = {
            "factor": method,
            "calendar_months": len(rows),
            "source_scope": "independent_public_price_method",
            "missing_signal_reasons": signals[signals.factor == method]
            .missing_reason.value_counts()
            .to_dict(),
        }
        for metric in ("rank_ic", "q5_q1"):
            values = rows[metric]
            lag = evaluation.newey_west_lag_rule(len(values), horizon=1)
            result[metric] = {
                "mean": float(values.mean()) if values.notna().any() else None,
                "observed_months": int(values.notna().sum()),
                "newey_west": evaluation.newey_west_stats(
                    values, lag=lag, horizon=1, min_observations=60
                ),
            }
        summaries.append(result)
    write_json(
        output / "summary.json",
        {
            "config": started_config,
            "results": summaries,
            "mother_rows": len(mother),
            "signal_rows": len(signals),
            "label_rows": len(labels),
            "input_limitations": wide.report["known_source_limits"],
            "original_T2_7_completed": False,
            "admission_authority": False,
        },
    )
    with (output / "research-index.jsonl").open("x") as handle:
        for result in summaries:
            handle.write(
                json.dumps(
                    {
                        "factor": result["factor"],
                        "config_sha256": file_sha(output / "frozen-config.json"),
                        "scope": "gross_signal_diagnostic_only",
                        "dsr_family_member": False,
                        "reason": "no_costed_executable_net_strategy",
                        "original_T2_7_completed": False,
                    }
                )
                + "\n"
            )
    (output / "script-snapshot.py").write_bytes(Path(__file__).read_bytes())
    write_json(
        output / "artifact-manifest.json",
        {p.name: file_sha(p) for p in sorted(output.iterdir()) if p.is_file()},
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "mother_rows": len(mother),
                "signal_rows": len(signals),
                "methods": [
                    {
                        "factor": r["factor"],
                        "RankIC": r["rank_ic"]["mean"],
                        "Q5_Q1": r["q5_q1"]["mean"],
                        "Q5_Q1_months": r["q5_q1"]["observed_months"],
                    }
                    for r in summaries
                ],
            }
        ),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.is_relative_to(args.input_manifest.resolve().parent):
        parser.error("output must be outside the frozen input directory")
    output.mkdir(parents=True, exist_ok=False)
    try:
        run(args.input_manifest.resolve(), output)
    except Exception as exc:
        write_json(
            output / "failure.json",
            {"status": "failed", "error_type": type(exc).__name__, "reason": str(exc)},
        )
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
