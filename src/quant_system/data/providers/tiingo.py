from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from pydantic import SecretStr

from quant_system.data.schema import normalize_ohlcv_dataframe

JsonGetter = Callable[[str, dict[str, str]], list[dict[str, object]]]


class TiingoProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retry_after_seconds = retry_after_seconds


def _parse_retry_after(headers: object) -> float | None:
    raw = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _default_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        if exc.code == 404:
            raise TiingoProviderError(
                "symbol_not_found",
                f"Tiingo returned HTTP 404: {detail}",
            ) from exc
        if exc.code == 429:
            raise TiingoProviderError(
                "rate_limited",
                "Tiingo rate limit exceeded",
                retry_after_seconds=_parse_retry_after(exc.headers),
            ) from exc
        if exc.code in (401, 403):
            raise TiingoProviderError(
                "unauthorized",
                f"Tiingo rejected the API token (HTTP {exc.code}): {detail}",
            ) from exc
        raise TiingoProviderError(
            "http_error",
            f"Tiingo request failed with HTTP {exc.code}: {detail}",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TiingoProviderError(
            "provider_unavailable",
            f"Tiingo request failed: {type(exc).__name__}",
        ) from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TiingoProviderError(
            "payload_error",
            "Tiingo returned a non-JSON response",
        ) from exc
    # Payload-level error detection: Tiingo error bodies are JSON objects
    # (``{"detail": "..."}``) while success is always a JSON list of rows.
    if not isinstance(parsed, list):
        detail = parsed.get("detail") if isinstance(parsed, dict) else None
        raise TiingoProviderError(
            "payload_error",
            f"Tiingo response must be a JSON list: {detail or type(parsed).__name__}",
        )
    return parsed


def _prefer_adjusted(
    item: dict[str, object],
    *,
    adjusted_key: str,
    raw_key: str,
) -> object:
    adjusted = item.get(adjusted_key)
    return item[raw_key] if adjusted is None else adjusted


def _price_adjustment_status(item: dict[str, object]) -> str:
    adjusted_keys = ("adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume")
    adjusted_count = sum(item.get(key) is not None for key in adjusted_keys)
    if adjusted_count == len(adjusted_keys):
        return "adjusted"
    if adjusted_count == 0:
        return "raw"
    return "mixed"


class TiingoEODProvider:
    provider_name = "tiingo"

    def __init__(
        self,
        api_token: str | SecretStr | None,
        *,
        get_json: JsonGetter = _default_get_json,
        rate_limit_max_retries: int = 1,
        rate_limit_retry_seconds: float = 65.0,
        sleep_func: Callable[[float], None] = time.sleep,
        strict_symbols: bool = False,
    ) -> None:
        self.api_token = (
            api_token.get_secret_value()
            if isinstance(api_token, SecretStr)
            else api_token
        )
        self.get_json = get_json
        self.rate_limit_max_retries = rate_limit_max_retries
        self.rate_limit_retry_seconds = rate_limit_retry_seconds
        self._sleep_func = sleep_func
        # ``strict_symbols=True`` makes any single symbol failure (invalid ticker,
        # HTTP error, empty payload) fail the whole batch. The disaster-recovery
        # backup chain opts in because it validates the returned frame against the
        # full request; the default keeps the long-standing per-symbol tolerance
        # relied on by the shared ingestion pipelines (one delisted/thin ticker
        # must not fail the remaining symbols).
        self._strict_symbols = strict_symbols

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Same US-only discipline as the Futu lane: plain ticker or US.-prefixed."""
        normalized = symbol.upper().strip()
        if not normalized:
            raise TiingoProviderError("invalid_symbol", "symbol must not be empty")
        if normalized.startswith("US."):
            normalized = normalized.split(".", 1)[1]
        # Class-share tickers such as BRK.B keep their dot (Tiingo spells them
        # ``BRK.B``); whitespace is never valid in a ticker.
        if not normalized or any(ch.isspace() for ch in normalized):
            raise TiingoProviderError(
                "invalid_symbol",
                f"Tiingo expects plain US tickers: {symbol}",
            )
        return normalized

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if interval.lower().strip() != "1d":
            raise ValueError(f"Tiingo provider only supports daily OHLCV: {interval}")
        if not self.api_token:
            raise ValueError("Tiingo API token is required")

        rows: list[dict[str, object]] = []
        for symbol in symbols:
            try:
                normalized = self.normalize_symbol(symbol)
                rows.extend(self._fetch_symbol(normalized, start=start, end=end))
            except TiingoProviderError:
                if self._strict_symbols:
                    raise
                # Default (shared-pipeline) mode: tolerate per-symbol failures so
                # one bad/delisted ticker cannot fail the whole batch.

        return normalize_ohlcv_dataframe(
            pd.DataFrame(rows),
            provider=self.provider_name,
            interval=interval,
        )

    def _fetch_symbol(self, symbol: str, *, start: str, end: str) -> list[dict[str, object]]:
        query = urlencode({"startDate": start, "endDate": end, "format": "json"})
        url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices?{query}"
        headers = {
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json",
        }
        payload = self._get_with_rate_limit_retry(url, headers)
        if not payload:
            raise TiingoProviderError(
                "no_data",
                f"Tiingo returned no daily rows for {symbol}",
            )
        # ``knowledge_ts`` reflects when the system actually learned about the row.
        # For end-of-day data we use the download time so PIT replays do not see
        # bars before they could have been observed in production.
        download_ts = pd.Timestamp.now(tz="UTC").isoformat()
        rows: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict) or "date" not in item:
                raise TiingoProviderError(
                    "payload_error",
                    f"Tiingo row is missing date for {symbol}",
                )
            price_adjustment = _price_adjustment_status(item)
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": item["date"],
                    "open": _prefer_adjusted(item, adjusted_key="adjOpen", raw_key="open"),
                    "high": _prefer_adjusted(item, adjusted_key="adjHigh", raw_key="high"),
                    "low": _prefer_adjusted(item, adjusted_key="adjLow", raw_key="low"),
                    "close": _prefer_adjusted(
                        item,
                        adjusted_key="adjClose",
                        raw_key="close",
                    ),
                    "volume": _prefer_adjusted(
                        item,
                        adjusted_key="adjVolume",
                        raw_key="volume",
                    ),
                    "price_adjustment": price_adjustment,
                    "event_ts": item["date"],
                    "knowledge_ts": download_ts,
                }
            )
        return rows

    def _get_with_rate_limit_retry(
        self,
        url: str,
        headers: dict[str, str],
    ) -> list[dict[str, object]]:
        last_error: TiingoProviderError | None = None
        for attempt in range(self.rate_limit_max_retries + 1):
            try:
                return self.get_json(url, headers)
            except TiingoProviderError as exc:
                if exc.code != "rate_limited" or attempt >= self.rate_limit_max_retries:
                    raise
                last_error = exc
                self._sleep_func(exc.retry_after_seconds or self.rate_limit_retry_seconds)
        assert last_error is not None  # for type checkers; loop always raises/returns
        raise last_error
