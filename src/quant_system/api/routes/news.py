from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.news import (
    AiHotDailiesResponse,
    AiHotDailyResponse,
    AiHotItemsResponse,
    NewsStatusResponse,
)
from quant_system.config.settings import Settings
from quant_system.news import horizon_repository
from quant_system.news.aihot_client import AiHotClient, AiHotProviderError
from quant_system.news.daily_report_repository import (
    cache_aihot_daily_report,
    load_cached_aihot_daily_report,
)
from quant_system.news.facade import NewsFacade, NewsFacadeError, current_brief_date
from quant_system.news.models import AiHotDaily, AiHotItemsPage
from quant_system.news.repository import (
    AiHotItemsCacheQuery,
    cache_aihot_items,
    load_cached_aihot_items,
)

router = APIRouter()

AiHotCategory = Literal["ai-models", "ai-products", "industry", "paper", "tip"]
NewsPreference = Literal["auto", "aihot", "horizon"]
_last_error: dict[str, Any] | None = None
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


def _remember_error(exc: AiHotProviderError) -> None:
    global _last_error
    _last_error = {
        "code": exc.code,
        "message": exc.message,
        "at": datetime.now(UTC).isoformat(),
    }


def _last_error_snapshot() -> dict[str, Any] | None:
    return dict(_last_error) if _last_error else None


def _cache_items_page(
    page: AiHotItemsPage,
    *,
    settings: Settings,
    mode: str = "selected",
    category: str | None = None,
    q: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    take: int = 50,
    query: AiHotItemsCacheQuery | None = None,
) -> None:
    cache_query = query or AiHotItemsCacheQuery(
        mode=mode,  # type: ignore[arg-type]
        category=category,
        q=q,
        since=since,
        cursor=cursor,
        take=take,
    )
    cache_aihot_items(page, settings=settings, query=cache_query)


def _load_cached_items_page(
    *,
    settings: Settings,
    mode: str = "selected",
    category: str | None = None,
    q: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    take: int = 50,
    query: AiHotItemsCacheQuery | None = None,
) -> AiHotItemsPage | None:
    cache_query = query or AiHotItemsCacheQuery(
        mode=mode,  # type: ignore[arg-type]
        category=category,
        q=q,
        since=since,
        cursor=cursor,
        take=take,
    )
    return load_cached_aihot_items(settings=settings, query=cache_query)


def _cache_daily_report(daily: AiHotDaily, *, settings: Settings) -> None:
    cache_aihot_daily_report(daily, settings=settings)


def _load_cached_daily_report(date: str, *, settings: Settings) -> AiHotDaily | None:
    return load_cached_aihot_daily_report(date, settings=settings)


