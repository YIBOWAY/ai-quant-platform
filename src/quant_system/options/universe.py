from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

UniverseSource = Literal["sp500", "nasdaq100", "both"]


@dataclass(frozen=True)
class UniverseEntry:
    ticker: str
    name: str
    sector: str
    exchange: str
    source: UniverseSource


class OptionsUniverse:
    required_columns = {"ticker", "name", "sector", "exchange", "source"}
    allowed_sources = {"sp500", "nasdaq100", "both"}

    @classmethod
    def load(cls, path: str | Path, *, top_n: int | None = None) -> list[UniverseEntry]:
        csv_path = Path(path)
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = cls.required_columns.difference(reader.fieldnames or [])
            if missing:
                raise ValueError(f"universe CSV is missing columns: {sorted(missing)}")
            merged: dict[str, UniverseEntry] = {}
            order: list[str] = []
            for raw in reader:
                ticker = str(raw.get("ticker", "")).strip().upper()
                if not ticker:
                    continue
                source = str(raw.get("source", "")).strip().lower()
                if source not in cls.allowed_sources:
                    raise ValueError(f"unknown universe source for {ticker}: {source}")
                entry = UniverseEntry(
                    ticker=ticker,
                    name=str(raw.get("name", "")).strip(),
                    sector=str(raw.get("sector", "")).strip() or "Unknown",
                    exchange=str(raw.get("exchange", "")).strip() or "Unknown",
                    source=source,  # type: ignore[arg-type]
                )
                if ticker not in merged:
                    order.append(ticker)
                    merged[ticker] = entry
                    continue
                merged[ticker] = _merge_entries(merged[ticker], entry)
        entries = [merged[ticker] for ticker in order]
        if top_n is not None:
            return entries[: max(top_n, 0)]
        return entries


def _merge_entries(left: UniverseEntry, right: UniverseEntry) -> UniverseEntry:
    source = "both" if left.source != right.source else left.source
    return UniverseEntry(
        ticker=left.ticker,
        name=left.name or right.name,
        sector=left.sector or right.sector,
        exchange=left.exchange or right.exchange,
        source=source,  # type: ignore[arg-type]
    )
