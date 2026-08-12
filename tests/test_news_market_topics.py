"""Tests for the morning-brief market-topics news lane.

Covers provider clients (payload-level error bodies, no network — httpx
MockTransport with sanitized recorded fixtures), facade failover order and
provenance stamping, and NewsAPI dev-only gating. No real API keys appear
anywhere; dummy placeholder strings are used for key parameters.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from quant_system.api.routes import news as news_routes
from quant_system.api.server import create_app
from quant_system.config.settings import (
    ApiKeySettings,
    LocalTrustSettings,
    MarketNewsSettings,
    Settings,
)
from quant_system.news.facade import NewsFacade, NewsFacadeError
from quant_system.news.market_providers import (
    DEFAULT_ASIA_MARKET_KEYWORDS,
    FinnhubNewsClient,
    MarketNewsProviderError,
    NewsApiClient,
    PolygonNewsClient,
    normalize_keywords,
)
from quant_system.news.models import AiHotItem, AiHotItemsPage

os.environ.setdefault("QS_API_BIND_ADDRESS", "127.0.0.1")

# ---------------------------------------------------------------------------
# Sanitized recorded fixtures (shape-accurate, no real articles or keys)
# ---------------------------------------------------------------------------

POLYGON_OK = {
    "status": "OK",
    "request_id": "fixture",
    "count": 2,
    "results": [
        {
            "id": "poly-1",
            "publisher": {"name": "Example Wire", "homepage_url": "https://example.com"},
            "title": "Hang Seng climbs as tech shares rebound",
            "author": "Fixture Author",
            "published_utc": "2026-08-11T02:30:00Z",
            "article_url": "https://example.com/poly-1",
            "tickers": ["HSI"],
            "description": "Hong Kong stocks advanced in early trade.",
        },
        {
            "id": "poly-2",
            "publisher": {"name": "Example Wire"},
            "title": "Regional currencies steady ahead of data",
            "author": "Fixture Author",
            "published_utc": "2026-08-11T01:00:00Z",
            "article_url": "https://example.com/poly-2",
            "tickers": [],
            "description": "FX markets were quiet.",
        },
    ],
}

FINNHUB_OK = [
    {
        "category": "general",
        "datetime": 1786425600,  # 2026-08-11T08:00:00Z
        "headline": "Nikkei rises as chip shares lead gains",
        "id": 700001,
        "image": "",
        "related": "",
        "source": "Example Daily",
        "summary": "Tokyo equities advanced with Taiwan Semiconductor suppliers higher.",
        "url": "https://example.com/finn-1",
    },
    {
        "category": "general",
        "datetime": 1786422000,
        "headline": "Unrelated sports headline",
        "id": 700002,
        "image": "",
        "related": "",
        "source": "Example Daily",
        "summary": "Nothing to do with markets.",
        "url": "https://example.com/finn-2",
    },
]

NEWSAPI_OK = {
    "status": "ok",
    "totalResults": 1,
    "articles": [
        {
            "source": {"id": "example", "name": "Example Post"},
            "author": "Fixture Author",
            "title": "Asia markets mixed as Hang Seng wavers",
            "description": "Truncated dev-tier description…",
            "url": "https://example.com/newsapi-1",
            "publishedAt": "2026-08-10T09:15:00Z",
            "content": "Truncated content body… [+214 chars]",
        }
    ],
}


def _http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Polygon client
# ---------------------------------------------------------------------------


def test_polygon_parses_and_filters_by_keywords() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json=POLYGON_OK)

    client = PolygonNewsClient(
        base_url="https://api.polygon.io",
        api_key="dummy-polygon-key",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    page = client.search(keywords=["hang seng"], take=10)

    assert seen["path"] == "/v2/reference/news"
    assert seen["params"]["apiKey"] == "dummy-polygon-key"
    assert seen["params"]["order"] == "desc"
    assert page.count == 1
    item = page.items[0]
    assert item.id == "poly-1"
    assert item.title == "Hang Seng climbs as tech shares rebound"
    assert item.source == "Example Wire"
    assert item.url == "https://example.com/poly-1"
    assert item.published_at == "2026-08-11T02:30:00Z"
    assert item.category == "market-topics"
    assert page.warnings == []


def test_polygon_status_error_payload_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "ERROR", "error": "unknown client error occurred"}
        )

    client = PolygonNewsClient(
        base_url="https://api.polygon.io",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    with pytest.raises(MarketNewsProviderError) as excinfo:
        client.search(keywords=["hang seng"])
    assert excinfo.value.code == "polygon_error_payload"
    assert "unknown client error" in excinfo.value.message


def test_polygon_http_error_raises_bad_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"status": "ERROR", "error": "rate limit"})

    client = PolygonNewsClient(
        base_url="https://api.polygon.io",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    with pytest.raises(MarketNewsProviderError) as excinfo:
        client.search(keywords=[])
    assert excinfo.value.code == "polygon_bad_gateway"
    assert "HTTP 429" in excinfo.value.message


def test_polygon_timeout_raises_503() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = PolygonNewsClient(
        base_url="https://api.polygon.io",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    with pytest.raises(MarketNewsProviderError) as excinfo:
        client.search(keywords=[])
    assert excinfo.value.code == "polygon_timeout"
    assert excinfo.value.status_code == 503


def test_polygon_no_keyword_match_is_honest_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=POLYGON_OK)

    client = PolygonNewsClient(
        base_url="https://api.polygon.io",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    page = client.search(keywords=["zzz-no-such-topic"], take=10)
    assert page.count == 0
    assert page.items == []
    assert "polygon_no_matching_articles" in page.warnings


# ---------------------------------------------------------------------------
# Finnhub client
# ---------------------------------------------------------------------------


def test_finnhub_parses_and_converts_epoch() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json=FINNHUB_OK)

    client = FinnhubNewsClient(
        base_url="https://finnhub.io",
        api_key="dummy-finnhub-key",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    page = client.search(keywords=["nikkei"], take=10)

    assert seen["path"] == "/api/v1/news"
    assert seen["params"] == {"category": "general", "token": "dummy-finnhub-key"}
    assert page.count == 1
    item = page.items[0]
    assert item.id == "700001"
    assert item.title == "Nikkei rises as chip shares lead gains"
    assert item.source == "Example Daily"
    assert item.published_at == datetime.fromtimestamp(
        FINNHUB_OK[0]["datetime"], UTC
    ).isoformat()


def test_finnhub_200_error_body_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "Invalid API key"})

    client = FinnhubNewsClient(
        base_url="https://finnhub.io",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    with pytest.raises(MarketNewsProviderError) as excinfo:
        client.search(keywords=[])
    assert excinfo.value.code == "finnhub_error_payload"
    assert "Invalid API key" in excinfo.value.message


def test_finnhub_unexpected_shape_raises_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": "not-a-list"})

    client = FinnhubNewsClient(
        base_url="https://finnhub.io",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    with pytest.raises(MarketNewsProviderError) as excinfo:
        client.search(keywords=[])
    assert excinfo.value.code == "finnhub_invalid_response"


# ---------------------------------------------------------------------------
# NewsAPI client (dev-only lane)
# ---------------------------------------------------------------------------


def test_newsapi_parses_and_marks_truncation() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json=NEWSAPI_OK)

    client = NewsApiClient(
        base_url="https://newsapi.org",
        api_key="dummy-newsapi-key",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    page = client.search(keywords=["hang seng", "nikkei"], take=10)

    assert seen["params"]["q"] == '"hang seng" OR "nikkei"'
    assert seen["params"]["language"] == "en"
    assert seen["params"]["apiKey"] == "dummy-newsapi-key"
    assert page.count == 1
    item = page.items[0]
    assert item.title == "Asia markets mixed as Hang Seng wavers"
    assert item.source == "Example Post"
    assert item.published_at == "2026-08-10T09:15:00Z"
    assert any("truncated" in warning for warning in page.warnings)


def test_newsapi_error_body_raises_with_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            426,
            json={
                "status": "error",
                "code": "upgradeRequired",
                "message": "This parameter is not available on your plan.",
            },
        )

    client = NewsApiClient(
        base_url="https://newsapi.org",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    with pytest.raises(MarketNewsProviderError) as excinfo:
        client.search(keywords=["hang seng"])
    assert excinfo.value.code == "newsapi_bad_gateway"
    assert "HTTP 426" in excinfo.value.message
    assert "upgradeRequired" in excinfo.value.message


def test_newsapi_200_error_payload_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "error", "code": "apiKeyInvalid", "message": "bad key"}
        )

    client = NewsApiClient(
        base_url="https://newsapi.org",
        api_key="dummy",
        timeout_seconds=1,
        http_client=_http(handler),
    )
    with pytest.raises(MarketNewsProviderError) as excinfo:
        client.search(keywords=["hang seng"])
    assert excinfo.value.code == "newsapi_error_payload"
    assert "apiKeyInvalid" in excinfo.value.message


# ---------------------------------------------------------------------------
# Keyword normalization
# ---------------------------------------------------------------------------


def test_normalize_keywords_dedupes_and_lowercases() -> None:
    assert normalize_keywords([" Hang Seng ", "HANG SENG", "", "Nikkei"]) == [
        "hang seng",
        "nikkei",
    ]
    assert normalize_keywords(None) == []


# ---------------------------------------------------------------------------
# Facade: failover order, provenance, dev gating
# ---------------------------------------------------------------------------


def _item(item_id: str, title: str) -> AiHotItem:
    return AiHotItem(
        id=item_id,
        title=title,
        title_en=None,
        url=f"https://example.com/{item_id}",
        source="Example",
        published_at="2026-08-11T08:00:00+00:00",
        summary="summary",
        category="market-topics",
        score=None,
        selected=None,
        raw={"id": item_id},
    )


def _page(*items: AiHotItem, warnings: list[str] | None = None) -> AiHotItemsPage:
    payload = list(items)
    return AiHotItemsPage(
        count=len(payload),
        has_next=False,
        next_cursor=None,
        items=payload,
        warnings=list(warnings or []),
        fetched_at="2026-08-11T08:05:00+00:00",
    )


class FakeMarketClient:
    def __init__(self, page: AiHotItemsPage | None = None, error: str | None = None) -> None:
        self.page = page
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def search(self, *, keywords: list[str], take: int = 20) -> AiHotItemsPage:
        self.calls.append({"keywords": list(keywords), "take": take})
        if self.error is not None:
            raise MarketNewsProviderError(
                code="fake_error",
                message=self.error,
                status_code=502,
            )
        assert self.page is not None
        return self.page


def _settings(
    *,
    market_enabled: bool = True,
    newsapi_dev: bool = False,
    trust_mode: bool = False,
) -> Settings:
    return Settings(
        market_news=MarketNewsSettings(
            enabled=market_enabled,
            newsapi_dev_enabled=newsapi_dev,
        ),
        local_trust=LocalTrustSettings(mode=trust_mode),
    )


def _facade(settings: Settings, clients: dict[str, Any]) -> NewsFacade:
    return NewsFacade(settings=settings, market_clients=clients)


def test_facade_polygon_primary_stamps_provenance() -> None:
    polygon = FakeMarketClient(page=_page(_item("p1", "Hang Seng climbs")))
    finnhub = FakeMarketClient(page=_page(_item("f1", "Nikkei rises")))
    facade = _facade(_settings(), {"polygon": polygon, "finnhub": finnhub})

    result = facade.market_topics(keywords=["hang seng"], take=5)

    assert result["provider"] == "polygon"
    assert result["served_from"] == "primary"
    assert result["keywords"] == ["hang seng"]
    assert result["count"] == 1
    assert result["items"][0]["id"] == "p1"
    assert polygon.calls == [{"keywords": ["hang seng"], "take": 5}]
    assert finnhub.calls == []


def test_facade_defaults_to_asia_keywords() -> None:
    polygon = FakeMarketClient(page=_page(_item("p1", "Asia")))
    facade = _facade(_settings(), {"polygon": polygon})

    result = facade.market_topics()

    assert result["keywords"] == list(DEFAULT_ASIA_MARKET_KEYWORDS)
    assert polygon.calls[0]["keywords"] == list(DEFAULT_ASIA_MARKET_KEYWORDS)


def test_facade_fails_over_to_finnhub_with_note() -> None:
    polygon = FakeMarketClient(error="polygon upstream returned HTTP 429")
    finnhub = FakeMarketClient(page=_page(_item("f1", "Nikkei rises")))
    facade = _facade(_settings(), {"polygon": polygon, "finnhub": finnhub})

    result = facade.market_topics(keywords=["nikkei"])

    assert result["provider"] == "finnhub"
    assert result["served_from"] == "failover"
    assert any(
        "market_news_failover: polygon=" in warning for warning in result["warnings"]
    )


def test_facade_skips_unconfigured_provider() -> None:
    finnhub = FakeMarketClient(page=_page(_item("f1", "Nikkei")))
    facade = _facade(_settings(), {"finnhub": finnhub})

    result = facade.market_topics(keywords=["nikkei"])

    assert result["provider"] == "finnhub"
    assert any(
        "market_news_failover: polygon=not_configured" in warning
        for warning in result["warnings"]
    )


def test_facade_raises_unavailable_when_all_lanes_fail() -> None:
    polygon = FakeMarketClient(error="polygon down")
    finnhub = FakeMarketClient(error="finnhub down")
    facade = _facade(_settings(), {"polygon": polygon, "finnhub": finnhub})

    with pytest.raises(NewsFacadeError) as excinfo:
        facade.market_topics(keywords=["nikkei"])

    assert excinfo.value.code == "market_news_unavailable"
    assert excinfo.value.status_code == 503
    assert "polygon=polygon down" in excinfo.value.message
    assert "finnhub=finnhub down" in excinfo.value.message


def test_facade_disabled_lane_raises() -> None:
    facade = _facade(_settings(market_enabled=False), {"polygon": FakeMarketClient()})
    with pytest.raises(NewsFacadeError) as excinfo:
        facade.market_topics()
    assert excinfo.value.code == "market_news_disabled"


def test_facade_newsapi_skipped_when_dev_flag_off() -> None:
    newsapi = FakeMarketClient(page=_page(_item("n1", "NewsAPI")))
    facade = _facade(_settings(newsapi_dev=False, trust_mode=True), {"newsapi": newsapi})

    with pytest.raises(NewsFacadeError) as excinfo:
        facade.market_topics()

    assert "newsapi=dev_only_gated" in excinfo.value.message
    assert newsapi.calls == []


def test_facade_newsapi_skipped_without_local_trust_mode() -> None:
    newsapi = FakeMarketClient(page=_page(_item("n1", "NewsAPI")))
    facade = _facade(_settings(newsapi_dev=True, trust_mode=False), {"newsapi": newsapi})

    with pytest.raises(NewsFacadeError) as excinfo:
        facade.market_topics()

    assert "newsapi=dev_only_gated" in excinfo.value.message
    assert newsapi.calls == []


def test_facade_newsapi_served_in_dev_with_trust_mode() -> None:
    newsapi = FakeMarketClient(page=_page(_item("n1", "Dev lane article")))
    facade = _facade(_settings(newsapi_dev=True, trust_mode=True), {"newsapi": newsapi})

    result = facade.market_topics(keywords=["hang seng"])

    assert result["provider"] == "newsapi"
    assert result["served_from"] == "failover"
    assert newsapi.calls == [{"keywords": ["hang seng"], "take": 20}]
    assert any("dev-only lane" in warning for warning in result["warnings"])


def test_facade_empty_provider_result_is_honest_not_failover() -> None:
    polygon = FakeMarketClient(
        page=_page(warnings=["polygon_no_matching_articles"])
    )
    finnhub = FakeMarketClient(page=_page(_item("f1", "Nikkei")))
    facade = _facade(_settings(), {"polygon": polygon, "finnhub": finnhub})

    result = facade.market_topics(keywords=["no-such-topic"])

    assert result["provider"] == "polygon"
    assert result["count"] == 0
    assert result["items"] == []
    assert finnhub.calls == []


# ---------------------------------------------------------------------------
# Route-level: provenance in HTTP response, 503 mapping, status section
# ---------------------------------------------------------------------------


def _route_client(tmp_path, monkeypatch, *, settings: Settings, clients: dict) -> TestClient:
    monkeypatch.setattr(
        news_routes, "_market_clients_for_settings", lambda _s: dict(clients)
    )
    return TestClient(create_app(settings=settings, output_dir=tmp_path))


def test_route_market_topics_happy_path(tmp_path, monkeypatch) -> None:
    polygon = FakeMarketClient(page=_page(_item("p1", "Hang Seng climbs")))
    client = _route_client(
        tmp_path, monkeypatch, settings=_settings(), clients={"polygon": polygon}
    )

    response = client.get("/api/news/market-topics?keywords=hang%20seng&take=5")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "polygon"
    assert body["served_from"] == "primary"
    assert body["keywords"] == ["hang seng"]
    assert body["count"] == 1
    assert body["items"][0]["title"] == "Hang Seng climbs"
    assert polygon.calls == [{"keywords": ["hang seng"], "take": 5}]


def test_route_market_topics_unavailable_maps_503(tmp_path, monkeypatch) -> None:
    client = _route_client(tmp_path, monkeypatch, settings=_settings(), clients={})

    response = client.get("/api/news/market-topics")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "market_news_unavailable"


def test_route_status_reports_market_news_without_keys(tmp_path, monkeypatch) -> None:
    settings = _settings()
    settings = settings.model_copy(
        update={"api_keys": ApiKeySettings()}
    )
    monkeypatch.setattr(
        news_routes, "_market_clients_for_settings", lambda _s: {}
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/news/status")

    assert response.status_code == 200
    market = response.json()["providers"]["market_news"]
    assert market["enabled"] is True
    assert market["failover_order"] == ["polygon", "finnhub", "newsapi"]
    assert market["providers"]["polygon"]["key_configured"] is False
    assert market["providers"]["finnhub"]["key_configured"] is False
    assert market["providers"]["newsapi"]["dev_only"] is True