class _LazyAiHotClient:
    """Resolve the real client only on first live method call.

    Status and horizon-only paths must not construct/probe AI HOT.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: AiHotClient | None = None

    def _resolve(self) -> AiHotClient:
        if self._client is None:
            self._client = _client_for_settings(self._settings)
        return self._client

    def items(self, **kwargs: Any) -> AiHotItemsPage:
        return self._resolve().items(**kwargs)

    def daily(self, **kwargs: Any) -> AiHotDaily:
        return self._resolve().daily(**kwargs)

    def dailies(self, **kwargs: Any) -> Any:
        return self._resolve().dailies(**kwargs)


def _facade_for_settings(settings: Settings) -> NewsFacade:
    # Lazy client: status / horizon-only never touch AI HOT construction.
    client = _LazyAiHotClient(settings) if settings.aihot.enabled else None
    # "any" hooks intentionally reuse the same PG loaders as the fresh path:
    # content loaders do not gate on run max_age. Freshness is decided only by
    # the facade via load_latest_horizon_run (+ date recency for undated daily).
    return NewsFacade(
        settings=settings,
        aihot_client=client,
        load_latest_horizon_run=horizon_repository.load_latest_horizon_run,
        load_horizon_items_page=horizon_repository.load_horizon_items_page,
        load_horizon_daily=horizon_repository.load_horizon_daily,
        load_horizon_dailies=horizon_repository.load_horizon_dailies,
        load_any_horizon_items=horizon_repository.load_horizon_items_page,
        load_any_horizon_daily=horizon_repository.load_horizon_daily,
        cache_aihot_items=_cache_items_page,
        load_cached_aihot_items=_load_cached_items_page,
        cache_aihot_daily=_cache_daily_report,
        load_cached_aihot_daily=_load_cached_daily_report,
        remember_error=_remember_error,
        last_error_getter=_last_error_snapshot,
    )


def _http_from_facade(exc: NewsFacadeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _items_handler(
    settings: Settings,
    *,
    preference: NewsPreference | None,
    mode: Literal["selected", "all"],
    category: AiHotCategory | None,
    q: str | None,
    since: str | None,
    cursor: str | None,
    take: int,
) -> dict:
    try:
        return _facade_for_settings(settings).items(
            preference=preference,
            mode=mode,
            category=category,
            q=q,
            since=since,
            cursor=cursor,
            take=take,
        )
    except NewsFacadeError as exc:
        raise _http_from_facade(exc) from exc


def _daily_handler(
    settings: Settings,
    *,
    preference: NewsPreference | None,
    date: str | None,
) -> dict:
    try:
        return _facade_for_settings(settings).daily(
            preference=preference,
            date=date,
        )
    except NewsFacadeError as exc:
        raise _http_from_facade(exc) from exc


def _dailies_handler(
    settings: Settings,
    *,
    preference: NewsPreference | None,
    take: int,
) -> dict:
    try:
        return _facade_for_settings(settings).dailies(
            preference=preference,
            take=take,
        )
    except NewsFacadeError as exc:
        raise _http_from_facade(exc) from exc


def _status_handler(settings: Settings) -> dict:
    return _facade_for_settings(settings).status()


# ---------------------------------------------------------------------------
# Neutral routes (preferred)
# ---------------------------------------------------------------------------


@router.get("/news/items", response_model=AiHotItemsResponse)
def news_items(
    settings: SettingsDep,
    preference: NewsPreference | None = None,
    mode: Literal["selected", "all"] = "selected",
    category: AiHotCategory | None = None,
    q: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    take: int = Query(default=50, ge=1, le=100),
) -> dict:
    return _items_handler(
        settings,
        preference=preference,
        mode=mode,
        category=category,
        q=q,
        since=since,
        cursor=cursor,
        take=take,
    )


@router.get("/news/daily", response_model=AiHotDailyResponse)
def news_daily(
    settings: SettingsDep,
    preference: NewsPreference | None = None,
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    return _daily_handler(settings, preference=preference, date=date)


@router.get("/news/dailies", response_model=AiHotDailiesResponse)
def news_dailies(
    settings: SettingsDep,
    preference: NewsPreference | None = None,
    take: int = Query(default=14, ge=1, le=180),
) -> dict:
    return _dailies_handler(settings, preference=preference, take=take)


@router.get("/news/status", response_model=NewsStatusResponse)
def news_status(settings: SettingsDep) -> dict:
    return _status_handler(settings)


# ---------------------------------------------------------------------------
# Compatibility aliases — path name is historical; default preference is auto
# ---------------------------------------------------------------------------


@router.get("/news/aihot/items", response_model=AiHotItemsResponse)
def aihot_items(
    settings: SettingsDep,
    preference: NewsPreference | None = None,
    mode: Literal["selected", "all"] = "selected",
    category: AiHotCategory | None = None,
    q: str | None = None,
    since: str | None = None,
    cursor: str | None = None,
    take: int = Query(default=50, ge=1, le=100),
) -> dict:
    return _items_handler(
        settings,
        preference=preference,
        mode=mode,
        category=category,
        q=q,
        since=since,
        cursor=cursor,
        take=take,
    )


@router.get("/news/aihot/daily", response_model=AiHotDailyResponse)
def aihot_daily(
    settings: SettingsDep,
    preference: NewsPreference | None = None,
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    return _daily_handler(settings, preference=preference, date=date)


@router.get("/news/aihot/dailies", response_model=AiHotDailiesResponse)
def aihot_dailies(
    settings: SettingsDep,
    preference: NewsPreference | None = None,
    take: int = Query(default=14, ge=1, le=180),
) -> dict:
    return _dailies_handler(settings, preference=preference, take=take)


@router.get("/news/aihot/status", response_model=NewsStatusResponse)
def aihot_status(settings: SettingsDep) -> dict:
    return _status_handler(settings)


# Keep helpers available for existing unit tests.
def _current_brief_date(now: datetime | None = None) -> str:
    return current_brief_date(now)
