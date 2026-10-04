from __future__ import annotations

import csv
from datetime import date
from pathlib import Path


def load_dividend_events(path: str | Path) -> dict[str, tuple[date | None, float]]:
    """Load the dividend-events CSV written by ``refresh_dividend_events``.

    Returns ticker -> (next ex-dividend date or None, last dividend per share).
    An empty ex_dividend_date with a 0.0 amount is the source's explicit
    no-dividend assertion; a missing row stays an honest absence of evidence.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        return {}
    events: dict[str, tuple[date | None, float]] = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"ticker", "ex_dividend_date", "dividend_per_share"}.difference(
            reader.fieldnames or []
        )
        if missing:
            raise ValueError(f"dividend events CSV is missing columns: {sorted(missing)}")
        for row in reader:
            ticker = str(row.get("ticker", "")).strip().upper()
            raw_amount = str(row.get("dividend_per_share", "")).strip()
            if not ticker or not raw_amount:
                continue
            raw_date = str(row.get("ex_dividend_date", "")).strip()
            ex_dividend_date = date.fromisoformat(raw_date) if raw_date else None
            events[ticker] = (ex_dividend_date, float(raw_amount))
    return events
