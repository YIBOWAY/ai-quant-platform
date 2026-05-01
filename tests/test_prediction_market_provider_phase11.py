import json
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.response import addinfourl

import pytest

from quant_system.config.settings import PredictionMarketSettings, Settings
from quant_system.prediction_market.data.polymarket_readonly import (
    PolymarketProviderError,
    PolymarketReadOnlyProvider,
    _default_get_json,
)
from quant_system.prediction_market.provider_factory import build_prediction_market_provider


def test_default_get_json_sends_user_agent_header(monkeypatch) -> None:
    captured_headers: dict[str, str] = {}

    def fake_urlopen(request, timeout=0):
        nonlocal captured_headers
        captured_headers = dict(request.header_items())
        payload = BytesIO(b'{"ok": true}')
        return addinfourl(payload, headers={}, url=request.full_url, code=200)

    monkeypatch.setattr(
        "quant_system.prediction_market.data.polymarket_readonly.urlopen",
        fake_urlopen,
    )

    payload = _default_get_json("https://gamma-api.polymarket.com/markets/keyset?limit=1", 3.0)

    assert payload == {"ok": True}
    assert captured_headers["User-agent"] == "ai-quant-platform/phase11"
    assert captured_headers["Accept"] == "application/json"


def test_polymarket_provider_converts_mocked_markets_and_books() -> None:
    calls: list[str] = []

    def fake_get_json(url: str, timeout: float) -> object:
        calls.append(url)
        assert timeout == 7
        if "gamma-api" in url:
            return {
                "markets": [
                    {
                        "id": "market-1",
                        "event_id": "event-1",
                        "conditionId": "condition-1",
                        "question": "Will Phase 11 stay read-only?",
                        "active": True,
                        "closed": False,
                        "outcomes": json.dumps(["YES", "NO"]),
                        "clobTokenIds": json.dumps(["token-yes", "token-no"]),
                    }
                ],
                "next_cursor": None,
            }
        if "book" in url and "token-yes" in url:
            return {
                "market": "token-yes",
                "bids": [{"price": "0.40", "size": "100"}],
                "asks": [{"price": "0.45", "size": "50"}],
            }
        if "book" in url and "token-no" in url:
            return {
                "market": "token-no",
                "bids": [{"price": "0.48", "size": "100"}],
                "asks": [{"price": "0.50", "size": "50"}],
            }
        raise AssertionError(url)

    provider = PolymarketReadOnlyProvider(get_json=fake_get_json, timeout_seconds=7)

    markets = provider.list_markets(limit=1)
    assert len(markets) == 1
    assert markets[0].market_id == "market-1"
    assert markets[0].condition_id == "condition-1"
    assert [outcome.token_id for outcome in markets[0].outcomes] == ["token-yes", "token-no"]

    books = provider.get_order_books("market-1")
    assert len(books) == 2
    assert books[0].best_ask.price == 0.45
    assert all(book.market_id == "market-1" for book in books)
    assert any("/markets/keyset" in call for call in calls)
    assert any("clob.polymarket.com" in call for call in calls)


def test_polymarket_provider_uses_cache_when_network_fails(tmp_path) -> None:
    def live_get_json(url: str, timeout: float) -> object:
        if "markets/keyset" in url:
            return {
                "markets": [
                    {
                        "id": "market-1",
                        "event_id": "event-1",
                        "conditionId": "condition-1",
                        "question": "Will cache fallback work?",
                        "active": True,
                        "closed": False,
                        "outcomes": json.dumps(["YES", "NO"]),
                        "clobTokenIds": json.dumps(["token-yes", "token-no"]),
                    }
                ],
                "next_cursor": None,
            }
        raise AssertionError(url)

    warm_provider = PolymarketReadOnlyProvider(
        cache_dir=tmp_path,
        cache_ttl_seconds=0,
        cache_stale_if_error_seconds=3600,
        get_json=live_get_json,
    )
    warm_provider.list_markets(limit=1)

    def failing_get_json(url: str, timeout: float) -> object:
        raise HTTPError(url, 403, "blocked", hdrs=None, fp=None)

    cached_provider = PolymarketReadOnlyProvider(
        cache_dir=tmp_path,
        cache_ttl_seconds=0,
        cache_stale_if_error_seconds=3600,
        get_json=failing_get_json,
        max_retries=0,
    )

    markets = cached_provider.list_markets(limit=1)

    assert len(markets) == 1
    assert cached_provider.last_cache_status == "stale_cache"


def test_polymarket_provider_maps_timeout_to_provider_error() -> None:
    def timeout_get_json(url: str, timeout: float) -> object:
        raise TimeoutError("slow")

    provider = PolymarketReadOnlyProvider(get_json=timeout_get_json, max_retries=0)

    with pytest.raises(PolymarketProviderError) as exc_info:
        provider.list_markets()

    assert exc_info.value.code == "provider_timeout"


def test_polymarket_provider_rejects_invalid_market_response() -> None:
    provider = PolymarketReadOnlyProvider(get_json=lambda url, timeout: {"not": "a-list"})

    with pytest.raises(PolymarketProviderError) as exc_info:
        provider.list_markets()

    assert exc_info.value.code == "provider_invalid_response"


def test_polymarket_provider_rejects_http_error_without_traceback() -> None:
    def failing_get_json(url: str, timeout: float) -> object:
        raise HTTPError(url, 500, "server error", hdrs=None, fp=None)

    provider = PolymarketReadOnlyProvider(get_json=failing_get_json, max_retries=0)

    with pytest.raises(PolymarketProviderError) as exc_info:
        provider.list_markets()

    assert exc_info.value.code == "provider_http_error"
    assert "Traceback" not in str(exc_info.value)


def test_polymarket_provider_retries_transient_url_error() -> None:
    attempts = 0

    def flaky_get_json(url: str, timeout: float) -> object:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise URLError(TimeoutError("temporary"))
        return []

    provider = PolymarketReadOnlyProvider(get_json=flaky_get_json, max_retries=1)

    assert provider.list_markets() == []
    assert attempts == 2


def test_prediction_market_provider_factory_defaults_to_sample() -> None:
    settings = Settings()

    provider, label = build_prediction_market_provider(settings)

    assert provider.__class__.__name__ == "SamplePredictionMarketProvider"
    assert label == "sample"


def test_prediction_market_provider_factory_builds_polymarket_when_explicit() -> None:
    settings = Settings(
        prediction_market=PredictionMarketSettings(provider="sample", read_only=True)
    )

    provider, label = build_prediction_market_provider(settings, requested="polymarket")

    assert provider.__class__.__name__ == "PolymarketReadOnlyProvider"
    assert label == "polymarket"


def test_prediction_market_provider_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown prediction market provider"):
        build_prediction_market_provider(Settings(), requested="wallet")
