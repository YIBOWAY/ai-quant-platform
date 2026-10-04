"""Qlib signal statistics matched to actual monthly entry/exit sessions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def monthly_pairs(prices: pd.DataFrame, result: dict) -> pd.DataFrame:
    rows = []
    records = result.get("signals", [])
    if result.get("profile", {}).get("family") in {"rsi_reversion", "index_trend"}:
        return pd.DataFrame(columns=["datetime", "instrument", "score", "label", "label_end"])
    opening = prices.pivot(index="timestamp", columns="symbol", values="open")
    opening.index = pd.to_datetime(opening.index, utc=True)
    for current, following in zip(records[:-1], records[1:], strict=True):
        entry = pd.Timestamp(current["trade_date"], tz="UTC")
        exit_day = pd.Timestamp(following["trade_date"], tz="UTC")
        if entry not in opening.index or exit_day not in opening.index:
            continue
        # A missing month cannot be disguised as the next one-month label.
        if (exit_day.year - entry.year) * 12 + exit_day.month - entry.month != 1:
            continue
        for score in current.get("scores", []):
            symbol = score["symbol"]
            value = score.get("score")
            a, b = opening.loc[entry, symbol], opening.loc[exit_day, symbol]
            if value is None or not np.isfinite([value, a, b]).all() or a <= 0:
                continue
            rows.append(
                {
                    "datetime": current["signal_date"],
                    "instrument": symbol,
                    "score": float(value),
                    "label": float(b / a - 1),
                    "label_end": exit_day.date().isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=["datetime", "instrument", "score", "label", "label_end"])


def qlib_statistics(pairs: pd.DataFrame) -> dict:
    from qlib.contrib.eva.alpha import calc_ic

    def summarize(frame):
        if frame.empty:
            return {
                "status": "unavailable",
                "periods": 0,
                "samples": 0,
                "ic": None,
                "rank_ic": None,
                "rank_ic_ir": None,
            }
        frame = frame.copy()
        frame["datetime"] = pd.to_datetime(frame["datetime"])
        frame = frame.set_index(["datetime", "instrument"])
        ic, rank = calc_ic(frame.score, frame.label)
        finite_ic, finite_rank = (
            ic.replace([np.inf, -np.inf], np.nan).dropna(),
            rank.replace([np.inf, -np.inf], np.nan).dropna(),
        )
        std = float(finite_rank.std(ddof=1)) if len(finite_rank) > 1 else 0
        return {
            "status": "available" if len(finite_rank) else "unavailable",
            "periods": len(finite_rank),
            "samples": len(frame),
            "ic": float(finite_ic.mean()) if len(finite_ic) else None,
            "rank_ic": float(finite_rank.mean()) if len(finite_rank) else None,
            "rank_ic_ir": float(finite_rank.mean() / std) if std > 1e-12 else None,
        }

    output = {
        "engine": "Qlib calc_ic",
        "label": "next month first open to following month first open",
        "frequency": "monthly",
        "all": summarize(pairs),
        "splits": {},
    }
    for name, begin, end in (
        ("train", "2018-01-01", "2021-12-31"),
        ("validation", "2022-01-01", "2024-12-31"),
        ("test", "2025-01-01", "2099-12-31"),
    ):
        subset = pairs[(pairs.datetime >= begin) & (pairs.label_end <= end)]
        output["splits"][name] = summarize(subset)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-start")
    parser.add_argument("--research-end")
    args = parser.parse_args()
    pairs = pd.read_parquet(args.pairs)
    output = {
        key: qlib_statistics(frame.drop(columns="study_id"))
        for key, frame in pairs.groupby("study_id", sort=False)
    }
    if args.research_start and args.research_end:
        from quant_system.research.temporal_protocol import mature_pairs

        for key, frame in pairs.groupby("study_id", sort=False):
            output[key]["research"] = qlib_statistics(
                mature_pairs(frame, args.research_start, args.research_end)
            )["all"]
    args.output.write_text(json.dumps(output, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
