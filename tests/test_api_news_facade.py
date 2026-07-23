"""HTTP matrix for NewsFacade neutral + alias routes."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from quant_system.api.routes import news as news_routes
from quant_system.api.server import create_app
from quant_system.config.settings import AiHotSettings, HorizonSettings, NewsSettings, Settings
from quant_system.news.aihot_client import AiHotProviderError
from quant_system.news.models import AiHotDaily, AiHotItem, AiHotItemsPage

os.environ.setdefault("QS_API_BIND_ADDRESS", "127.0.0.1")


def _item(item_id: str, title: str = "News") -> AiHotItem:
    return AiHotItem(
        id=item_id,
        title=title,
        title_en=None,
        url=f"https://example.com/{item_id}",
        source="Example",
        published_at="2026-07-23T12:00:00+00:00",
        summary="summary",
        category="ai-models",
        score=0.9,
        selected=True,
        raw={"id": item_id},
    )


def _page(*items: AiHotItem, warnings: list[str] | None = None) -> AiHotItemsPage:
    payload = list(items) or [_item("x")]
    return AiHotItemsPage(
        count=len(payload),
        has_next=False,
        next_cursor=None,
        items=payload,
        warnings=list(warnings or []),
        fetched_at="2026-07-23T12:05:00+00:00",
    )


class LiveClient:
    def items(self, **_kwargs: Any) -> AiHotItemsPage:
        return _page(_item("live-1", "Live AI HOT"))

    def daily(self, **_kwargs: Any) -> AiHotDaily:
        return AiHotDaily(
            date="2026-07-23",
            generated_at="2026-07-23T00:01:00+00:00",
            window_start=None,
            window_end=None,
            lead={"title": "Live"},
            sections=[],
            flashes=[],
            warnings=[],
            raw={},
        )

    def dailies(self, **_kwargs: Any):
        from quant_system.news.models import AiHotDailiesPage, AiHotDailyIndex

        return AiHotDailiesPage(
            count=1,
            items=[AiHotDailyIndex(date="2026-07-23", generated_at=None, lead_title="Live", raw={})],
            warnings=[],
        )


class TimeoutClient:
    def items(self, **_kwargs: Any) -> AiHotItemsPage:
        raise AiHotProviderError(
            code="aihot_timeout",
            message="AI HOT request timed out",
            status_code=503,
        )

    def daily(self, **_kwargs: Any) -> AiHotDaily:
        raise AiHotProviderError(
            code="aihot_timeout",
            message="AI HOT request timed out",
            status_code=503,
        )

    def dailies(self, **_kwargs: Any):
        raise AiHotProviderError(
            code="aihot_timeout",
            message="AI HOT request timed out",
            status_code=503,
        )


def _settings(**kwargs: Any) -> Settings:
    return Settings(
        aihot=AiHotSettings(enabled=kwargs.get("aihot_enabled", True)),
        news=NewsSettings(
            source_preference=kwargs.get("preference", "auto"),
            failover_enabled=kwargs.get("failover_enabled", True),
        ),
        horizon=HorizonSettings(enabled=kwargs.get("horizon_enabled", True)),
    )


def _client(tmp_path, monkeypatch, *, settings: Settings | None = None, aihot=None) -> TestClient:
    monkeypatch.setattr(
        news_routes,
        "_client_for_settings",
        lambda _s: aihot if aihot is not None else LiveClient(),
    )
    # Default: no horizon / no cache unless tests override.
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_latest_horizon_run",
        lambda **_k: None,
    )
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_horizon_items_page",
        lambda **_k: None,
    )
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_horizon_daily",
        lambda **_k: None,
    )
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_horizon_dailies",
        lambda **_k: None,
    )
    monkeypatch.setattr(news_routes, "_cache_items_page", lambda *a, **k: None)
    monkeypatch.setattr(news_routes, "_load_cached_items_page", lambda **k: None)
    monkeypatch.setattr(news_routes, "_cache_daily_report", lambda *a, **k: None)
    monkeypatch.setattr(news_routes, "_load_cached_daily_report", lambda *a, **k: None)
    return TestClient(create_app(settings=settings or _settings(), output_dir=tmp_path))


def test_primary_aihot_on_neutral_route(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, aihot=LiveClient())
    response = client.get("/api/news/items", params={"take": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "aihot"
    assert payload["served_from"] == "primary"
    assert payload["preference"] == "auto"
    assert payload["items"][0]["id"] == "live-1"
    assert payload["research_safety"]["research_only"] is True


def test_failover_horizon_on_alias_route(tmp_path, monkeypatch) -> None:
    run = {
        "run_id": "20260723T120000Z-ab12",
        "generated_at": datetime.now(UTC).isoformat(),
        "ingested_at": datetime.now(UTC).isoformat(),
        "item_count": 2,
        "status": "ingested",
    }
    client = _client(tmp_path, monkeypatch, aihot=TimeoutClient())
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_latest_horizon_run",
        lambda **_k: run,
    )
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_horizon_items_page",
        lambda **_k: _page(_item("hz-1", "Horizon")),
    )

    response = client.get("/api/news/aihot/items")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "failover"
    assert any("failover" in w for w in payload["warnings"])
    assert any("horizon_run_id=20260723T120000Z-ab12" in w for w in payload["warnings"])


def test_cache_fallback(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, aihot=TimeoutClient())
    monkeypatch.setattr(
        news_routes,
        "_load_cached_items_page",
        lambda **_k: _page(
            _item("cached-1"),
            warnings=["Using cached AI HOT items from the local database."],
        ),
    )
    response = client.get("/api/news/items")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "aihot"
    assert payload["served_from"] == "cache"
    assert payload["items"][0]["id"] == "cached-1"
    assert any("aihot_cache_fallback" in w for w in payload["warnings"])


def test_unavailable_returns_503(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, aihot=TimeoutClient())
    response = client.get("/api/news/items")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "news_unavailable"


def test_aihot_disabled_auto_failsover_to_horizon(tmp_path, monkeypatch) -> None:
    run = {
        "run_id": "run-disabled",
        "generated_at": datetime.now(UTC).isoformat(),
        "ingested_at": datetime.now(UTC).isoformat(),
        "item_count": 1,
        "status": "ingested",
    }
    calls = 0

    def fail_if_called(_settings):
        nonlocal calls
        calls += 1
        raise AssertionError("disabled auto must not build aihot client")

    monkeypatch.setattr(news_routes, "_client_for_settings", fail_if_called)
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_latest_horizon_run",
        lambda **_k: run,
    )
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_horizon_items_page",
        lambda **_k: _page(_item("hz-disabled")),
    )
    monkeypatch.setattr(news_routes, "_cache_items_page", lambda *a, **k: None)
    monkeypatch.setattr(news_routes, "_load_cached_items_page", lambda **k: None)
    settings = _settings(aihot_enabled=False)
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/news/items")
    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "failover"
    assert calls == 0


def test_forced_aihot_disabled_still_503(tmp_path, monkeypatch) -> None:
    calls = 0

    def fail_if_called(_settings):
        nonlocal calls
        calls += 1
        raise AssertionError("forced disabled must not build client")

    monkeypatch.setattr(news_routes, "_client_for_settings", fail_if_called)
    settings = _settings(aihot_enabled=False)
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/news/items", params={"preference": "aihot"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "aihot_disabled"
    assert calls == 0


def test_status_does_not_call_aihot_client(tmp_path, monkeypatch) -> None:
    calls = 0

    def fail_if_called(_settings):
        nonlocal calls
        calls += 1
        raise AssertionError("status must not probe aihot")

    # status builds facade with client only when aihot enabled — but must not call it.
    class ProbeClient(LiveClient):
        def items(self, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("status must not call items")

        def daily(self, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("status must not call daily")

        def dailies(self, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("status must not call dailies")

    monkeypatch.setattr(news_routes, "_client_for_settings", lambda _s: ProbeClient())
    monkeypatch.setattr(
        news_routes.horizon_repository,
        "load_latest_horizon_run",
        lambda **_k: {
            "run_id": "r1",
            "generated_at": "t",
            "ingested_at": "t",
            "item_count": 1,
            "status": "ingested",
        },
    )
    client = TestClient(create_app(settings=_settings(), output_dir=tmp_path))
    response = client.get("/api/news/status")
    assert response.status_code == 200
    payload = response.json()
    assert calls == 0
    assert payload["preference_default"] == "auto"
    assert payload["providers"]["horizon"]["fresh"] is True
    assert payload["failover"]["order"] == ["aihot_live", "horizon_pg", "aihot_cache"]
    assert payload["research_safety"]["does_not_trigger_trading"] is True
    assert "research_safety" in payload
