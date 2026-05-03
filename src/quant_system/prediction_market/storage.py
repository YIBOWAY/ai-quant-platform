from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_system.prediction_market.models import (
    HistoricalSnapshotRecord,
    Market,
    MarketTrade,
    OrderBookSnapshot,
    PriceHistoryPoint,
)


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

    def write_history_snapshot(
        self,
        *,
        provider: str,
        market: Market,
        order_books: list[OrderBookSnapshot],
        source_endpoint: str,
        fetched_at: str | None = None,
    ) -> list[Path]:
        active_fetched_at = fetched_at or _utc_now()
        date_part = active_fetched_at[:10]
        market_dir = self.root_dir / f"date={date_part}" / f"market_id={market.market_id}"
        market_dir.mkdir(parents=True, exist_ok=True)
        (market_dir / "market.json").write_text(
            market.model_dump_json(indent=2),
            encoding="utf-8",
        )
        paths: list[Path] = []
        for order_book in order_books:
            path = market_dir / f"token_id={order_book.token_id}.jsonl"
            record = HistoricalSnapshotRecord(
                provider=provider,
                market_id=market.market_id,
                condition_id=market.condition_id,
                token_id=order_book.token_id,
                timestamp_utc=active_fetched_at,
                fetched_at=active_fetched_at,
                source_type=(
                    "rest_snapshot" if provider == "polymarket" else "sample_snapshot"
                ),
                source_endpoint=source_endpoint,
                market=market,
                order_book=order_book,
            )
            with path.open("a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
            paths.append(path)
        return paths

    def load_history_records(
        self,
        *,
        provider: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        market_ids: list[str] | None = None,
    ) -> list[HistoricalSnapshotRecord]:
        history_root = self.root_dir
        if not history_root.exists():
            return []

        allowed_markets = {item for item in (market_ids or [])}
        start_dt = _parse_utc(start_time) if start_time else None
        end_dt = _parse_utc(end_time) if end_time else None
        records: list[HistoricalSnapshotRecord] = []
        for path in sorted(history_root.glob("date=*/market_id=*/token_id=*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = HistoricalSnapshotRecord.model_validate_json(line)
                if provider and record.provider != provider:
                    continue
                if allowed_markets and record.market_id not in allowed_markets:
                    continue
                record_dt = _parse_utc(record.timestamp_utc)
                if start_dt and record_dt < start_dt:
                    continue
                if end_dt and record_dt > end_dt:
                    continue
                records.append(record)
        return sorted(
            records,
            key=lambda item: (item.timestamp_utc, item.market_id, item.token_id),
        )

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

    def list_markets(self, limit: int | None = None) -> list[Market]:
        markets = [Market.model_validate(snapshot["market"]) for snapshot in self._snapshots]
        return markets if limit is None else markets[:limit]

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        for snapshot in self._snapshots:
            if snapshot["market_id"] == market_id:
                return [
                    OrderBookSnapshot.model_validate(book)
                    for book in snapshot.get("order_books", [])
                ]
        raise KeyError(f"unknown replay market_id {market_id!r}")

    def get_price_history(
        self,
        token_id: str,
        *,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> list[PriceHistoryPoint]:
        return []

    def get_trades(
        self,
        condition_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MarketTrade]:
        return []


class PredictionMarketHttpCache:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def read_json(
        self,
        *,
        resource: str,
        cache_key: str,
        max_age_seconds: int,
    ) -> dict[str, Any] | None:
        path = self.cache_path(resource=resource, cache_key=cache_key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, str):
            return None
        age_seconds = max((_utc_now_dt() - _parse_utc(fetched_at)).total_seconds(), 0.0)
        if age_seconds > max_age_seconds:
            return None
        return payload

    def read_stale_json(
        self,
        *,
        resource: str,
        cache_key: str,
        max_stale_seconds: int,
    ) -> dict[str, Any] | None:
        path = self.cache_path(resource=resource, cache_key=cache_key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = payload.get("fetched_at")
        if not isinstance(fetched_at, str):
            return None
        age_seconds = max((_utc_now_dt() - _parse_utc(fetched_at)).total_seconds(), 0.0)
        if age_seconds > max_stale_seconds:
            return None
        return payload

    def write_json(
        self,
        *,
        resource: str,
        cache_key: str,
        url: str,
        payload: object,
        fetched_at: str | None = None,
    ) -> Path:
        active_fetched_at = fetched_at or _utc_now()
        path = self.cache_path(resource=resource, cache_key=cache_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "resource": resource,
                    "cache_key": cache_key,
                    "url": url,
                    "fetched_at": active_fetched_at,
                    "payload": payload,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path

    def cache_path(self, *, resource: str, cache_key: str) -> Path:
        digest = sha256(cache_key.encode("utf-8")).hexdigest()
        return self.root_dir / "http_cache" / resource / f"{digest}.json"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _utc_now_dt() -> datetime:
    return datetime.now(UTC)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
