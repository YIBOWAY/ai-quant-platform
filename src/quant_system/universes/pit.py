"""Point-in-time universe snapshots.

A universe is a series of dated membership snapshots. ``universe_at`` resolves
the latest snapshot on or before a date, so backtests can pin exactly which
membership list a decision could have seen. Static seeds carry an explicit
note when historical churn is not tracked — those results are research
conclusions, not survivorship-free verdicts.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PIT_CONTRACT = "qs.universe_pit/v1"
UniverseMembershipMode = Literal["static_snapshot", "dated_snapshot", "adhoc"]


class UniverseSnapshot(BaseModel):
    universe_id: str = Field(min_length=1, max_length=64)
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    symbols: list[str] = Field(min_length=1)
    membership_mode: UniverseMembershipMode = "dated_snapshot"
    note: str | None = None

    def digest(self) -> str:
        normalized = sorted({s.strip().upper() for s in self.symbols})
        return hashlib.sha256(
            f"{self.universe_id}|{self.as_of}|".encode()
            + "|".join(normalized).encode()
        ).hexdigest()


def seed_store_path() -> Path:
    return Path(__file__).resolve().parent / "seed"


class PitUniverseStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.path = self.root / "universes.jsonl"

    def append(self, snapshot: UniverseSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot.model_dump(), sort_keys=True) + "\n")

    def list(self) -> list[UniverseSnapshot]:
        if not self.path.is_file():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(UniverseSnapshot.model_validate(json.loads(line)))
        return rows

    def universe_at(self, universe_id: str, on_date: str) -> UniverseSnapshot | None:
        best: UniverseSnapshot | None = None
        for row in self.list():
            if row.universe_id != universe_id:
                continue
            if row.as_of <= on_date and (best is None or row.as_of > best.as_of):
                best = row
        return best


__all__ = [
    "PIT_CONTRACT",
    "PitUniverseStore",
    "UniverseMembershipMode",
    "UniverseSnapshot",
    "seed_store_path",
]
