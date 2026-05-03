from __future__ import annotations

import argparse
import csv
import sys
from datetime import UTC, datetime
from pathlib import Path

from quant_system.options.universe import OptionsUniverse


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the offline earnings calendar used by Options Radar. "
            "This is a manual utility; runtime screening reads only the CSV."
        )
    )
    parser.add_argument(
        "--universe",
        default="data/options_universe/sp500_nasdaq100.csv",
        help="Universe CSV path.",
    )
    parser.add_argument(
        "--output",
        default="data/options_universe/earnings_calendar.csv",
        help="Output CSV path.",
    )
    parser.add_argument("--top", type=int, default=100, help="Maximum tickers to refresh.")
    args = parser.parse_args()

    try:
        import yfinance as yf
    except ImportError:
        print("yfinance is required for this manual refresh script", file=sys.stderr)
        return 2

    entries = OptionsUniverse.load(args.universe, top_n=args.top)
    rows: list[dict[str, str]] = []
    for entry in entries:
        earnings_date = _next_earnings_date(yf, entry.ticker)
        if earnings_date:
            rows.append({"ticker": entry.ticker, "earnings_date": earnings_date})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["ticker", "earnings_date"])
        writer.writeheader()
        writer.writerows(rows)
    print(
        f"source=yfinance fetched_at={datetime.now(UTC).isoformat()} "
        f"tickers={len(entries)} rows={len(rows)} output={output}"
    )
    return 0


def _next_earnings_date(yf_module, ticker: str) -> str | None:
    try:
        calendar = yf_module.Ticker(ticker).calendar
    except Exception:
        return None
    if calendar is None:
        return None
    raw = None
    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date") or calendar.get("EarningsDate")
    else:
        try:
            raw = calendar.loc["Earnings Date"][0]
        except Exception:
            raw = None
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        text = str(raw).split()[0]
        return text if len(text) == 10 else None


if __name__ == "__main__":
    raise SystemExit(main())
