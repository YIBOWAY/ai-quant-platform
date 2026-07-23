import os
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from quant_system.api.routes import news as news_routes
from quant_system.api.server import create_app
from quant_system.config.settings import AiHotSettings, Settings
from quant_system.news.aihot_client import AiHotProviderError
from quant_system.news.daily_report_repository import daily_report_cache_warning
from quant_system.news.models import (
    AiHotDailiesPage,
    AiHotDaily,
    AiHotDailyIndex,
    AiHotItem,
    AiHotItemsPage,
)

# Local .env may enable Hermes gateway; declare loopback bind so create_app can start.
os.environ.setdefault("QS_API_BIND_ADDRESS", "127.0.0.1")


class FakeAiHotClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def items(self, **kwargs) -> AiHotItemsPage:
        self.calls.append(("items", kwargs))
        return AiHotItemsPage(
            count=1,
            has_next=False,
            next_cursor=None,
            items=[
                AiHotItem(
                    id="item-1",
                    title="OpenAI 发布新模型",
                    title_en="OpenAI releases a new model",
                    url="https://example.com/openai",
                    source="OpenAI Blog",
                    published_at="2026-06-28T15:30:00.000Z",
                    summary="中文摘要",
                    category="ai-models",
                    score=0.91,
                    selected=True,
                    raw={"id": "item-1"},
                )
            ],
            warnings=[],
        )

    def daily(self, **kwargs) -> AiHotDaily:
        self.calls.append(("daily", kwargs))
        return AiHotDaily(
            date="2026-06-28",
            generated_at="2026-06-28T00:01:00.000Z",
            window_start="2026-06-27T00:00:00.000Z",
            window_end="2026-06-28T00:00:00.000Z",
            lead={"title": "今日要点"},
            sections=[{"label": "模型发布/更新", "items": []}],
            flashes=[],
            warnings=[],
            raw={"date": "2026-06-28"},
        )

    def dailies(self, **kwargs) -> AiHotDailiesPage:
        self.calls.append(("dailies", kwargs))
        return AiHotDailiesPage(
            count=1,
            items=[
                AiHotDailyIndex(
                    date="2026-06-28",
                    generated_at="2026-06-28T00:01:00.000Z",
                    lead_title="今日要点",
                    raw={"date": "2026-06-28"},
                )
            ],
            warnings=[],
        )


def test_default_daily_cache_date_uses_asia_shanghai_boundary() -> None:
    assert news_routes._current_brief_date(
        datetime(2026, 7, 13, 15, 59, 59, tzinfo=UTC)
    ) == "2026-07-13"
    assert news_routes._current_brief_date(
        datetime(2026, 7, 13, 16, 0, 0, tzinfo=UTC)
    ) == "2026-07-14"


def test_aihot_items_route_returns_research_only_payload(tmp_path, monkeypatch) -> None:
    fake = FakeAiHotClient()
    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _settings: fake)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/news/aihot/items",
        params={
            "mode": "all",
            "category": "ai-models",
            "q": "OpenAI",
            "since": "2026-06-28T00:00:00Z",
            "take": "2",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert fake.calls == [
        (
            "items",
            {
                "mode": "all",
                "category": "ai-models",
                "q": "OpenAI",
                "since": "2026-06-28T00:00:00Z",
                "cursor": None,
                "take": 2,
            },
        )
    ]
    assert payload["provider"] == "aihot"
    assert payload["provider_beta"] is True
    assert payload["count"] == 1
    assert payload["items"][0]["title"] == "OpenAI 发布新模型"
    assert payload["research_safety"]["research_only"] is True
    assert payload["research_safety"]["does_not_trigger_trading"] is True
    assert payload["safety"]["live_trading_enabled"] is False
    assert payload["preference"] == "auto"
    assert payload["served_from"] == "primary"
    assert "research_safety" in payload
    assert "safety" not in payload or payload.get("safety")


def test_aihot_items_route_caches_live_page_best_effort(tmp_path, monkeypatch) -> None:
    fake = FakeAiHotClient()
    cached: list[tuple[AiHotItemsPage, object]] = []

    def capture_cache(page: AiHotItemsPage, *, settings: Settings, query) -> None:
        cached.append((page, query))

    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _settings: fake)
    monkeypatch.setattr(news_routes, "_cache_items_page", capture_cache, raising=False)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/news/aihot/items",
        params={"q": "OpenAI", "since": "2026-06-28T00:00:00Z", "take": "2"},
    )

    assert response.status_code == 200
    assert len(cached) == 1
    page, query = cached[0]
    assert page.items[0].id == "item-1"
    assert query.mode == "selected"
    assert query.q == "OpenAI"
    assert query.since == "2026-06-28T00:00:00Z"
    assert query.take == 2


