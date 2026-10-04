"""Compare two saved research panels; no network or mutation of either source."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiingo", type=Path, required=True)
    parser.add_argument("--futu", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    results = []
    for left_path in sorted(args.tiingo.glob("*.parquet")):
        right_path = args.futu / left_path.name
        if not right_path.is_file():
            continue
        left, right = pd.read_parquet(left_path), pd.read_parquet(right_path)
        left.index = pd.to_datetime(left.date, utc=True)
        right.index = pd.to_datetime(right.timestamp, utc=True)
        joined = pd.concat(
            [
                left.adjClose.rename("tiingo"),
                right.close.rename("futu"),
                left.adjVolume.rename("tiingo_volume"),
                right.volume.rename("futu_volume"),
            ],
            axis=1,
        ).dropna()
        returns = joined[["tiingo", "futu"]].pct_change(fill_method=None).dropna()
        diff = (returns.futu - returns.tiingo).abs() * 1e4
        volume_ratio = (
            (joined.futu_volume / joined.tiingo_volume).replace([np.inf, -np.inf], np.nan).dropna()
        )
        results.append(
            {
                "symbol": left_path.stem,
                "common_rows": len(joined),
                "start": str(joined.index.min()),
                "end": str(joined.index.max()),
                "return_diff_bps_median": float(diff.median()),
                "return_diff_bps_p95": float(diff.quantile(0.95)),
                "return_diff_bps_max": float(diff.max()),
                "volume_ratio_min": float(volume_ratio.min()),
                "volume_ratio_p95": float(volume_ratio.quantile(0.95)),
                "volume_ratio_max": float(volume_ratio.max()),
                "tiingo_sha256": hashlib.sha256(left_path.read_bytes()).hexdigest(),
                "futu_sha256": hashlib.sha256(right_path.read_bytes()).hexdigest(),
            }
        )
    report = {
        "schema_version": "qs.cross_source_check/v1",
        "as_of": "2026-09-20",
        "sources": ["tiingo_adjusted_ohlcv", "futu_qfq"],
        "symbols_compared": len(results),
        "results": results,
        "admission_authority": False,
        "limitations": [
            "Only these common symbols were checked, not universal source equivalence.",
            "AAPL pre-2020-08-31: Futu volume matches Tiingo adjVolume (raw times four).",
            "Provider volume counts and occasional price corrections differ; "
            "volume-sensitive factors retain this limitation.",
            "Each symbol uses one complete source series; "
            "old frozen strategy histories are unchanged.",
        ],
    }
    with args.out.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"symbols_compared": len(results), "path": str(args.out)}))


if __name__ == "__main__":
    main()
