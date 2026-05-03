from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


class IvHistoryStore:
    def __init__(self, history_dir: str | Path) -> None:
        self.history_dir = Path(history_dir)

    def append(
        self,
        ticker: str,
        *,
        current_iv: float,
        run_date: str,
        fetched_at: str | None = None,
    ) -> Path:
        normalized = ticker.upper().strip()
        path = self.history_dir / f"{normalized}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ticker": normalized,
            "run_date": run_date,
            "current_iv": current_iv,
            "fetched_at": fetched_at or _utc_now(),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
        return path

    def read_values(self, ticker: str, *, lookback_days: int | None = None) -> list[float]:
        normalized = ticker.upper().strip()
        path = self.history_dir / f"{normalized}.jsonl"
        if not path.exists():
            return []
        values: list[float] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            value = payload.get("current_iv")
            if isinstance(value, int | float):
                values.append(float(value))
        if lookback_days is not None:
            return values[-lookback_days:]
        return values


def compute_iv_rank(
    ticker: str,
    current_iv: float | None,
    *,
    lookback_days: int = 252,
    history_dir: str | Path = Path("data/options_scans/iv_history"),
    min_samples: int = 30,
) -> float | None:
    if current_iv is None:
        return None
    history = IvHistoryStore(history_dir).read_values(ticker, lookback_days=lookback_days)
    if len(history) < min_samples:
        return None
    low = min(history)
    high = max(history)
    if high <= low:
        return 50.0
    rank = ((current_iv - low) / (high - low)) * 100
    return round(min(max(rank, 0.0), 100.0), 2)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
