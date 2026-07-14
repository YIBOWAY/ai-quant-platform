from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.news import (
    AiHotDailiesResponse,
    AiHotDailyResponse,
    AiHotItemsResponse,
    AiHotStatusResponse,
)
from quant_system.config.settings import Settings
from quant_system.news.aihot_client import AiHotClient, AiHotProviderError
from quant_system.news.daily_report_repository import (
    cache_aihot_daily_report,
    load_cached_aihot_daily_report,
)
from quant_system.news.models import AiHotDailiesPage, AiHotDaily, AiHotItemsPage
from quant_system.news.repository import (
    AiHotItemsCacheQuery,
    cache_aihot_items,
    load_cached_aihot_items,
)

router = APIRouter()

AiHotCategory = Literal["ai-models", "ai-products", "industry", "paper", "tip"]
_PROVIDER = "aihot"
_PROVIDER_BETA_WARNING = (
    "AI HOT is an external beta source; summaries may be generated and should be "
    "verified against original sources."
)
_last_error: dict[str, str] | None = None
_CLIENTS: dict[tuple[str, int, int, str], AiHotClient] = {}
_CLIENTS_LOCK = threading.RLock()


def _client_for_settings(settings: Settings) -> AiHotClient:
    config = settings.aihot
    key = (
        config.base_url.rstrip("/"),
        config.timeout_seconds,
        config.cache_ttl_seconds,
        config.user_agent,
    )
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(key)
        if client is None:
            client = AiHotClient(
                base_url=config.base_url,
                timeout_seconds=config.timeout_seconds,
                cache_ttl_seconds=config.cache_ttl_seconds,
                user_agent=config.user_agent,
            )
            _CLIENTS[key] = client
        return client


def close_aihot_clients() -> None:
    with _CLIENTS_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        client.close()


@router.get("/news/aihot/items", response_model=AiHotItemsResponse)
def aihot_items(
    settings: SettingsDep,
    mode: Literal["selected", "all"] = "selected",
    category: AiHotCategory | None = None,
    q: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    take: int = Query(default=50, ge=1, le=100),
) -> dict:
    _ensure_enabled(settings)
    cache_query = AiHotItemsCacheQuery(
        mode=mode,
        category=category,
        q=q,
        since=since,
        cursor=cursor,
        take=take,
    )
    try:
        page = _client_for_settings(settings).items(
            mode=mode,
            category=category,
            q=q,
            since=since,
            cursor=cursor,
            take=take,
        )
    except AiHotProviderError as exc:
        _remember_error(exc)
        cached_page = _load_cached_items_page(settings=settings, query=cache_query)
        if cached_page is not None:
            warnings = [*cached_page.warnings, exc.message]
            return _items_payload(replace(cached_page, warnings=warnings))
        raise _http_error(exc) from exc
    _cache_items_page(page, settings=settings, query=cache_query)
    return _items_payload(page)


@router.get("/news/aihot/daily", response_model=AiHotDailyResponse)
def aihot_daily(
    settings: SettingsDep,
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    _ensure_enabled(settings)
    try:
        daily = _client_for_settings(settings).daily(date=date)
    except AiHotProviderError as exc:
        _remember_error(exc)
        cached_daily = _load_cached_daily_report(
            date=date or _current_brief_date(),
            settings=settings,
        )
        if cached_daily is not None:
            warnings = [*cached_daily.warnings, exc.message]
            return _daily_payload(replace(cached_daily, warnings=warnings))
        raise _http_error(exc) from exc
    _cache_daily_report(daily, settings=settings)
    return _daily_payload(daily)


@router.get("/news/aihot/dailies", response_model=AiHotDailiesResponse)
def aihot_dailies(
    settings: SettingsDep,
    take: int = Query(default=14, ge=1, le=180),
) -> dict:
    _ensure_enabled(settings)
    try:
        page = _client_for_settings(settings).dailies(take=take)
    except AiHotProviderError as exc:
        _remember_error(exc)
        raise _http_error(exc) from exc
    return _dailies_payload(page)


@router.get("/news/aihot/status", response_model=AiHotStatusResponse)
def aihot_status(settings: SettingsDep) -> dict:
    config = settings.aihot
    return {
        "provider": _PROVIDER,
        "provider_beta": True,
        "enabled": config.enabled,
        "base_url": config.base_url.rstrip("/"),
        "timeout_seconds": config.timeout_seconds,
        "cache_ttl_seconds": config.cache_ttl_seconds,
        "last_error": _last_error,
        "warnings": [_PROVIDER_BETA_WARNING],
        "research_safety": _research_safety(),
    }


def _ensure_enabled(settings: Settings) -> None:
    if settings.aihot.enabled:
        return
    raise HTTPException(
        status_code=503,
        detail={
            "code": "aihot_disabled",
            "message": "AI HOT news integration is disabled by QS_AIHOT_ENABLED.",
        },
    )


def _http_error(exc: AiHotProviderError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
        },
    )


