from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from quant_system.prediction_market.models import CLOBOrder, Market, OrderBookSnapshot, Outcome

JsonGetter = Callable[[str, float], object]


class PolymarketProviderError(RuntimeError):
    """Frontend-safe provider error without traceback details."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _default_get_json(url: str, timeout: float) -> object:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class PolymarketReadOnlyProvider:
    """Read-only Polymarket REST provider.

    This class performs market-data GET requests only. It intentionally has no
    order submission, signing, wallet, private-key, token-transfer, or redeem
    methods.
    """

    provider_name = "polymarket"

    def __init__(
        self,
        *,
        gamma_base_url: str = "https://gamma-api.polymarket.com",
        clob_base_url: str = "https://clob.polymarket.com",
        timeout_seconds: int = 10,
        max_retries: int = 2,
        rate_limit_per_second: float = 2.0,
        get_json: JsonGetter = _default_get_json,
    ) -> None:
        self.gamma_base_url = gamma_base_url.rstrip("/")
        self.clob_base_url = clob_base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.rate_limit_per_second = rate_limit_per_second
        self.get_json = get_json
        self._markets_by_id: dict[str, Market] = {}
        self._last_request_monotonic = 0.0

    def list_markets(self, limit: int = 50) -> list[Market]:
        query = urlencode({"limit": limit, "active": "true", "closed": "false"})
        payload = self._request_json(f"{self.gamma_base_url}/markets?{query}")
        if not isinstance(payload, list):
            raise PolymarketProviderError(
                "provider_invalid_response",
                "Polymarket markets response was not a JSON list",
            )
        markets = [self._parse_market(item) for item in payload if isinstance(item, dict)]
        self._markets_by_id.update({market.market_id: market for market in markets})
        return markets

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

    def _fetch_order_book(self, *, market: Market, token_id: str) -> OrderBookSnapshot:
        query = urlencode({"token_id": token_id})
        payload = self._request_json(f"{self.clob_base_url}/book?{query}")
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

    def _request_json(self, url: str) -> object:
        attempts = self.max_retries + 1
        last_error: PolymarketProviderError | None = None
        for attempt in range(attempts):
            self._pace_request()
            try:
                return self.get_json(url, float(self.timeout_seconds))
            except TimeoutError as exc:
                last_error = PolymarketProviderError(
                    "provider_timeout",
                    "Polymarket read-only request timed out",
                )
                if attempt + 1 >= attempts:
                    raise last_error from exc
            except HTTPError as exc:
                raise PolymarketProviderError(
                    "provider_http_error",
                    f"Polymarket read-only request failed with HTTP {exc.code}",
                ) from exc
            except URLError as exc:
                last_error = PolymarketProviderError(
                    "provider_timeout",
                    "Polymarket read-only request failed before a response was received",
                )
                if attempt + 1 >= attempts:
                    raise last_error from exc
        if last_error is not None:
            raise last_error
        raise PolymarketProviderError("provider_http_error", "Polymarket read-only request failed")

    def _pace_request(self) -> None:
        min_interval = 1.0 / self.rate_limit_per_second
        elapsed = time.monotonic() - self._last_request_monotonic
        if self._last_request_monotonic and elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_request_monotonic = time.monotonic()

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
