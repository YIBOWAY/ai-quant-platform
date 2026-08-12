"""Third-party market-news providers for the morning-brief topics lane.

Polygon is the primary lane and Finnhub the failover lane. NewsAPI is an
explicitly dev-only lane: its Developer tier is contractually localhost/dev-only
with up to 24h delay and content truncated to ~214 chars, so the facade gates it
behind both ``QS_MARKET_NEWS_NEWSAPI_DEV_ENABLED`` and local trust mode — it can
never be a production default.

All providers fail closed: HTTP errors, timeouts, and payload-level error bodies
(Polygon ``status=ERROR``, Finnhub 200-with-``error``, NewsAPI ``status=error``)
raise :class:`MarketNewsProviderError`. There are no sample-data fallbacks.

Items are normalized into the shared ``AiHotItemsPage`` model (category
``"market-topics"``) so the news facade can stamp provider / served_from
provenance exactly like the AI-news lanes. Futu remains the market-data lane;
these providers only supply news text, never prices.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from quant_system.news.models import AiHotItem, AiHotItemsPage

#: Default morning-brief topics query (Asia-market focus) used when the caller
#: passes no explicit keywords.
DEFAULT_ASIA_MARKET_KEYWORDS: tuple[str, ...] = (
    "hang seng",
    "nikkei",
    "taiwan semiconductor",
    "tsmc",
    "asia markets",
    "hong kong stocks",
)

_NEWSAPI_TRUNCATION_WARNING = (
    "newsapi_dev: Developer tier content is truncated (~214 chars) and delayed up to 24h"
)


class MarketNewsProviderError(RuntimeError):
    """Structured third-party market-news failure mapped by the facade."""

    def __init__(self, *, code: str, message: str, status_code: int) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"{code}: {message}")


def normalize_keywords(keywords: list[str] | tuple[str, ...] | None) -> list[str]:
    """Lowercased, trimmed, de-duplicated keyword list (order preserved)."""

    out: list[str] = []
    for keyword in keywords or []:
        text = str(keyword).strip().lower()
        if text and text not in out:
            out.append(text)
    return out


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    haystack = text.lower()
    return any(keyword in haystack for keyword in keywords)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _epoch_to_iso(value: Any) -> str | None:
    try:
        epoch = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def _invalid_response(provider: str, message: str) -> MarketNewsProviderError:
    return MarketNewsProviderError(
        code=f"{provider}_invalid_response",
        message=message,
        status_code=502,
    )


class _BaseMarketNewsClient:
    """Shared read-only HTTP plumbing with payload-level error detection."""

    provider: str = "base"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owns_http_client = http_client is None
        self._http_client = (
            http_client
            if http_client is not None
            else httpx.Client(timeout=timeout_seconds, follow_redirects=True)
        )

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def _payload_error(self, payload: Any) -> str | None:
        """Return an upstream error description from a parsed body, if any."""

        return None

    def _get_json(self, path: str, params: dict[str, str | None]) -> Any:
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        try:
            response = self._http_client.get(
                f"{self._base_url}{path}",
                params=clean_params,
                headers={"accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise MarketNewsProviderError(
                code=f"{self.provider}_timeout",
                message=f"{self.provider} request timed out",
                status_code=503,
            ) from exc
        except httpx.HTTPError as exc:
            raise MarketNewsProviderError(
                code=f"{self.provider}_bad_gateway",
                message=f"{self.provider} request failed: {exc.__class__.__name__}",
                status_code=502,
            ) from exc

        if response.status_code >= 400:
            detail: str | None = None
            try:
                detail = self._payload_error(response.json())
            except ValueError:
                detail = None
            message = f"{self.provider} upstream returned HTTP {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise MarketNewsProviderError(
                code=f"{self.provider}_bad_gateway",
                message=message,
                status_code=502,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise MarketNewsProviderError(
                code=f"{self.provider}_invalid_response",
                message=f"{self.provider} returned invalid JSON",
                status_code=502,
            ) from exc

        # Payload-level error detection is mandatory: several vendors answer
        # HTTP 200 with an error body (Finnhub) or a status field (Polygon).
        payload_error = self._payload_error(payload)
        if payload_error:
            raise MarketNewsProviderError(
                code=f"{self.provider}_error_payload",
                message=f"{self.provider} returned an error payload: {payload_error}",
                status_code=502,
            )
        return payload

    def _page(self, items: list[AiHotItem], *, take: int) -> AiHotItemsPage:
        warnings: list[str] = []
        if not items:
            warnings.append(f"{self.provider}_no_matching_articles")
        return AiHotItemsPage(
            count=len(items),
            has_next=False,
            next_cursor=None,
            items=items[:take],
            warnings=warnings,
        )


class PolygonNewsClient(_BaseMarketNewsClient):
    """Polygon ``/v2/reference/news`` (free tier: same-day articles, 5 req/min).

    The endpoint has no free-text query on the free tier, so keyword matching
    happens locally against title + description of the latest articles.
    """

    provider = "polygon"

    def _payload_error(self, payload: Any) -> str | None:
        if isinstance(payload, dict) and str(payload.get("status", "")).upper() == "ERROR":
            return str(payload.get("error") or payload.get("message") or "unknown error")
        return None

    def search(self, *, keywords: list[str], take: int = 20) -> AiHotItemsPage:
        limit = min(100, max(take * 3, 10))
        payload = self._get_json(
            "/v2/reference/news",
            {
                "limit": str(limit),
                "order": "desc",
                "sort": "published_utc",
                "apiKey": self._api_key,
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("results", []), list):
            raise _invalid_response(
                self.provider, "Polygon news response has unexpected shape"
            )
        items: list[AiHotItem] = []
        for raw in payload.get("results", []):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "")
            summary = _optional_string(raw.get("description"))
            if keywords and not _matches_keywords(f"{title} {summary or ''}", keywords):
                continue
            publisher = raw.get("publisher")
            publisher_name = (
                _optional_string(publisher.get("name"))
                if isinstance(publisher, dict)
                else None
            )
            url = str(raw.get("article_url") or "")
            items.append(
                AiHotItem(
                    id=str(raw.get("id") or url),
                    title=title,
                    title_en=None,
                    url=url,
                    source=publisher_name or "polygon",
                    published_at=_optional_string(raw.get("published_utc")),
                    summary=summary,
                    category="market-topics",
                    score=None,
                    selected=None,
                    raw=dict(raw),
                )
            )
            if len(items) >= take:
                break
        return self._page(items, take=take)


class FinnhubNewsClient(_BaseMarketNewsClient):
    """Finnhub ``/api/v1/news?category=general`` (free tier, ~100 articles).

    Keyword matching happens locally against headline + summary.
    """

    provider = "finnhub"

    def _payload_error(self, payload: Any) -> str | None:
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload.get("error"))
        return None

    def search(self, *, keywords: list[str], take: int = 20) -> AiHotItemsPage:
        payload = self._get_json(
            "/api/v1/news",
            {"category": "general", "token": self._api_key},
        )
        if not isinstance(payload, list):
            raise _invalid_response(
                self.provider, "Finnhub news response has unexpected shape"
            )
        items: list[AiHotItem] = []
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("headline") or "")
            summary = _optional_string(raw.get("summary"))
            if keywords and not _matches_keywords(f"{title} {summary or ''}", keywords):
                continue
            url = str(raw.get("url") or "")
            items.append(
                AiHotItem(
                    id=str(raw.get("id") or url),
                    title=title,
                    title_en=None,
                    url=url,
                    source=str(raw.get("source") or "finnhub"),
                    published_at=_epoch_to_iso(raw.get("datetime")),
                    summary=summary,
                    category="market-topics",
                    score=None,
                    selected=None,
                    raw=dict(raw),
                )
            )
            if len(items) >= take:
                break
        return self._page(items, take=take)


class NewsApiClient(_BaseMarketNewsClient):
    """NewsAPI ``/v2/everything`` — DEV-ONLY lane.

    Developer tier is contractually localhost/dev-only: 24h delay, 1-month
    history cap (HTTP 426 beyond), content truncated to ~214 chars. The facade
    refuses to call this client outside local trust mode.
    """

    provider = "newsapi"

    def _payload_error(self, payload: Any) -> str | None:
        if isinstance(payload, dict) and payload.get("status") != "ok":
            code = payload.get("code") or "unknown"
            message = payload.get("message") or "unknown error"
            return f"{code}: {message}"
        return None

    def search(self, *, keywords: list[str], take: int = 20) -> AiHotItemsPage:
        query = " OR ".join(f'"{keyword}"' for keyword in keywords) or "markets"
        payload = self._get_json(
            "/v2/everything",
            {
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": str(min(100, max(take, 10))),
                "apiKey": self._api_key,
            },
        )
        articles = payload.get("articles") if isinstance(payload, dict) else None
        if not isinstance(articles, list):
            raise _invalid_response(
                self.provider, "NewsAPI response has unexpected shape"
            )
        items: list[AiHotItem] = []
        for raw in articles:
            if not isinstance(raw, dict):
                continue
            source = raw.get("source")
            source_name = (
                _optional_string(source.get("name")) if isinstance(source, dict) else None
            )
            url = str(raw.get("url") or "")
            items.append(
                AiHotItem(
                    id=str(raw.get("url") or raw.get("publishedAt") or ""),
                    title=str(raw.get("title") or ""),
                    title_en=None,
                    url=url,
                    source=source_name or "newsapi",
                    published_at=_optional_string(raw.get("publishedAt")),
                    summary=_optional_string(raw.get("description")),
                    category="market-topics",
                    score=None,
                    selected=None,
                    raw=dict(raw),
                )
            )
            if len(items) >= take:
                break
        page = self._page(items, take=take)
        if _NEWSAPI_TRUNCATION_WARNING not in page.warnings:
            page.warnings.append(_NEWSAPI_TRUNCATION_WARNING)
        return page