def test_aihot_daily_route_caches_live_report_best_effort(tmp_path, monkeypatch) -> None:
    fake = FakeAiHotClient()
    cached: list[AiHotDaily] = []

    def capture_cache(daily: AiHotDaily, *, settings: Settings) -> None:
        cached.append(daily)

    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _settings: fake)
    monkeypatch.setattr(news_routes, "_cache_daily_report", capture_cache, raising=False)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/news/aihot/daily", params={"date": "2026-06-28"})

    assert response.status_code == 200
    assert len(cached) == 1
    assert cached[0].date == "2026-06-28"
    assert fake.calls == [("daily", {"date": "2026-06-28"})]


def test_aihot_client_for_settings_reuses_client_until_closed() -> None:
    news_routes.close_aihot_clients()
    settings = Settings(aihot=AiHotSettings(cache_ttl_seconds=30))
    try:
        first = news_routes._client_for_settings(settings)
        second = news_routes._client_for_settings(settings)

        assert first is second
    finally:
        news_routes.close_aihot_clients()

    third = news_routes._client_for_settings(settings)
    try:
        assert third is not first
    finally:
        news_routes.close_aihot_clients()


def test_aihot_items_route_returns_cached_page_when_upstream_fails(
    tmp_path,
    monkeypatch,
) -> None:
    class TimeoutClient:
        def items(self, **_kwargs):
            raise AiHotProviderError(
                code="aihot_timeout",
                message="AI HOT request timed out",
                status_code=503,
            )

    captured_queries: list[object] = []

    def cached_page(*, settings: Settings, query) -> AiHotItemsPage:
        captured_queries.append(query)
        return AiHotItemsPage(
            count=1,
            has_next=False,
            next_cursor=None,
            items=[
                AiHotItem(
                    id="cached-1",
                    title="缓存里的 AI 新闻",
                    title_en=None,
                    url="https://example.com/cached",
                    source="Cached Source",
                    published_at="2026-06-28T12:00:00.000Z",
                    summary="上游失败时来自本地数据库缓存。",
                    category="industry",
                    score=0.7,
                    selected=True,
                    raw={"id": "cached-1"},
                )
            ],
            warnings=["Using cached AI HOT items from the local database."],
            fetched_at="2026-06-28T12:30:00+00:00",
        )

    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _settings: TimeoutClient())
    monkeypatch.setattr(news_routes, "_load_cached_items_page", cached_page, raising=False)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/news/aihot/items", params={"q": "OpenAI", "take": "2"})

    assert response.status_code == 200
    payload = response.json()
    assert captured_queries[0].q == "OpenAI"
    assert payload["items"][0]["id"] == "cached-1"
    assert payload["fetched_at"] == "2026-06-28T12:30:00+00:00"
    assert "Using cached AI HOT items from the local database." in payload["warnings"]
    assert "AI HOT request timed out" in payload["warnings"]
    assert payload["research_safety"]["does_not_trigger_trading"] is True


