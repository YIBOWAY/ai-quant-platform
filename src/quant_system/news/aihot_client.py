from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

import httpx

from quant_system.news.models import (
    AiHotDailiesPage,
    AiHotDaily,
    AiHotDailyIndex,
    AiHotItem,
    AiHotItemsPage,
)


class AiHotProviderError(RuntimeError):
    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


class AiHotClient:
    """Small read-only client for AI HOT public endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: int,
        user_agent: str,
        cache_ttl_seconds: int = 0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._cache_ttl_seconds = cache_ttl_seconds
        self._owns_http_client = http_client is None
        self._http_client = (
            http_client
            if http_client is not None
            else httpx.Client(
                timeout=timeout_seconds,
                follow_redirects=True,
            )
        )
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, Any]] = {}

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()
        self._cache.clear()

    def items(
        self,
        *,
        mode: str = "selected",
        category: str | None = None,
        q: str | None = None,
        since: str | None = None,
        cursor: str | None = None,
        take: int = 50,
    ) -> AiHotItemsPage:
        payload = self._get_json(
            "/api/public/items",
            {
                "mode": mode,
                "category": category,
                "q": q,
                "since": since,
                "cursor": cursor,
                "take": str(take),
            },
        )
        return self._parse_items_page(payload)

    def daily(self, *, date: str | None = None) -> AiHotDaily:
        path = f"/api/public/daily/{date}" if date else "/api/public/daily"
        return self._parse_daily(self._get_json(path, {}))

    def dailies(self, *, take: int = 14) -> AiHotDailiesPage:
        return self._parse_dailies_page(
            self._get_json("/api/public/dailies", {"take": str(take)})
        )

    def _get_json(self, path: str, params: Mapping[str, str | None]) -> Any:
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        cache_key = (path, tuple(sorted(clean_params.items())))
        if self._cache_ttl_seconds > 0:
            cached = self._cache.get(cache_key)
            if cached is not None and cached[0] >= time.monotonic():
                return cached[1]
        try:
            response = self._http_client.get(
                f"{self._base_url}{path}",
                params=clean_params,
                headers={
                    "accept": "application/json",
                    "user-agent": self._user_agent,
                },
            )
        except httpx.TimeoutException as exc:
            raise AiHotProviderError(
                code="aihot_timeout",
                message="AI HOT request timed out",
                status_code=503,
            ) from exc
        except httpx.HTTPError as exc:
            raise AiHotProviderError(
                code="aihot_bad_gateway",
                message=f"AI HOT request failed: {exc.__class__.__name__}",
                status_code=502,
            ) from exc

        if response.status_code >= 400:
            raise AiHotProviderError(
                code="aihot_bad_gateway",
                message=f"AI HOT upstream returned HTTP {response.status_code}",
                status_code=502,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise AiHotProviderError(
                code="aihot_invalid_response",
                message="AI HOT returned invalid JSON",
                status_code=502,
            ) from exc
        if self._cache_ttl_seconds > 0:
            self._cache[cache_key] = (time.monotonic() + self._cache_ttl_seconds, payload)
        return payload

    def _parse_items_page(self, payload: Any) -> AiHotItemsPage:
        if not isinstance(payload, dict) or not isinstance(payload.get("items", []), list):
            raise _invalid_response("AI HOT items response has unexpected shape")
        raw_items = payload.get("items", [])
        items = [self._parse_item(item) for item in raw_items if isinstance(item, dict)]
        count = _int_value(payload.get("count"), default=len(items))
        return AiHotItemsPage(
            count=count,
            has_next=bool(payload.get("hasNext", payload.get("has_next", False))),
            next_cursor=_optional_string(payload.get("nextCursor", payload.get("next_cursor"))),
            items=items,
            warnings=_string_list(payload.get("warnings")),
        )

    def _parse_item(self, payload: dict[str, Any]) -> AiHotItem:
        return AiHotItem(
            id=_string_value(payload.get("id")) or _string_value(payload.get("url")),
            title=_string_value(payload.get("title")),
            title_en=_optional_string(payload.get("title_en", payload.get("titleEn"))),
            url=_string_value(payload.get("url", payload.get("sourceUrl"))),
            source=_string_value(payload.get("source", payload.get("sourceName"))),
            published_at=_optional_string(
                payload.get("publishedAt", payload.get("published_at"))
            ),
            summary=_optional_string(payload.get("summary")),
            category=_optional_string(payload.get("category")),
            score=_float_value(payload.get("score", payload.get("aiScore"))),
            selected=_optional_bool(payload.get("selected", payload.get("aiSelected"))),
            raw=dict(payload),
        )

    def _parse_daily(self, payload: Any) -> AiHotDaily:
        if not isinstance(payload, dict):
            raise _invalid_response("AI HOT daily response has unexpected shape")
        lead = payload.get("lead")
        sections = payload.get("sections", [])
        flashes = payload.get("flashes", [])
        return AiHotDaily(
            date=_string_value(payload.get("date")),
            generated_at=_optional_string(payload.get("generatedAt", payload.get("generated_at"))),
            window_start=_optional_string(payload.get("windowStart", payload.get("window_start"))),
            window_end=_optional_string(payload.get("windowEnd", payload.get("window_end"))),
            lead=lead if isinstance(lead, dict) else None,
            sections=[item for item in sections if isinstance(item, dict)]
            if isinstance(sections, list)
            else [],
            flashes=[item for item in flashes if isinstance(item, dict)]
            if isinstance(flashes, list)
            else [],
            warnings=_string_list(payload.get("warnings")),
            raw=dict(payload),
        )

    def _parse_dailies_page(self, payload: Any) -> AiHotDailiesPage:
        if not isinstance(payload, dict) or not isinstance(payload.get("items", []), list):
            raise _invalid_response("AI HOT dailies response has unexpected shape")
        raw_items = payload.get("items", [])
        items = [
            AiHotDailyIndex(
                date=_string_value(item.get("date")),
                generated_at=_optional_string(item.get("generatedAt", item.get("generated_at"))),
                lead_title=_optional_string(item.get("leadTitle", item.get("lead_title"))),
                raw=dict(item),
            )
            for item in raw_items
            if isinstance(item, dict)
        ]
        return AiHotDailiesPage(
            count=_int_value(payload.get("count"), default=len(items)),
            items=items,
            warnings=_string_list(payload.get("warnings")),
        )


def _invalid_response(message: str) -> AiHotProviderError:
    return AiHotProviderError(
        code="aihot_invalid_response",
        message=message,
        status_code=502,
    )


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]
