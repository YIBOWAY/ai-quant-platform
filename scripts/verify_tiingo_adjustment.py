#!/usr/bin/env python3
"""Reproducible Tiingo split/dividend adjustment validation (manual / external gate).

Remediation Package A (Result Credibility Baseline) keeps the Tiingo
adjusted-price risk *guarded* with offline fixture tests
(``tests/test_data_tiingo_provider.py``) and local-storage round-trip tests.
The remaining in-scope acceptance item is a *reproducible* live validation that a
real corporate-action window is actually adjusted.

That validation needs a real Tiingo API token and market-data network access, so
it is an operator-run **external gate**, NOT part of the offline pytest suite
(see AGENTS.md: "Do not call live ... APIs in tests"). It only reads market data
and never places orders.

Usage (operator, with a configured token in .env / ``QS_TIINGO_API_TOKEN``)::

    python scripts/verify_tiingo_adjustment.py
    python scripts/verify_tiingo_adjustment.py --symbol NVDA --split-date 2024-06-10

Without a token the script prints ``SKIP`` and exits 0, so it is safe to invoke
anywhere. With a token it fetches the split window from the live Tiingo EOD
endpoint, asserts ``price_adjustment == "adjusted"`` for every row, and asserts
the adjusted close shows no split-sized discontinuity across the split date (an
unadjusted N:1 split would jump by ~``ln(N)``). Exits non-zero on failure.

For a dividend window, pass the ex-dividend symbol/date with ``--split-ratio 1``
to skip the discontinuity assertion and simply confirm the rows are
``adjusted``-labelled.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Make sure ``src/`` is on sys.path when running this as a standalone script.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_system.config.settings import reload_settings  # noqa: E402  # isort:skip
from quant_system.data.providers.tiingo import TiingoEODProvider  # noqa: E402  # isort:skip


@dataclass(frozen=True)
class AdjustmentCheck:
    ok: bool
    messages: list[str]


def max_abs_daily_log_return(closes: list[float]) -> float:
    """Largest ``|ln(c_t / c_{t-1})|`` across an ordered close series.

    A correctly split-adjusted series keeps day-over-day returns small across a
    split date; an unadjusted N:1 split shows a single jump near ``ln(N)``.
    """

    largest = 0.0
    previous: float | None = None
    for close in closes:
        if previous is not None and previous > 0 and close > 0:
            largest = max(largest, abs(math.log(close / previous)))
        previous = close
    return largest


def evaluate_adjustment(frame: pd.DataFrame, *, split_ratio: float) -> AdjustmentCheck:
    """Validate that a fetched corporate-action window is adjusted and continuous."""

    if frame.empty:
        return AdjustmentCheck(False, ["no rows returned for the requested window"])

    messages: list[str] = []
    ok = True

    labels = set(frame["price_adjustment"].astype(str).str.lower())
    messages.append(f"price_adjustment labels: {sorted(labels)}")
    if labels != {"adjusted"}:
        ok = False
        messages.append("FAIL: expected every row labelled 'adjusted'")

    ordered = frame.sort_values("timestamp")
    closes = [float(value) for value in ordered["close"].tolist()]
    observed = max_abs_daily_log_return(closes)
    split_jump = abs(math.log(split_ratio)) if split_ratio > 1 else 0.0
    if split_jump:
        threshold = split_jump / 2
        messages.append(
            f"max |daily log-return| = {observed:.4f} "
            f"(unadjusted split jump ~ {split_jump:.4f}; reject >= {threshold:.4f})"
        )
        if observed >= threshold:
            ok = False
            messages.append("FAIL: adjusted close still shows a split-sized discontinuity")
    else:
        messages.append(
            f"max |daily log-return| = {observed:.4f} (no split jump asserted; ratio <= 1)"
        )
    return AdjustmentCheck(ok, messages)


def resolve_token() -> str | None:
    settings = reload_settings()
    token = settings.api_keys.tiingo_api_token
    if token is None:
        return None
    value = token.get_secret_value().strip()
    return value or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate Tiingo split/dividend adjustment over a known corporate-action window."
        ),
    )
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument(
        "--split-date",
        default="2020-08-31",
        help="ISO date the corporate action took effect (default: AAPL 4:1 split)",
    )
    parser.add_argument(
        "--split-ratio",
        type=float,
        default=4.0,
        help="N for an N:1 forward split; values <= 1 skip the discontinuity assertion",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=5,
        help="calendar days before/after --split-date to fetch",
    )
    args = parser.parse_args(argv)

    token = resolve_token()
    if token is None:
        print(
            "SKIP: no Tiingo API token configured "
            "(QS_TIINGO_API_TOKEN / settings.api_keys.tiingo_api_token)."
        )
        print(
            "This live split/dividend validation is a manual / external gate; "
            "configure a real token and re-run to exercise it."
        )
        print("Exiting 0 without contacting the network.")
        return 0

    start = (pd.Timestamp(args.split_date) - pd.Timedelta(days=args.window_days)).date().isoformat()
    end = (pd.Timestamp(args.split_date) + pd.Timedelta(days=args.window_days)).date().isoformat()
    print(f"Fetching {args.symbol} {start}..{end} from the live Tiingo EOD endpoint...")

    provider = TiingoEODProvider(api_token=token)
    frame = provider.fetch_ohlcv([args.symbol], start=start, end=end)

    result = evaluate_adjustment(frame, split_ratio=args.split_ratio)
    for message in result.messages:
        print(f"  {message}")
    if result.ok:
        print(
            f"PASS: {args.symbol} {args.split_date} window is adjusted "
            "with no split-sized discontinuity."
        )
        return 0
    print(f"FAIL: {args.symbol} {args.split_date} window did not validate; see messages above.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
