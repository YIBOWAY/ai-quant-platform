"""Unit tests for NewsFacade auto/failover selection (no HTTP)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from quant_system.config.settings import (
    AiHotSettings,
    HorizonSettings,
    NewsSettings,
    Settings,
)
from quant_system.news.aihot_client import AiHotProviderError
from quant_system.news.facade import NewsFacade, NewsFacadeError
from quant_system.news.models import (
    AiHotDailiesPage,
    AiHotDaily,
    AiHotDailyIndex,
    AiHotItem,
    AiHotItemsPage,
)


def _item(item_id: str = "item-1", *, title: str = "AI news") -> AiHotItem:
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


def _items_page(*items: AiHotItem, warnings: list[str] | None = None) -> AiHotItemsPage:
    payload = list(items) or [_item()]
    return AiHotItemsPage(
        count=len(payload),
        has_next=False,
        next_cursor=None,
        items=payload,
        warnings=list(warnings or []),
        fetched_at="2026-07-23T12:05:00+00:00",
    )


def _daily(date: str = "2026-07-23", *, warnings: list[str] | None = None) -> AiHotDaily:
    return AiHotDaily(
        date=date,
        generated_at=f"{date}T00:01:00+00:00",
        window_start=f"{date}T00:00:00+00:00",
        window_end=f"{date}T23:59:59+00:00",
        lead={"title": f"Lead {date}"},
        sections=[{"label": "Models"}],
        flashes=[],
        warnings=list(warnings or []),
        raw={"date": date},
        fetched_at=f"{date}T08:00:00+00:00",
    )


def _dailies(*dates: str) -> AiHotDailiesPage:
    items = [
        AiHotDailyIndex(
            date=d,
            generated_at=f"{d}T00:01:00+00:00",
            lead_title=f"Lead {d}",
            raw={"date": d},
        )
        for d in (dates or ("2026-07-23",))
    ]
    return AiHotDailiesPage(count=len(items), items=items, warnings=[])


def _settings(
    *,
    aihot_enabled: bool = True,
    horizon_enabled: bool = True,
    failover_enabled: bool = True,
    preference: str = "auto",
    max_age_seconds: int = 129_600,
) -> Settings:
    return Settings(
        aihot=AiHotSettings(enabled=aihot_enabled),
        news=NewsSettings(source_preference=preference, failover_enabled=failover_enabled),  # type: ignore[arg-type]
        horizon=HorizonSettings(enabled=horizon_enabled, max_age_seconds=max_age_seconds),
    )


class FakeOk:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def items(self, **kwargs: Any) -> AiHotItemsPage:
        self.calls.append(("items", kwargs))
        return _items_page(_item("aihot-1", title="AI HOT live"))

    def daily(self, **kwargs: Any) -> AiHotDaily:
        self.calls.append(("daily", kwargs))
        return _daily("2026-07-23")

    def dailies(self, **kwargs: Any) -> AiHotDailiesPage:
        self.calls.append(("dailies", kwargs))
        return _dailies("2026-07-23", "2026-07-22")


class FakeTimeout:
    def __init__(self, message: str = "AI HOT request timed out") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.message = message

    def items(self, **kwargs: Any) -> AiHotItemsPage:
        self.calls.append(("items", kwargs))
        raise AiHotProviderError(code="aihot_timeout", message=self.message, status_code=503)

    def daily(self, **kwargs: Any) -> AiHotDaily:
        self.calls.append(("daily", kwargs))
        raise AiHotProviderError(code="aihot_timeout", message=self.message, status_code=503)

    def dailies(self, **kwargs: Any) -> AiHotDailiesPage:
        self.calls.append(("dailies", kwargs))
        raise AiHotProviderError(code="aihot_timeout", message=self.message, status_code=503)


@dataclass
class HorizonState:
    fresh_run: dict[str, Any] | None = None
    items: AiHotItemsPage | None = None
    daily: AiHotDaily | None = None
    dailies: AiHotDailiesPage | None = None
    any_items: AiHotItemsPage | None = None
    any_daily: AiHotDaily | None = None


def _fresh_run(
    run_id: str = "20260723T120000Z-ab12",
    *,
    generated_at: str | None = None,
    item_count: int = 3,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "run_id": run_id,
        "generated_at": generated_at or now.isoformat(),
        "ingested_at": now.isoformat(),
        "item_count": item_count,
        "status": "ingested",
        "daily_date": now.date().isoformat(),
    }


class RecordingCache:
    def __init__(
        self,
        *,
        items: AiHotItemsPage | None = None,
        daily: AiHotDaily | None = None,
    ) -> None:
        self.items = items
        self.daily = daily
        self.cached_items: list[AiHotItemsPage] = []
        self.cached_dailies: list[AiHotDaily] = []

    def cache_items(self, page: AiHotItemsPage, **_kwargs: Any) -> None:
        self.cached_items.append(page)

    def load_items(self, **_kwargs: Any) -> AiHotItemsPage | None:
        return self.items

    def cache_daily(self, daily: AiHotDaily, **_kwargs: Any) -> None:
        self.cached_dailies.append(daily)

    def load_daily(self, date: str, **_kwargs: Any) -> AiHotDaily | None:
        if self.daily is None:
            return None
        if date and self.daily.date != date:
            return None
        return self.daily


def _facade(
    *,
    client: Any = None,
    settings: Settings | None = None,
    horizon: HorizonState | None = None,
    cache: RecordingCache | None = None,
    last_error: dict[str, Any] | None = None,
) -> NewsFacade:
    hz = horizon or HorizonState()
    cache = cache or RecordingCache()
    error_box: dict[str, Any] = {"value": last_error}

    def remember(exc: AiHotProviderError) -> None:
        error_box["value"] = {
            "code": exc.code,
            "message": exc.message,
            "at": datetime.now(UTC).isoformat(),
        }

    return NewsFacade(
        settings=settings or _settings(),
        aihot_client=client,
        load_latest_horizon_run=lambda **_k: hz.fresh_run,
        load_horizon_items_page=lambda **_k: hz.items if hz.fresh_run is not None else hz.any_items,
        load_horizon_daily=lambda **_k: hz.daily if hz.fresh_run is not None else hz.any_daily,
        load_horizon_dailies=lambda **_k: hz.dailies,
        load_any_horizon_items=lambda **_k: hz.any_items if hz.any_items is not None else hz.items,
        load_any_horizon_daily=lambda **_k: hz.any_daily if hz.any_daily is not None else hz.daily,
        cache_aihot_items=cache.cache_items,
        load_cached_aihot_items=cache.load_items,
        cache_aihot_daily=cache.cache_daily,
        load_cached_aihot_daily=cache.load_daily,
        remember_error=remember,
        last_error_getter=lambda: error_box["value"],
    )


def test_auto_primary_aihot() -> None:
    client = FakeOk()
    cache = RecordingCache()
    facade = _facade(client=client, cache=cache)

    payload = facade.items(preference="auto", mode="selected", take=10)

    assert payload["provider"] == "aihot"
    assert payload["preference"] == "auto"
    assert payload["served_from"] == "primary"
    assert payload["items"][0]["id"] == "aihot-1"
    assert payload["research_safety"]["research_only"] is True
    assert "safety" not in payload
    assert len(cache.cached_items) == 1
    assert client.calls[0][0] == "items"


def test_auto_failover_horizon() -> None:
    run = _fresh_run()
    facade = _facade(
        client=FakeTimeout(),
        horizon=HorizonState(
            fresh_run=run,
            items=_items_page(_item("hz-1", title="Horizon item")),
        ),
    )

    payload = facade.items(preference="auto", mode="selected", take=10)

    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "failover"
    assert payload["preference"] == "auto"
    assert payload["items"][0]["id"] == "hz-1"
    warnings = payload["warnings"]
    assert any("failover" in w for w in warnings)
    assert any("AI HOT request timed out" in w for w in warnings)
    assert any(f"horizon_run_id={run['run_id']}" in w for w in warnings)
    assert any("horizon_generated_at=" in w for w in warnings)


def test_auto_cache_when_horizon_missing() -> None:
    cached = _items_page(
        _item("cached-1", title="Cached AI HOT"),
        warnings=["Using cached AI HOT items from the local database."],
    )
    facade = _facade(
        client=FakeTimeout(),
        horizon=HorizonState(),
        cache=RecordingCache(items=cached),
    )

    payload = facade.items(preference="auto", mode="selected", take=10)

    assert payload["provider"] == "aihot"
    assert payload["served_from"] == "cache"
    assert payload["items"][0]["id"] == "cached-1"
    assert any("AI HOT request timed out" in w for w in payload["warnings"])
    assert any("aihot_cache_fallback" in w for w in payload["warnings"])


def test_auto_unavailable() -> None:
    facade = _facade(client=FakeTimeout(), horizon=HorizonState(), cache=RecordingCache())

    with pytest.raises(NewsFacadeError) as ei:
        facade.items(preference="auto", mode="selected", take=10)

    assert ei.value.code == "news_unavailable"
    assert ei.value.status_code == 503
    assert "aihot=" in ei.value.message
    assert "horizon=" in ei.value.message


def test_auto_skips_aihot_when_disabled_and_failsover() -> None:
    run = _fresh_run()
    client = FakeOk()
    facade = _facade(
        client=client,
        settings=_settings(aihot_enabled=False),
        horizon=HorizonState(
            fresh_run=run,
            items=_items_page(_item("hz-disabled")),
        ),
    )

    payload = facade.items(preference="auto", mode="selected", take=10)

    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "failover"
    assert client.calls == []


def test_forced_aihot_disabled() -> None:
    facade = _facade(client=FakeOk(), settings=_settings(aihot_enabled=False))

    with pytest.raises(NewsFacadeError) as ei:
        facade.items(preference="aihot", mode="selected", take=10)

    assert ei.value.code == "aihot_disabled"
    assert ei.value.status_code == 503


def test_forced_horizon_fresh() -> None:
    run = _fresh_run()
    facade = _facade(
        client=FakeTimeout(),
        horizon=HorizonState(
            fresh_run=run,
            items=_items_page(_item("hz-forced")),
        ),
    )

    payload = facade.items(preference="horizon", mode="selected", take=5)

    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "forced"
    assert payload["preference"] == "horizon"
    assert payload["items"][0]["id"] == "hz-forced"


def test_forced_horizon_stale() -> None:
    facade = _facade(
        client=FakeOk(),
        horizon=HorizonState(
            fresh_run=None,
            items=None,
            any_items=_items_page(_item("hz-old")),
        ),
    )

    with pytest.raises(NewsFacadeError) as ei:
        facade.items(preference="horizon", mode="selected", take=10)

    assert ei.value.code == "horizon_stale"
    assert ei.value.status_code == 503


def test_forced_horizon_unavailable() -> None:
    facade = _facade(client=FakeOk(), horizon=HorizonState())

    with pytest.raises(NewsFacadeError) as ei:
        facade.items(preference="horizon", mode="selected", take=10)

    assert ei.value.code == "horizon_unavailable"


def test_failover_disabled_uses_aihot_cache_only() -> None:
    cached = _items_page(_item("cache-only"))
    facade = _facade(
        client=FakeTimeout(),
        settings=_settings(failover_enabled=False),
        horizon=HorizonState(
            fresh_run=_fresh_run(),
            items=_items_page(_item("hz-ignored")),
        ),
        cache=RecordingCache(items=cached),
    )

    payload = facade.items(preference="auto", mode="selected", take=10)

    assert payload["provider"] == "aihot"
    assert payload["served_from"] == "cache"
    assert payload["items"][0]["id"] == "cache-only"


def test_auto_daily_failover_horizon() -> None:
    today = datetime.now(UTC).date().isoformat()
    run = _fresh_run()
    facade = _facade(
        client=FakeTimeout(),
        horizon=HorizonState(fresh_run=run, daily=_daily(today)),
    )

    payload = facade.daily(preference="auto", date=None)

    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "failover"
    assert payload["date"] == today
    assert any("served_from=horizon_failover" in w for w in payload["warnings"])


def test_auto_daily_rejects_stale_horizon_date() -> None:
    old = (datetime.now(UTC).date() - timedelta(days=5)).isoformat()
    # Cache key for undated auto daily is Asia/Shanghai "today" (current_brief_date).
    from quant_system.news.facade import current_brief_date

    brief_today = current_brief_date()
    cached = _daily(brief_today, warnings=["cached daily"])
    facade = _facade(
        client=FakeTimeout(),
        horizon=HorizonState(fresh_run=_fresh_run(), daily=_daily(old)),
        cache=RecordingCache(daily=cached),
    )

    payload = facade.daily(preference="auto", date=None)

    assert payload["provider"] == "aihot"
    assert payload["served_from"] == "cache"
    assert payload["date"] == brief_today


def test_auto_dailies_failover_horizon() -> None:
    facade = _facade(
        client=FakeTimeout(),
        horizon=HorizonState(
            fresh_run=_fresh_run(),
            dailies=_dailies("2026-07-23", "2026-07-22"),
        ),
    )

    payload = facade.dailies(preference="auto", take=5)

    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "failover"
    assert payload["count"] == 2


def test_forced_horizon_daily_archive_when_run_stale() -> None:
    facade = _facade(
        client=FakeOk(),
        horizon=HorizonState(
            fresh_run=None,
            any_daily=_daily("2026-07-01"),
        ),
    )

    payload = facade.daily(preference="horizon", date="2026-07-01")

    assert payload["provider"] == "horizon"
    assert payload["served_from"] == "forced"
    assert payload["preference"] == "horizon"
    assert payload["date"] == "2026-07-01"
    assert any("archive" in w for w in payload["warnings"])


def test_forced_horizon_daily_current_stale_when_run_stale() -> None:
    facade = _facade(
        client=FakeOk(),
        horizon=HorizonState(
            fresh_run=None,
            any_daily=_daily("2026-07-23"),
        ),
    )

    with pytest.raises(NewsFacadeError) as ei:
        facade.daily(preference="horizon", date=None)

    assert ei.value.code == "horizon_stale"
    assert ei.value.status_code == 503


def test_auto_dailies_skips_stale_horizon() -> None:
    facade = _facade(
        client=FakeTimeout(),
        horizon=HorizonState(
            fresh_run=None,
            dailies=_dailies("2026-07-23", "2026-07-22"),
        ),
        cache=RecordingCache(),
    )

    with pytest.raises(NewsFacadeError) as ei:
        facade.dailies(preference="auto", take=5)

    assert ei.value.code == "news_unavailable"
    assert ei.value.status_code == 503


def test_status_is_local_only_and_does_not_use_client() -> None:
    client = FakeOk()
    run = _fresh_run()
    facade = _facade(
        client=client,
        horizon=HorizonState(fresh_run=run),
        last_error={"code": "aihot_timeout", "message": "AI HOT request timed out", "at": "t0"},
    )

    payload = facade.status()

    assert client.calls == []
    assert payload["preference_default"] == "auto"
    assert payload["research_only"] is True
    assert payload["providers"]["aihot"]["enabled"] is True
    assert payload["providers"]["aihot"]["last_error"]["code"] == "aihot_timeout"
    assert payload["providers"]["horizon"]["fresh"] is True
    assert payload["providers"]["horizon"]["last_run"]["run_id"] == run["run_id"]
    assert payload["failover"]["auto_enabled"] is True
    assert payload["failover"]["order"] == ["aihot_live", "horizon_pg", "aihot_cache"]
    assert payload["research_safety"]["does_not_trigger_trading"] is True
    assert "api_key" not in str(payload).lower()
    assert "openai" not in str(payload).lower() or "provider" in str(payload).lower()


def test_default_preference_from_settings_when_none() -> None:
    facade = _facade(
        client=FakeOk(),
        settings=_settings(preference="aihot"),
    )
    payload = facade.items(preference=None, mode="selected", take=3)
    assert payload["preference"] == "aihot"
    assert payload["served_from"] == "forced"
