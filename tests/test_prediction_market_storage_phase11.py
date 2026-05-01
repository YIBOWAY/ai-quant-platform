import json
from pathlib import Path

from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.storage import (
    PredictionMarketReplayProvider,
    PredictionMarketSnapshotStore,
)


def test_snapshot_store_persists_market_and_order_books_as_jsonl(tmp_path) -> None:
    provider = SamplePredictionMarketProvider()
    market = provider.list_markets()[0]
    books = provider.get_order_books(market.market_id)
    store = PredictionMarketSnapshotStore(tmp_path)

    path = store.write_snapshot(
        provider="sample",
        market=market,
        order_books=books,
        source_endpoint="sample://deterministic",
    )

    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["provider"] == "sample"
    assert payload["market_id"] == market.market_id
    assert payload["condition_id"] == market.condition_id
    assert payload["source_endpoint"] == "sample://deterministic"
    assert payload["market"]["market_id"] == market.market_id
    assert payload["order_books"][0]["market_id"] == market.market_id


def test_replay_provider_loads_latest_snapshot(tmp_path) -> None:
    provider = SamplePredictionMarketProvider()
    market = provider.list_markets()[0]
    books = provider.get_order_books(market.market_id)
    store = PredictionMarketSnapshotStore(tmp_path)
    store.write_snapshot(
        provider="sample",
        market=market,
        order_books=books,
        source_endpoint="sample://deterministic",
    )

    replay = PredictionMarketReplayProvider(tmp_path)
    markets = replay.list_markets()

    assert [item.market_id for item in markets] == [market.market_id]
    replay_books = replay.get_order_books(market.market_id)
    assert len(replay_books) == len(books)
    assert replay_books[0].best_ask.price == books[0].best_ask.price


def test_replay_provider_raises_for_missing_market(tmp_path) -> None:
    replay = PredictionMarketReplayProvider(Path(tmp_path))

    assert replay.list_markets() == []
