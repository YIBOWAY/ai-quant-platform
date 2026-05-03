from datetime import UTC, datetime

import pytest

from quant_system.prediction_market.collector import (
    PredictionMarketSnapshotCollector,
    ensure_no_polymarket_credentials_in_env,
    seed_sample_history_dataset,
)
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.storage import PredictionMarketSnapshotStore


def test_prediction_market_collector_writes_partitioned_history(tmp_path) -> None:
    store = PredictionMarketSnapshotStore(tmp_path)
    collector = PredictionMarketSnapshotCollector(
        provider=SamplePredictionMarketProvider(),
        provider_label="sample",
        store=store,
        interval_seconds=1.0,
        duration_seconds=0.0,
        limit=10,
    )

    summary = collector.collect_once(fetched_at="2026-01-01T00:00:00Z")

    assert summary.market_count == 2
    assert summary.snapshot_record_count == 5
    records = store.load_history_records(provider="sample")
    assert len(records) == 5
    assert all(
        "date=2026-01-01" in str(path)
        for path in tmp_path.glob("date=*/market_id=*/*")
    )


def test_prediction_market_collector_run_honors_duration(tmp_path) -> None:
    class Clock:
        def __init__(self) -> None:
            self.values = iter(
                [
                    datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC),
                ]
            )

        def __call__(self) -> datetime:
            return next(self.values)

    store = PredictionMarketSnapshotStore(tmp_path)
    collector = PredictionMarketSnapshotCollector(
        provider=SamplePredictionMarketProvider(),
        provider_label="sample",
        store=store,
        interval_seconds=1.0,
        duration_seconds=1.0,
        limit=10,
        sleep_fn=lambda seconds: None,
        now_fn=Clock(),
    )

    summary = collector.run()

    assert summary.iteration_count == 1
    assert summary.snapshot_record_count == 5


def test_seed_sample_history_dataset_produces_three_timepoints(tmp_path) -> None:
    summary = seed_sample_history_dataset(tmp_path)
    store = PredictionMarketSnapshotStore(tmp_path)
    records = store.load_history_records(provider="sample")

    assert summary.iteration_count == 3
    assert summary.snapshot_record_count == 15
    assert len(records) == 15
    assert len({record.timestamp_utc for record in records}) == 3


def test_collector_rejects_polymarket_credentials_from_env(monkeypatch) -> None:
    monkeypatch.setenv("QS_POLYMARKET_API_KEY", "secret")

    with pytest.raises(ValueError, match="read-only"):
        ensure_no_polymarket_credentials_in_env()