def test_aihot_daily_route_returns_cached_report_when_upstream_fails(
    tmp_path,
    monkeypatch,
) -> None:
    class TimeoutClient:
        def daily(self, **_kwargs):
            raise AiHotProviderError(
                code="aihot_timeout",
                message="AI HOT request timed out",
                status_code=503,
            )

    captured_dates: list[str] = []

    def cached_daily(date: str, *, settings: Settings) -> AiHotDaily:
        captured_dates.append(date)
        return AiHotDaily(
            date=date,
            generated_at="2026-07-08T00:01:00+00:00",
            window_start="2026-07-07T00:00:00+00:00",
            window_end="2026-07-08T00:00:00+00:00",
            lead={"title": "Cached daily"},
            sections=[{"label": "Models"}],
            flashes=[],
            warnings=[daily_report_cache_warning(date)],
            raw={"date": date},
            fetched_at="2026-07-08T08:00:00+00:00",
        )

    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _settings: TimeoutClient())
    monkeypatch.setattr(news_routes, "_load_cached_daily_report", cached_daily, raising=False)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/news/aihot/daily", params={"date": "2026-07-08"})

    assert response.status_code == 200
    assert captured_dates == ["2026-07-08"]
    payload = response.json()
    assert payload["date"] == "2026-07-08"
    assert payload["lead"] == {"title": "Cached daily"}
    assert payload["research_safety"]["research_only"] is True
    assert payload["research_safety"]["does_not_trigger_trading"] is True
    assert daily_report_cache_warning("2026-07-08") in payload["warnings"]
    assert "AI HOT request timed out" in payload["warnings"]
    assert any("external beta source" in warning for warning in payload["warnings"])


def test_aihot_daily_and_dailies_routes_proxy_read_only(tmp_path, monkeypatch) -> None:
    fake = FakeAiHotClient()
    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _settings: fake)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    daily_response = client.get("/api/news/aihot/daily", params={"date": "2026-06-28"})
    dailies_response = client.get("/api/news/aihot/dailies", params={"take": "5"})

    assert daily_response.status_code == 200
    assert dailies_response.status_code == 200
    assert fake.calls == [
        ("daily", {"date": "2026-06-28"}),
        ("dailies", {"take": 5}),
    ]
    daily_payload = daily_response.json()
    dailies_payload = dailies_response.json()
    assert daily_payload["date"] == "2026-06-28"
    assert daily_payload["research_safety"]["not_investment_advice"] is True
    assert daily_payload["preference"] == "auto"
    assert daily_payload["served_from"] == "primary"
    assert dailies_payload["items"][0]["lead_title"] == "今日要点"
    assert dailies_payload["preference"] == "auto"
    assert dailies_payload["served_from"] == "primary"


def test_aihot_disabled_returns_503_without_calling_upstream(tmp_path, monkeypatch) -> None:
    calls = 0

    def fail_if_called(_settings):
        nonlocal calls
        calls += 1
        raise AssertionError("disabled route must not build an upstream client")

    monkeypatch.setattr(news_routes, "_client_for_settings", fail_if_called)
    settings = Settings(aihot=AiHotSettings(enabled=False))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/news/aihot/items")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "aihot_disabled"
    assert calls == 0


def test_aihot_invalid_query_params_return_422_without_calling_upstream(
    tmp_path,
    monkeypatch,
) -> None:
    calls = 0

    def fail_if_called(_settings):
        nonlocal calls
        calls += 1
        raise AssertionError("invalid query params must fail before upstream client creation")

    monkeypatch.setattr(news_routes, "_client_for_settings", fail_if_called)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    bad_category = client.get("/api/news/aihot/items", params={"category": "bad-category"})
    bad_date = client.get("/api/news/aihot/daily", params={"date": "2026/06/28"})

    assert bad_category.status_code == 422
    assert bad_date.status_code == 422
    assert calls == 0


def test_aihot_status_does_not_probe_upstream(tmp_path, monkeypatch) -> None:
    calls = 0

    def fail_if_called(_settings):
        nonlocal calls
        calls += 1
        raise AssertionError("status route must not probe AI HOT")

    monkeypatch.setattr(news_routes, "_client_for_settings", fail_if_called)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/news/aihot/status")

    assert response.status_code == 200
    payload = response.json()
    assert calls == 0
    assert payload["enabled"] is True
    assert payload["provider_beta"] is True
    assert payload["base_url"] == "https://aihot.virxact.com"
    assert payload["research_safety"]["verify_original_source"] is True


def test_aihot_provider_errors_map_to_structured_http_errors(
    tmp_path,
    monkeypatch,
) -> None:
    class TimeoutClient:
        def items(self, **_kwargs):
            raise AiHotProviderError(
                code="aihot_timeout",
                message="AI HOT request timed out",
                status_code=503,
            )

    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _settings: TimeoutClient())
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/news/aihot/items")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "aihot_timeout",
        "message": "AI HOT request timed out",
    }
