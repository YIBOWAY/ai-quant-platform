from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class EarningsCalendar:
    dates_by_ticker: dict[str, list[date]]

    @classmethod
    def load(cls, path: str | Path) -> EarningsCalendar:
        csv_path = Path(path)
        if not csv_path.exists():
            return cls({})
        dates_by_ticker: dict[str, list[date]] = {}
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = {"ticker", "earnings_date"}.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(f"earnings calendar CSV is missing columns: {sorted(missing)}")
            for row in reader:
                ticker = str(row.get("ticker", "")).strip().upper()
                raw_date = str(row.get("earnings_date", "")).strip()
                if not ticker or not raw_date:
                    continue
                dates_by_ticker.setdefault(ticker, []).append(date.fromisoformat(raw_date))
        return cls(
            {
                ticker: sorted(values)
                for ticker, values in dates_by_ticker.items()
            }
        )

    def next_earnings(self, ticker: str, today: date) -> date | None:
        normalized = ticker.upper().strip()
        for value in self.dates_by_ticker.get(normalized, []):
            if value >= today:
                return value
        return None

    def is_within(self, ticker: str, today: date, days: int) -> bool:
        next_date = self.next_earnings(ticker, today)
        if next_date is None:
            return False
        return 0 <= (next_date - today).days <= days
