"""Manual refresh of the offline VIX/VIX3M history CSV used by Options Radar.

Source: Yahoo Chart REST API first; Cboe public daily CSV fallback.
This script is read-only research tooling: no orders, no trading context,
no broker credentials. The output CSV has columns ``date,vix,vix3m`` and
is consumed by ``quant_system.options.vix_data.load_vix_history``.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from quant_system.options.vix_data import (
    fetch_vix_history,
    load_vix_history,
    save_vix_history,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the offline VIX history CSV (Yahoo first, Cboe fallback). "
            "Required for Options Radar regime adjustments."
        )
    )
    parser.add_argument(
        "--output",
        default="data/options_universe/vix_history.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=400,
        help="How many calendar days of history to request (>=300 recommended).",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date YYYY-MM-DD; defaults to today (UTC).",
    )
    args = parser.parse_args()

    end_date: date
    if args.end:
        try:
            end_date = datetime.strptime(args.end, "%Y-%m-%d").date()
        except ValueError as exc:
            print(f"invalid_end_date: {exc}", file=sys.stderr)
            return 2
    else:
        end_date = datetime.now(UTC).date()

    vix, vix3m = fetch_vix_history(end=end_date, lookback_days=args.lookback_days)
    if vix.empty and vix3m.empty:
        existing_vix, existing_vix3m = load_vix_history(args.output)
        if not existing_vix.empty:
            print(
                "fetch_failed reason=empty_response keeping_existing=true "
                f"existing_rows={len(existing_vix)} output={args.output}"
            )
            return 0
        print("fetch_failed reason=empty_response output=<not_written>", file=sys.stderr)
        return 3

    output = save_vix_history(args.output, vix, vix3m if not vix3m.empty else None)
    print(
        " ".join(
            [
                "source=yahoo_chart_or_cboe_csv",
                f"fetched_at={datetime.now(UTC).isoformat()}",
                f"vix_rows={len(vix)}",
                f"vix3m_rows={len(vix3m)}",
                f"end={end_date.isoformat()}",
                f"output={Path(output)}",
            ]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
