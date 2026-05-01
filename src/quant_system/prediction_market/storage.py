from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quant_system.prediction_market.models import Market, OrderBookSnapshot


class PredictionMarketSnapshotStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def write_snapshot(
        self,
        *,
        provider: str,
        market: Market,
        order_books: list[OrderBookSnapshot],
        source_endpoint: str,
        fetched_at: str | None = None,
    ) -> Path:
        active_fetched_at = fetched_at or _utc_now()
        date_part = active_fetched_at[:10]
        path = self.root_dir / "snapshots" / date_part / provider / f"{market.market_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": provider,
            "market_id": market.market_id,
            "condition_id": market.condition_id,
            "timestamp_utc": active_fetched_at,
            "fetched_at": active_fetched_at,
            "source_type": "rest_snapshot" if provider == "polymarket" else "sample_snapshot",
            "source_endpoint": source_endpoint,
            "market": market.model_dump(mode="json"),
            "order_books": [book.model_dump(mode="json") for book in order_books],
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return path

    def load_latest_snapshots(self) -> list[dict[str, Any]]:
        latest_by_market: dict[str, dict[str, Any]] = {}
        for path in sorted((self.root_dir / "snapshots").glob("*/*/*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                market_id = str(payload["market_id"])
                is_newer = (
                    market_id not in latest_by_market
                    or payload["fetched_at"] >= latest_by_market[market_id]["fetched_at"]
                )
                if is_newer:
                    latest_by_market[market_id] = payload
        return list(latest_by_market.values())


class PredictionMarketReplayProvider:
    provider_name = "replay"

    def __init__(self, root_dir: str | Path) -> None:
        self.store = PredictionMarketSnapshotStore(root_dir)
        self._snapshots = self.store.load_latest_snapshots()

    def list_markets(self) -> list[Market]:
        return [Market.model_validate(snapshot["market"]) for snapshot in self._snapshots]

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        for snapshot in self._snapshots:
            if snapshot["market_id"] == market_id:
                return [
                    OrderBookSnapshot.model_validate(book)
                    for book in snapshot.get("order_books", [])
                ]
        raise KeyError(f"unknown replay market_id {market_id!r}")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
