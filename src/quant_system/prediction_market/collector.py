from __future__ import annotations

import copy
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from quant_system.prediction_market.data.base import PredictionMarketDataProvider
from quant_system.prediction_market.models import OrderBookSnapshot
from quant_system.prediction_market.storage import PredictionMarketSnapshotStore

_POLYMARKET_CREDENTIAL_ENV_NAMES = (
    "POLYMARKET_API_KEY",
    "QS_POLYMARKET_API_KEY",
    "POLYMARKET_SECRET",
    "QS_POLYMARKET_SECRET",
    "POLYMARKET_TOKEN",
    "QS_POLYMARKET_TOKEN",
)


@dataclass(slots=True)
class PredictionMarketCollectionSummary:
    provider: str
    iteration_count: int
    market_count: int
    snapshot_record_count: int
    output_root: Path
    first_timestamp: str | None
    last_timestamp: str | None


class PredictionMarketSnapshotCollector:
    def __init__(
        self,
        *,
        provider: PredictionMarketDataProvider,
        provider_label: str,
        store: PredictionMarketSnapshotStore,
        interval_seconds: float,
        duration_seconds: float,
        market_ids: list[str] | None = None,
        limit: int | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        if duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative")
        self.provider = provider
        self.provider_label = provider_label
        self.store = store
        self.interval_seconds = interval_seconds
        self.duration_seconds = duration_seconds
        self.market_ids = {item for item in (market_ids or [])}
        self.limit = limit
        self.sleep_fn = sleep_fn
        self.now_fn = now_fn or (lambda: datetime.now(UTC))

    def collect_once(self, *, fetched_at: str | None = None) -> PredictionMarketCollectionSummary:
        active_fetched_at = fetched_at or _utc_now(self.now_fn())
        markets = self.provider.list_markets(limit=self.limit)
        if self.market_ids:
            markets = [market for market in markets if market.market_id in self.market_ids]
        record_count = 0
        for market in markets:
            order_books = self.provider.get_order_books(market.market_id)
            paths = self.store.write_history_snapshot(
                provider=self.provider_label,
                market=market,
                order_books=order_books,
                source_endpoint=self.provider_label,
                fetched_at=active_fetched_at,
            )
            record_count += len(paths)
        return PredictionMarketCollectionSummary(
            provider=self.provider_label,
            iteration_count=1,
            market_count=len(markets),
            snapshot_record_count=record_count,
            output_root=self.store.root_dir,
            first_timestamp=active_fetched_at if markets else None,
            last_timestamp=active_fetched_at if markets else None,
        )

    def run(self) -> PredictionMarketCollectionSummary:
        start = self.now_fn()
        iteration = 0
        record_count = 0
        market_count = 0
        first_timestamp: str | None = None
        last_timestamp: str | None = None
        while True:
            timestamp = _utc_now(self.now_fn())
            summary = self.collect_once(fetched_at=timestamp)
            iteration += 1
            record_count += summary.snapshot_record_count
            market_count = summary.market_count
            first_timestamp = first_timestamp or summary.first_timestamp
            last_timestamp = summary.last_timestamp
            if self.duration_seconds == 0:
                break
            if (self.now_fn() - start).total_seconds() >= self.duration_seconds:
                break
            self.sleep_fn(self.interval_seconds)
        return PredictionMarketCollectionSummary(
            provider=self.provider_label,
            iteration_count=iteration,
            market_count=market_count,
            snapshot_record_count=record_count,
            output_root=self.store.root_dir,
            first_timestamp=first_timestamp,
            last_timestamp=last_timestamp,
        )


def ensure_no_polymarket_credentials_in_env() -> None:
    for name in _POLYMARKET_CREDENTIAL_ENV_NAMES:
        if os.getenv(name):
            raise ValueError(
                f"{name} is set, but Phase 12 remains read-only "
                "and does not accept Polymarket credentials"
            )


def seed_sample_history_dataset(root_dir: str | Path) -> PredictionMarketCollectionSummary:
    from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider

    store = PredictionMarketSnapshotStore(root_dir)
    provider = SamplePredictionMarketProvider()
    timestamps = [
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
    ]
    price_overrides = {
        "2026-01-01T00:00:00Z": {
            "sample-binary-yes": (0.39, 0.42),
            "sample-binary-no": (0.53, 0.56),
            "sample-three-a": (0.29, 0.31),
            "sample-three-b": (0.32, 0.34),
            "sample-three-c": (0.36, 0.38),
        },
        "2026-01-02T00:00:00Z": {
            "sample-binary-yes": (0.37, 0.40),
            "sample-binary-no": (0.52, 0.55),
            "sample-three-a": (0.28, 0.30),
            "sample-three-b": (0.33, 0.35),
            "sample-three-c": (0.38, 0.40),
        },
        "2026-01-03T00:00:00Z": {
            "sample-binary-yes": (0.44, 0.47),
            "sample-binary-no": (0.46, 0.49),
            "sample-three-a": (0.26, 0.28),
            "sample-three-b": (0.32, 0.34),
            "sample-three-c": (0.34, 0.36),
        },
    }

    total_records = 0
    for timestamp in timestamps:
        for market in provider.list_markets():
            order_books = provider.get_order_books(market.market_id)
            adjusted_books = [
                _adjust_order_book(
                    order_book,
                    bid=price_overrides[timestamp][order_book.token_id][0],
                    ask=price_overrides[timestamp][order_book.token_id][1],
                )
                for order_book in order_books
            ]
            total_records += len(
                store.write_history_snapshot(
                    provider="sample",
                    market=market,
                    order_books=adjusted_books,
                    source_endpoint="sample://phase12-fixture",
                    fetched_at=timestamp,
                )
            )
    return PredictionMarketCollectionSummary(
        provider="sample",
        iteration_count=len(timestamps),
        market_count=len(provider.list_markets()),
        snapshot_record_count=total_records,
        output_root=store.root_dir,
        first_timestamp=timestamps[0],
        last_timestamp=timestamps[-1],
    )


def _adjust_order_book(
    order_book: OrderBookSnapshot,
    *,
    bid: float,
    ask: float,
) -> OrderBookSnapshot:
    clone = copy.deepcopy(order_book)
    if clone.bids:
        clone.bids[0].price = bid
    if clone.asks:
        clone.asks[0].price = ask
    clone.timestamp = order_book.timestamp
    return clone


def _utc_now(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
