"""NewsFacade: preference selection and auto failover for AI news reads.

Phase A order for preference=auto:
  1. AI HOT live
  2. Horizon PG fresh (provider_runs ingested + max_age + item_count>0)
  3. AI HOT PG cache
  4. news_unavailable

Request path never runs Horizon pipeline / ingest / LLM.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from quant_system.config.settings import Settings
from quant_system.news.aihot_client import AiHotProviderError
from quant_system.news.models import (
    AiHotDailiesPage,
    AiHotDaily,
    AiHotItemsPage,
    utc_now_iso,
)

Preference = Literal["auto", "aihot", "horizon"]
ServedFrom = Literal["primary", "failover", "cache", "forced"]

_AIHOT_BETA_WARNING = (
    "AI HOT is an external beta source; summaries may be generated and should be "
    "verified against original sources."
)
_HORIZON_BETA_WARNING = (
    "Horizon is a local research feed; summaries may be generated and should be "
    "verified against original sources."
)
_FAILOVER_ORDER = ["aihot_live", "horizon_pg", "aihot_cache"]


class NewsFacadeError(RuntimeError):
    """Structured news selection failure mapped to HTTP by the route layer."""

    def __init__(self, code: str, message: str, status_code: int = 503) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


class NewsFacade:
    """Selects AI HOT / Horizon sources and stamps response metadata."""

    def __init__(
        self,
        *,
        settings: Settings,
        aihot_client: Any | None = None,
        load_latest_horizon_run: Callable[..., dict[str, Any] | None] | None = None,
        load_horizon_items_page: Callable[..., AiHotItemsPage | None] | None = None,
        load_horizon_daily: Callable[..., AiHotDaily | None] | None = None,
        load_horizon_dailies: Callable[..., AiHotDailiesPage | None] | None = None,
        load_any_horizon_items: Callable[..., AiHotItemsPage | None] | None = None,
        load_any_horizon_daily: Callable[..., AiHotDaily | None] | None = None,
        cache_aihot_items: Callable[..., None] | None = None,
        load_cached_aihot_items: Callable[..., AiHotItemsPage | None] | None = None,
        cache_aihot_daily: Callable[..., None] | None = None,
        load_cached_aihot_daily: Callable[..., AiHotDaily | None] | None = None,
        remember_error: Callable[[AiHotProviderError], None] | None = None,
        last_error_getter: Callable[[], dict[str, Any] | None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self._aihot_client = aihot_client
        self._load_latest_horizon_run = load_latest_horizon_run
        self._load_horizon_items_page = load_horizon_items_page
        self._load_horizon_daily = load_horizon_daily
        self._load_horizon_dailies = load_horizon_dailies
        self._load_any_horizon_items = load_any_horizon_items or load_horizon_items_page
        self._load_any_horizon_daily = load_any_horizon_daily or load_horizon_daily
        self._cache_aihot_items = cache_aihot_items
        self._load_cached_aihot_items = load_cached_aihot_items
        self._cache_aihot_daily = cache_aihot_daily
        self._load_cached_aihot_daily = load_cached_aihot_daily
        self._remember_error = remember_error
        self._last_error_getter = last_error_getter
        self._now = now or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------------ public

    def items(
        self,
        *,
        preference: Preference | None,
        mode: str = "selected",
        category: str | None = None,
        q: str | None = None,
        since: str | None = None,
        cursor: str | None = None,
        take: int = 50,
    ) -> dict[str, Any]:
        pref = self._resolve_preference(preference)
        kwargs = {
            "mode": mode,
            "category": category,
            "q": q,
            "since": since,
            "cursor": cursor,
            "take": take,
        }
        if pref == "aihot":
            return self._aihot_items(forced=True, preference=pref, **kwargs)
        if pref == "horizon":
            return self._horizon_items(forced=True, preference=pref, **kwargs)
        return self._auto_items(**kwargs)

    def daily(
        self,
        *,
        preference: Preference | None,
        date: str | None = None,
    ) -> dict[str, Any]:
        pref = self._resolve_preference(preference)
        if pref == "aihot":
            return self._aihot_daily(forced=True, preference=pref, date=date)
        if pref == "horizon":
            return self._horizon_daily(forced=True, preference=pref, date=date)
        return self._auto_daily(date=date)

    def dailies(
        self,
        *,
        preference: Preference | None,
        take: int = 14,
    ) -> dict[str, Any]:
        pref = self._resolve_preference(preference)
        if pref == "aihot":
            return self._aihot_dailies(forced=True, preference=pref, take=take)
        if pref == "horizon":
            return self._horizon_dailies(forced=True, preference=pref, take=take)
        return self._auto_dailies(take=take)

    def status(self) -> dict[str, Any]:
        """Local-only status. Must not call AI HOT client or run Horizon."""

        settings = self.settings
        run = self._safe_latest_run()
        fresh = run is not None
        last_error = self._last_error_getter() if self._last_error_getter else None
        warnings: list[str] = []
        if settings.horizon.enabled and not fresh:
            warnings.append("horizon_stale_or_empty")
        if not settings.aihot.enabled:
            warnings.append("aihot_disabled")
        if not settings.news.failover_enabled:
            warnings.append("failover_disabled")

        return {
            "preference_default": settings.news.source_preference,
            "research_only": True,
            "providers": {
                "aihot": {
                    "enabled": settings.aihot.enabled,
                    "base_url": settings.aihot.base_url.rstrip("/"),
                    "timeout_seconds": settings.aihot.timeout_seconds,
                    "cache_ttl_seconds": settings.aihot.cache_ttl_seconds,
                    "provider_beta": True,
                    "last_error": last_error,
                },
                "horizon": {
                    "enabled": settings.horizon.enabled,
                    "inbox_dir": settings.horizon.inbox_dir,
                    "max_age_seconds": settings.horizon.max_age_seconds,
                    "provider_beta": bool(settings.horizon.provider_beta),
                    "last_run": _status_run(run),
                    "fresh": fresh,
                },
            },
            "failover": {
                "auto_enabled": bool(
                    settings.news.failover_enabled and settings.horizon.enabled
                ),
                "order": list(_FAILOVER_ORDER),
            },
            "warnings": warnings,
            "research_safety": _research_safety(),
            # Backward-compatible aihot status fields (superset).
            "provider": "aihot",
            "provider_beta": True,
            "enabled": settings.aihot.enabled,
            "base_url": settings.aihot.base_url.rstrip("/"),
            "timeout_seconds": settings.aihot.timeout_seconds,
            "cache_ttl_seconds": settings.aihot.cache_ttl_seconds,
            "last_error": last_error,
        }

    # --------------------------------------------------------------- auto path

    def _auto_items(self, **kwargs: Any) -> dict[str, Any]:
        if not self._failover_active():
            return self._aihot_items(forced=False, preference="auto", **kwargs)

        aihot_exc: AiHotProviderError | None = None
        if self.settings.aihot.enabled:
            try:
                page = self._aihot_live_items(**kwargs)
            except AiHotProviderError as exc:
                aihot_exc = exc
                self._note_error(exc)
            else:
                self._try_cache_items(page, **kwargs)
                return self._stamp_items(
                    page,
                    provider="aihot",
                    preference="auto",
                    served_from="primary",
                )
        else:
            aihot_exc = AiHotProviderError(
                code="aihot_disabled",
                message="AI HOT news integration is disabled by QS_AIHOT_ENABLED.",
                status_code=503,
            )
            self._note_error(aihot_exc)

        horizon = self._horizon_fresh_items(**kwargs)
        if horizon is not None:
            page, run = horizon
            return self._stamp_items(
                page,
                provider="horizon",
                preference="auto",
                served_from="failover",
                extra_warnings=_failover_warnings(aihot_exc, run),
            )

        cached = self._load_aihot_cache(**kwargs)
        if cached is not None:
            return self._stamp_items(
                cached,
                provider="aihot",
                preference="auto",
                served_from="cache",
                extra_warnings=_cache_fallback_warnings(aihot_exc),
            )

        raise NewsFacadeError(
            "news_unavailable",
            _unavailable_message(aihot_exc, horizon_note="unavailable"),
            503,
        )

    def _auto_daily(self, *, date: str | None) -> dict[str, Any]:
        if not self._failover_active():
            return self._aihot_daily(forced=False, preference="auto", date=date)

        aihot_exc: AiHotProviderError | None = None
        if self.settings.aihot.enabled:
            try:
                daily = self._aihot_live_daily(date=date)
            except AiHotProviderError as exc:
                aihot_exc = exc
                self._note_error(exc)
            else:
                self._try_cache_daily(daily)
                return self._stamp_daily(
                    daily,
                    provider="aihot",
                    preference="auto",
                    served_from="primary",
                )
        else:
            aihot_exc = AiHotProviderError(
                code="aihot_disabled",
                message="AI HOT news integration is disabled by QS_AIHOT_ENABLED.",
                status_code=503,
            )
            self._note_error(aihot_exc)

        horizon = self._horizon_fresh_daily(date=date)
        if horizon is not None:
            daily, run = horizon
            return self._stamp_daily(
                daily,
                provider="horizon",
                preference="auto",
                served_from="failover",
                extra_warnings=_failover_warnings(aihot_exc, run),
            )

        cached = self._load_aihot_daily_cache(date=date)
        if cached is not None:
            return self._stamp_daily(
                cached,
                provider="aihot",
                preference="auto",
                served_from="cache",
                extra_warnings=_cache_fallback_warnings(aihot_exc),
            )

        raise NewsFacadeError(
            "news_unavailable",
            _unavailable_message(aihot_exc, horizon_note="unavailable"),
            503,
        )

    def _auto_dailies(self, *, take: int) -> dict[str, Any]:
        if not self._failover_active():
            return self._aihot_dailies(forced=False, preference="auto", take=take)

        aihot_exc: AiHotProviderError | None = None
        if self.settings.aihot.enabled:
            try:
                page = self._aihot_live_dailies(take=take)
            except AiHotProviderError as exc:
                aihot_exc = exc
                self._note_error(exc)
            else:
                return self._stamp_dailies(
                    page,
                    provider="aihot",
                    preference="auto",
                    served_from="primary",
                )
        else:
            aihot_exc = AiHotProviderError(
                code="aihot_disabled",
                message="AI HOT news integration is disabled by QS_AIHOT_ENABLED.",
                status_code=503,
            )
            self._note_error(aihot_exc)

        # Auto failover only when the latest Horizon run is still fresh
        # (same gate as items/daily). Forced horizon dailies stay ungated.
        run = self._safe_latest_run()
        if run is not None:
            page = self._call_optional(
                self._load_horizon_dailies,
                settings=self.settings,
                take=take,
            )
            if page is not None and page.items:
                return self._stamp_dailies(
                    page,
                    provider="horizon",
                    preference="auto",
                    served_from="failover",
                    extra_warnings=_failover_warnings(aihot_exc, run),
                )

        raise NewsFacadeError(
            "news_unavailable",
            _unavailable_message(aihot_exc, horizon_note="unavailable"),
            503,
        )

    # ------------------------------------------------------------- forced aihot

    def _aihot_items(self, *, forced: bool, preference: Preference, **kwargs: Any) -> dict[str, Any]:
        self._require_aihot_enabled()
        try:
            page = self._aihot_live_items(**kwargs)
        except AiHotProviderError as exc:
            self._note_error(exc)
            cached = self._load_aihot_cache(**kwargs)
            if cached is not None:
                return self._stamp_items(
                    cached,
                    provider="aihot",
                    preference=preference,
                    served_from="cache",
                    extra_warnings=[exc.message, "aihot_cache_fallback"],
                )
            raise NewsFacadeError(exc.code, exc.message, exc.status_code) from exc
        self._try_cache_items(page, **kwargs)
        return self._stamp_items(
            page,
            provider="aihot",
            preference=preference,
            served_from="forced" if forced else "primary",
        )

    def _aihot_daily(
        self,
        *,
        forced: bool,
        preference: Preference,
        date: str | None,
    ) -> dict[str, Any]:
        self._require_aihot_enabled()
        try:
            daily = self._aihot_live_daily(date=date)
        except AiHotProviderError as exc:
            self._note_error(exc)
            cached = self._load_aihot_daily_cache(date=date)
            if cached is not None:
                return self._stamp_daily(
                    cached,
                    provider="aihot",
                    preference=preference,
                    served_from="cache",
                    extra_warnings=[exc.message, "aihot_cache_fallback"],
                )
            raise NewsFacadeError(exc.code, exc.message, exc.status_code) from exc
        self._try_cache_daily(daily)
        return self._stamp_daily(
            daily,
            provider="aihot",
            preference=preference,
            served_from="forced" if forced else "primary",
        )

    def _aihot_dailies(
        self,
        *,
        forced: bool,
        preference: Preference,
        take: int,
    ) -> dict[str, Any]:
        self._require_aihot_enabled()
        try:
            page = self._aihot_live_dailies(take=take)
        except AiHotProviderError as exc:
            self._note_error(exc)
            raise NewsFacadeError(exc.code, exc.message, exc.status_code) from exc
        return self._stamp_dailies(
            page,
            provider="aihot",
            preference=preference,
            served_from="forced" if forced else "primary",
        )

    # ----------------------------------------------------------- forced horizon

    def _horizon_items(
        self,
        *,
        forced: bool,
        preference: Preference,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._require_horizon_enabled()
        result = self._horizon_fresh_items(**kwargs)
        if result is not None:
            page, run = result
            return self._stamp_items(
                page,
                provider="horizon",
                preference=preference,
                served_from="forced" if forced else "failover",
                extra_warnings=_horizon_run_warnings(run),
            )
        any_items = self._call_optional(
            self._load_any_horizon_items,
            settings=self.settings,
            take=kwargs.get("take", 50),
            category=kwargs.get("category"),
            q=kwargs.get("q"),
            since=kwargs.get("since"),
        )
        if any_items is not None and any_items.items:
            raise NewsFacadeError(
                "horizon_stale",
                "Horizon news is present but outside max_age / freshness window.",
                503,
            )
        raise NewsFacadeError(
            "horizon_unavailable",
            "No Horizon news is available in PostgreSQL.",
            503,
        )

    def _horizon_daily(
        self,
        *,
        forced: bool,
        preference: Preference,
        date: str | None,
    ) -> dict[str, Any]:
        self._require_horizon_enabled()
        result = self._horizon_fresh_daily(date=date)
        if result is not None:
            daily, run = result
            return self._stamp_daily(
                daily,
                provider="horizon",
                preference=preference,
                served_from="forced" if forced else "failover",
                extra_warnings=_horizon_run_warnings(run),
            )
        any_daily = self._call_optional(
            self._load_any_horizon_daily,
            settings=self.settings,
            date=date,
        )
        # Forced + explicit date: serve archive even when the latest run is stale
        # (design §5.5). Undated / current daily stays gated on freshness.
        if any_daily is not None and date is not None and forced:
            if any_daily.date != date:
                raise NewsFacadeError(
                    "horizon_unavailable",
                    "No Horizon daily report is available in PostgreSQL.",
                    503,
                )
            return self._stamp_daily(
                any_daily,
                provider="horizon",
                preference=preference,
                served_from="forced",
                extra_warnings=[
                    "horizon_archive_read",
                    "horizon_run outside max_age / freshness window",
                ],
            )
        if any_daily is not None:
            raise NewsFacadeError(
                "horizon_stale",
                "Horizon daily is present but outside freshness window.",
                503,
            )
        raise NewsFacadeError(
            "horizon_unavailable",
            "No Horizon daily report is available in PostgreSQL.",
            503,
        )

    def _horizon_dailies(
        self,
        *,
        forced: bool,
        preference: Preference,
        take: int,
    ) -> dict[str, Any]:
        self._require_horizon_enabled()
        page = self._call_optional(
            self._load_horizon_dailies,
            settings=self.settings,
            take=take,
        )
        if page is None or not page.items:
            raise NewsFacadeError(
                "horizon_unavailable",
                "No Horizon daily index is available in PostgreSQL.",
                503,
            )
        run = self._safe_latest_run()
        return self._stamp_dailies(
            page,
            provider="horizon",
            preference=preference,
            served_from="forced" if forced else "failover",
            extra_warnings=_horizon_run_warnings(run),
        )

    # --------------------------------------------------------------- live aihot

    def _aihot_live_items(self, **kwargs: Any) -> AiHotItemsPage:
        client = self._require_client()
        return client.items(**kwargs)

    def _aihot_live_daily(self, *, date: str | None) -> AiHotDaily:
        client = self._require_client()
        return client.daily(date=date)

    def _aihot_live_dailies(self, *, take: int) -> AiHotDailiesPage:
        client = self._require_client()
        return client.dailies(take=take)

    # ------------------------------------------------------------ horizon load

    def _horizon_fresh_items(
        self,
        **kwargs: Any,
    ) -> tuple[AiHotItemsPage, dict[str, Any] | None] | None:
        run = self._safe_latest_run()
        if run is None:
            return None
        page = self._call_optional(
            self._load_horizon_items_page,
            settings=self.settings,
            take=kwargs.get("take", 50),
            category=kwargs.get("category"),
            q=kwargs.get("q"),
            since=kwargs.get("since"),
        )
        if page is None or not page.items:
            return None
        return page, run

    def _horizon_fresh_daily(
        self,
        *,
        date: str | None,
    ) -> tuple[AiHotDaily, dict[str, Any] | None] | None:
        run = self._safe_latest_run()
        if run is None:
            return None
        daily = self._call_optional(
            self._load_horizon_daily,
            settings=self.settings,
            date=date,
        )
        if daily is None:
            return None
        if date is None and not _daily_is_recent_enough(daily.date, now=self._now()):
            return None
        if date is not None and daily.date != date:
            return None
        return daily, run

    def _safe_latest_run(self) -> dict[str, Any] | None:
        return self._call_optional(
            self._load_latest_horizon_run,
            settings=self.settings,
            now=self._now(),
        )

    # ---------------------------------------------------------------- caching

    def _try_cache_items(self, page: AiHotItemsPage, **kwargs: Any) -> None:
        if self._cache_aihot_items is None:
            return
        try:
            self._cache_aihot_items(
                page,
                settings=self.settings,
                mode=kwargs.get("mode", "selected"),
                category=kwargs.get("category"),
                q=kwargs.get("q"),
                since=kwargs.get("since"),
                cursor=kwargs.get("cursor"),
                take=kwargs.get("take", 50),
            )
        except TypeError:
            # Callers may accept a query object instead of kwargs.
            try:
                from quant_system.news.repository import AiHotItemsCacheQuery

                query = AiHotItemsCacheQuery(
                    mode=kwargs.get("mode", "selected"),
                    category=kwargs.get("category"),
                    q=kwargs.get("q"),
                    since=kwargs.get("since"),
                    cursor=kwargs.get("cursor"),
                    take=kwargs.get("take", 50),
                )
                self._cache_aihot_items(page, settings=self.settings, query=query)
            except Exception:  # noqa: BLE001 - best effort
                return
        except Exception:  # noqa: BLE001 - best effort
            return

    def _load_aihot_cache(self, **kwargs: Any) -> AiHotItemsPage | None:
        if self._load_cached_aihot_items is None:
            return None
        try:
            return self._load_cached_aihot_items(
                settings=self.settings,
                mode=kwargs.get("mode", "selected"),
                category=kwargs.get("category"),
                q=kwargs.get("q"),
                since=kwargs.get("since"),
                cursor=kwargs.get("cursor"),
                take=kwargs.get("take", 50),
            )
        except TypeError:
            try:
                from quant_system.news.repository import AiHotItemsCacheQuery

                query = AiHotItemsCacheQuery(
                    mode=kwargs.get("mode", "selected"),
                    category=kwargs.get("category"),
                    q=kwargs.get("q"),
                    since=kwargs.get("since"),
                    cursor=kwargs.get("cursor"),
                    take=kwargs.get("take", 50),
                )
                return self._load_cached_aihot_items(settings=self.settings, query=query)
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None

    def _try_cache_daily(self, daily: AiHotDaily) -> None:
        if self._cache_aihot_daily is None:
            return
        try:
            self._cache_aihot_daily(daily, settings=self.settings)
        except Exception:  # noqa: BLE001
            return

    def _load_aihot_daily_cache(self, *, date: str | None) -> AiHotDaily | None:
        if self._load_cached_aihot_daily is None:
            return None
        report_date = date or _current_brief_date(self._now())
        try:
            return self._load_cached_aihot_daily(report_date, settings=self.settings)
        except Exception:  # noqa: BLE001
            return None

    # ---------------------------------------------------------------- stamping

    def _stamp_items(
        self,
        page: AiHotItemsPage,
        *,
        provider: str,
        preference: Preference,
        served_from: ServedFrom,
        extra_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        warnings = _merge_warnings(page.warnings, extra_warnings, provider=provider, settings=self.settings)
        return {
            "provider": provider,
            "provider_beta": _provider_beta(provider, self.settings),
            "fetched_at": page.fetched_at or utc_now_iso(),
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
            "warnings": warnings,
            "research_safety": _research_safety(),
            "preference": preference,
            "served_from": served_from,
        }

    def _stamp_daily(
        self,
        daily: AiHotDaily,
        *,
        provider: str,
        preference: Preference,
        served_from: ServedFrom,
        extra_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        warnings = _merge_warnings(daily.warnings, extra_warnings, provider=provider, settings=self.settings)
        return {
            "provider": provider,
            "provider_beta": _provider_beta(provider, self.settings),
            "fetched_at": daily.fetched_at or utc_now_iso(),
            "date": daily.date,
            "generated_at": daily.generated_at,
            "window_start": daily.window_start,
            "window_end": daily.window_end,
            "lead": daily.lead,
            "sections": daily.sections,
            "flashes": daily.flashes,
            "warnings": warnings,
            "research_safety": _research_safety(),
            "raw": daily.raw,
            "preference": preference,
            "served_from": served_from,
        }

    def _stamp_dailies(
        self,
        page: AiHotDailiesPage,
        *,
        provider: str,
        preference: Preference,
        served_from: ServedFrom,
        extra_warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        warnings = _merge_warnings(page.warnings, extra_warnings, provider=provider, settings=self.settings)
        return {
            "provider": provider,
            "provider_beta": _provider_beta(provider, self.settings),
            "fetched_at": page.fetched_at or utc_now_iso(),
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
            "warnings": warnings,
            "research_safety": _research_safety(),
            "preference": preference,
            "served_from": served_from,
        }

    # ---------------------------------------------------------------- helpers

    def _resolve_preference(self, preference: Preference | None) -> Preference:
        if preference is None:
            return self.settings.news.source_preference  # type: ignore[return-value]
        return preference

    def _failover_active(self) -> bool:
        return bool(self.settings.news.failover_enabled and self.settings.horizon.enabled)

    def _require_aihot_enabled(self) -> None:
        if self.settings.aihot.enabled:
            return
        raise NewsFacadeError(
            "aihot_disabled",
            "AI HOT news integration is disabled by QS_AIHOT_ENABLED.",
            503,
        )

    def _require_horizon_enabled(self) -> None:
        if self.settings.horizon.enabled:
            return
        raise NewsFacadeError(
            "horizon_unavailable",
            "Horizon news integration is disabled by QS_HORIZON_ENABLED.",
            503,
        )

    def _require_client(self) -> Any:
        if self._aihot_client is None:
            raise NewsFacadeError(
                "aihot_disabled",
                "AI HOT client is not configured.",
                503,
            )
        return self._aihot_client

    def _note_error(self, exc: AiHotProviderError) -> None:
        if self._remember_error is not None:
            self._remember_error(exc)

    @staticmethod
    def _call_optional(fn: Callable[..., Any] | None, **kwargs: Any) -> Any:
        if fn is None:
            return None
        try:
            return fn(**kwargs)
        except Exception:  # noqa: BLE001 - read path must survive loader failures
            return None


def _research_safety() -> dict[str, bool]:
    return {
        "research_only": True,
        "not_investment_advice": True,
        "does_not_trigger_trading": True,
        "verify_original_source": True,
    }


def _provider_beta(provider: str, settings: Settings) -> bool:
    if provider == "horizon":
        return bool(settings.horizon.provider_beta)
    return True


def _provider_warning(provider: str, settings: Settings) -> str | None:
    if provider == "aihot":
        return _AIHOT_BETA_WARNING
    if provider == "horizon" and settings.horizon.provider_beta:
        return _HORIZON_BETA_WARNING
    if provider == "horizon":
        return (
            "Horizon local research feed; verify claims against original sources."
        )
    return None


def _merge_warnings(
    base: list[str],
    extra: list[str] | None,
    *,
    provider: str,
    settings: Settings,
) -> list[str]:
    out: list[str] = []
    for item in [*(base or []), *(extra or [])]:
        text = str(item)
        if text and text not in out:
            out.append(text)
    provider_warning = _provider_warning(provider, settings)
    if provider_warning and provider_warning not in out:
        out.append(provider_warning)
    return out


def _failover_warnings(
    aihot_exc: AiHotProviderError | None,
    run: dict[str, Any] | None,
) -> list[str]:
    warnings: list[str] = []
    if aihot_exc is not None:
        warnings.append(f"aihot_upstream: {aihot_exc.message}")
        warnings.append(aihot_exc.message)
    warnings.append("served_from=horizon_failover")
    warnings.extend(_horizon_run_warnings(run))
    return warnings


def _cache_fallback_warnings(aihot_exc: AiHotProviderError | None) -> list[str]:
    warnings: list[str] = []
    if aihot_exc is not None:
        warnings.append(aihot_exc.message)
    warnings.append("aihot_cache_fallback")
    return warnings


def _horizon_run_warnings(run: dict[str, Any] | None) -> list[str]:
    if not run:
        return []
    warnings: list[str] = []
    run_id = run.get("run_id")
    if run_id:
        warnings.append(f"horizon_run_id={run_id}")
    generated_at = run.get("generated_at")
    if generated_at:
        warnings.append(f"horizon_generated_at={generated_at}")
    return warnings


def _unavailable_message(
    aihot_exc: AiHotProviderError | None,
    *,
    horizon_note: str,
) -> str:
    aihot_note = aihot_exc.message if aihot_exc is not None else "unavailable"
    return f"aihot={aihot_note}; horizon={horizon_note}"


def _status_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "run_id": run.get("run_id"),
        "generated_at": run.get("generated_at"),
        "ingested_at": run.get("ingested_at"),
        "item_count": run.get("item_count"),
        "status": run.get("status"),
    }


def _current_brief_date(now: datetime | None = None) -> str:
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def _daily_is_recent_enough(report_date: str, *, now: datetime) -> bool:
    """Auto failover accepts today or yesterday (UTC) as a fresh daily."""

    try:
        parsed = date.fromisoformat(report_date[:10])
    except ValueError:
        return False
    today = now.astimezone(UTC).date()
    return parsed >= today - timedelta(days=1)


# Re-export helper used by routes for default daily cache date.
current_brief_date = _current_brief_date
