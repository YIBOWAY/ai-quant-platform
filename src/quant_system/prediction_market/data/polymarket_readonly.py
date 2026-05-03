from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quant_system.prediction_market.models import (
    CLOBOrder,
    Market,
    MarketTrade,
    OrderBookSnapshot,
    Outcome,
    PriceHistoryPoint,
)
from quant_system.prediction_market.storage import PredictionMarketHttpCache

CacheMode = Literal["prefer_cache", "refresh", "network_only"]
JsonGetter = Callable[[str, float], object]
DEFAULT_USER_AGENT = "ai-quant-platform/phase11"


class PolymarketProviderError(RuntimeError):
    """Frontend-safe provider error without traceback details."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _default_get_json(url: str, timeout: float) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class PolymarketReadOnlyProvider:
    """Read-only Polymarket REST provider.

    This class performs public market-data GET requests only. It intentionally
    has no order submission, signing, wallet, private-key, token-transfer, or
    redeem methods.
    """

    provider_name = "polymarket"

    def __init__(
        self,
        *,
        gamma_base_url: str = "https://gamma-api.polymarket.com",
        clob_base_url: str = "https://clob.polymarket.com",
        data_api_base_url: str = "https://data-api.polymarket.com",
        timeout_seconds: int = 10,
        max_retries: int = 2,
        rate_limit_per_second: float = 2.0,
        cache_dir: str | Path | None = None,
        cache_ttl_seconds: int = 300,
        cache_stale_if_error_seconds: int = 86_400,
        cache_mode: CacheMode = "prefer_cache",
        user_agent: str = DEFAULT_USER_AGENT,
        get_json: JsonGetter | None = None,
    ) -> None:
        self.gamma_base_url = gamma_base_url.rstrip("/")
        self.clob_base_url = clob_base_url.rstrip("/")
        self.data_api_base_url = data_api_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.rate_limit_per_second = rate_limit_per_second
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_stale_if_error_seconds = cache_stale_if_error_seconds
        self.user_agent = user_agent
        if cache_mode not in {"prefer_cache", "refresh", "network_only"}:
            raise ValueError(f"unknown Polymarket cache_mode {cache_mode!r}")
        self.cache_mode: CacheMode = cache_mode
        self.get_json = get_json or self._get_json
        self.cache = (
            PredictionMarketHttpCache(cache_dir) if cache_dir is not None else None
        )
        self.last_cache_status: str = "live"
        self._markets_by_id: dict[str, Market] = {}
        self._last_request_monotonic = 0.0

    def _get_json(self, url: str, timeout: float) -> object:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def list_markets(self, limit: int | None = None) -> list[Market]:
        active_limit = max(1, min(limit or 50, 200))
        markets: list[Market] = []
        cursor: str | None = None
        while len(markets) < active_limit:
            page_limit = min(100, active_limit - len(markets))
            query = {"limit": page_limit, "closed": "false"}
            if cursor:
                query["next_cursor"] = cursor
            payload = self._request_json(
                f"{self.gamma_base_url}/markets/keyset?{urlencode(query)}",
                resource="markets",
            )
            page_markets, cursor = self._parse_markets_payload(payload)
            markets.extend(page_markets)
            if not cursor or not page_markets:
                break
        self._markets_by_id.update({market.market_id: market for market in markets})
        return markets[:active_limit]

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        market = self._markets_by_id.get(market_id)
        if market is None:
            matching = [
                item
                for item in self.list_markets(limit=100)
                if item.market_id == market_id
            ]
            market = matching[0] if matching else None
        if market is None:
            raise PolymarketProviderError(
                "provider_invalid_response",
                f"market_id {market_id!r} was not found in read-only market list",
            )

        return [
            self._fetch_order_book(market=market, token_id=outcome.token_id)
            for outcome in market.outcomes
        ]

    def get_price_history(
        self,
        token_id: str,
        *,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> list[PriceHistoryPoint]:
        query = urlencode(
            {
                "market": token_id,
                "interval": interval,
                "fidelity": fidelity,
            }
        )
        payload = self._request_json(
            f"{self.clob_base_url}/prices-history?{query}",
            resource="prices_history",
        )
        history = payload.get("history") if isinstance(payload, dict) else None
        if not isinstance(history, list):
            raise PolymarketProviderError(
                "provider_invalid_response",
                "Polymarket price history response was missing history data",
            )
        points: list[PriceHistoryPoint] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            timestamp = item.get("t")
            price = item.get("p")
            if timestamp is None or price is None:
                continue
            points.append(
                PriceHistoryPoint(
                    timestamp=_timestamp_to_iso(int(timestamp)),
                    price=float(price),
                )
            )
        return points

    def get_trades(
        self,
        condition_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MarketTrade]:
        query = urlencode({"market": condition_id, "limit": limit, "offset": offset})
        payload = self._request_json(
            f"{self.data_api_base_url}/trades?{query}",
            resource="trades",
        )
        if not isinstance(payload, list):
            raise PolymarketProviderError(
                "provider_invalid_response",
                "Polymarket trades response was not a JSON list",
            )
        trades: list[MarketTrade] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            trades.append(
                MarketTrade(
                    condition_id=str(item.get("conditionId") or condition_id),
                    token_id=str(item.get("asset") or ""),
                    price=float(item["price"]),
                    size=float(item["size"]),
                    side=str(item["side"]),
                    timestamp=_timestamp_to_iso(int(item["timestamp"])),
                )
            )
        return trades

    def _fetch_order_book(self, *, market: Market, token_id: str) -> OrderBookSnapshot:
        query = urlencode({"token_id": token_id})
        payload = self._request_json(
            f"{self.clob_base_url}/book?{query}",
            resource="order_book",
        )
        if not isinstance(payload, dict):
            raise PolymarketProviderError(
                "provider_invalid_response",
                "Polymarket order book response was not a JSON object",
            )
        return OrderBookSnapshot(
            market_id=market.market_id,
            condition_id=market.condition_id,
            token_id=token_id,
            bids=self._parse_orders(payload.get("bids", [])),
            asks=self._parse_orders(payload.get("asks", [])),
        )

    def _request_json(self, url: str, *, resource: str) -> object:
        cache_key = url
        if self.cache_mode == "prefer_cache" and self.cache is not None:
            cached = self.cache.read_json(
                resource=resource,
                cache_key=cache_key,
                max_age_seconds=self.cache_ttl_seconds,
            )
            if cached is not None:
                self.last_cache_status = "cache"
                return cached["payload"]

        attempts = self.max_retries + 1
        last_error: PolymarketProviderError | None = None
        for attempt in range(attempts):
            self._pace_request()
            try:
                payload = self.get_json(url, float(self.timeout_seconds))
                self.last_cache_status = "live"
                if self.cache is not None:
                    self.cache.write_json(
                        resource=resource,
                        cache_key=cache_key,
                        url=url,
                        payload=payload,
                    )
                return payload
            except TimeoutError:
                last_error = PolymarketProviderError(
                    "provider_timeout",
                    "Polymarket read-only request timed out",
                )
                if attempt + 1 >= attempts:
                    break
            except HTTPError as exc:
                last_error = PolymarketProviderError(
                    "provider_http_error",
                    f"Polymarket read-only request failed with HTTP {exc.code}",
                )
                if attempt + 1 >= attempts:
                    break
            except URLError:
                last_error = PolymarketProviderError(
                    "provider_timeout",
                    "Polymarket read-only request failed before a response was received",
                )
                if attempt + 1 >= attempts:
                    break

        if self.cache is not None and self.cache_mode != "network_only":
            stale = self.cache.read_stale_json(
                resource=resource,
                cache_key=cache_key,
                max_stale_seconds=self.cache_stale_if_error_seconds,
            )
            if stale is not None:
                self.last_cache_status = "stale_cache"
                return stale["payload"]

        if last_error is not None:
            raise last_error
        raise PolymarketProviderError(
            "provider_http_error",
            "Polymarket read-only request failed",
        )

    def _pace_request(self) -> None:
        min_interval = 1.0 / self.rate_limit_per_second
        elapsed = time.monotonic() - self._last_request_monotonic
        if self._last_request_monotonic and elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_monotonic = time.monotonic()

    @staticmethod
    def _parse_markets_payload(payload: object) -> tuple[list[Market], str | None]:
        if isinstance(payload, dict):
            rows = payload.get("markets")
            if not isinstance(rows, list):
                raise PolymarketProviderError(
                    "provider_invalid_response",
                    "Polymarket markets response was not a JSON list",
                )
            cursor = payload.get("next_cursor")
            parsed_rows = [
                PolymarketReadOnlyProvider._parse_market(item)
                for item in rows
                if isinstance(item, dict)
            ]
            return (
                parsed_rows,
                str(cursor) if cursor else None,
            )
        if isinstance(payload, list):
            parsed_rows = [
                PolymarketReadOnlyProvider._parse_market(item)
                for item in payload
                if isinstance(item, dict)
            ]
            return (
                parsed_rows,
                None,
            )
        raise PolymarketProviderError(
            "provider_invalid_response",
            "Polymarket markets response was not a JSON list",
        )

    @staticmethod
    def _parse_market(item: dict[str, Any]) -> Market:
        market_id = str(item.get("id") or item.get("market_id") or item.get("slug") or "")
        condition_id = str(item.get("conditionId") or item.get("condition_id") or "")
        question = str(item.get("question") or item.get("title") or market_id)
        event_id = str(
            item.get("event_id")
            or item.get("eventId")
            or item.get("eventSlug")
            or market_id
        )
        outcome_names = _coerce_json_list(item.get("outcomes"))
        token_ids = _coerce_json_list(item.get("clobTokenIds") or item.get("clob_token_ids"))
        if (
            not market_id
            or not condition_id
            or not outcome_names
            or len(outcome_names) != len(token_ids)
        ):
            raise PolymarketProviderError(
                "provider_invalid_response",
                "Polymarket market response is missing id, condition, outcomes, or token ids",
            )
        outcomes = [
            Outcome(name=str(name), outcome_index=index, token_id=str(token_ids[index]))
            for index, name in enumerate(outcome_names)
        ]
        return Market(
            market_id=market_id,
            event_id=event_id,
            condition_id=condition_id,
            question=question,
            outcomes=outcomes,
            active=bool(item.get("active", True)),
            closed=bool(item.get("closed", False)),
        )

    @staticmethod
    def _parse_orders(payload: object) -> list[CLOBOrder]:
        if not isinstance(payload, list):
            raise PolymarketProviderError(
                "provider_invalid_response",
                "Polymarket order book side was not a JSON list",
            )
        orders: list[CLOBOrder] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            orders.append(CLOBOrder(price=float(item["price"]), size=float(item["size"])))
        return orders


def _coerce_json_list(value: object) -> list[object]:
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    if isinstance(value, list):
        return value
    return []


def _timestamp_to_iso(value: int) -> str:
    seconds = value / 1000 if value > 10_000_000_000 else value
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))