def _remember_error(exc: AiHotProviderError) -> None:
    global _last_error
    _last_error = {
        "code": exc.code,
        "message": exc.message,
    }


def _cache_items_page(
    page: AiHotItemsPage,
    *,
    settings: Settings,
    query: AiHotItemsCacheQuery,
) -> None:
    cache_aihot_items(page, settings=settings, query=query)


def _load_cached_items_page(
    *,
    settings: Settings,
    query: AiHotItemsCacheQuery,
) -> AiHotItemsPage | None:
    return load_cached_aihot_items(settings=settings, query=query)


def _cache_daily_report(
    daily: AiHotDaily,
    *,
    settings: Settings,
) -> None:
    cache_aihot_daily_report(daily, settings=settings)


def _load_cached_daily_report(
    date: str,
    *,
    settings: Settings,
) -> AiHotDaily | None:
    return load_cached_aihot_daily_report(date, settings=settings)


def _current_brief_date(now: datetime | None = None) -> str:
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _items_payload(page: AiHotItemsPage) -> dict:
    return {
        "provider": _PROVIDER,
        "provider_beta": True,
        "fetched_at": page.fetched_at,
        "count": page.count,
        "has_next": page.has_next,
        "next_cursor": page.next_cursor,
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "title_en": item.title_en,
                "url": item.url,
                "source": item.source,
                "published_at": item.published_at,
                "summary": item.summary,
                "category": item.category,
                "score": item.score,
                "selected": item.selected,
                "raw": item.raw,
            }
            for item in page.items
        ],
        "warnings": [*page.warnings, _PROVIDER_BETA_WARNING],
        "research_safety": _research_safety(),
    }


def _daily_payload(daily: AiHotDaily) -> dict:
    return {
        "provider": _PROVIDER,
        "provider_beta": True,
        "fetched_at": daily.fetched_at,
        "date": daily.date,
        "generated_at": daily.generated_at,
        "window_start": daily.window_start,
        "window_end": daily.window_end,
        "lead": daily.lead,
        "sections": daily.sections,
        "flashes": daily.flashes,
        "warnings": [*daily.warnings, _PROVIDER_BETA_WARNING],
        "research_safety": _research_safety(),
        "raw": daily.raw,
    }


def _dailies_payload(page: AiHotDailiesPage) -> dict:
    return {
        "provider": _PROVIDER,
        "provider_beta": True,
        "fetched_at": page.fetched_at,
        "count": page.count,
        "items": [
            {
                "date": item.date,
                "generated_at": item.generated_at,
                "lead_title": item.lead_title,
                "raw": item.raw,
            }
            for item in page.items
        ],
        "warnings": [*page.warnings, _PROVIDER_BETA_WARNING],
        "research_safety": _research_safety(),
    }


def _research_safety() -> dict[str, bool]:
    return {
        "research_only": True,
        "not_investment_advice": True,
        "does_not_trigger_trading": True,
        "verify_original_source": True,
    }
