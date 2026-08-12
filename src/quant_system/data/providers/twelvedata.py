from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from pydantic import SecretStr

from quant_system.data.schema import normalize_ohlcv_dataframe

BASE_URL = "https://api.twelvedata.com"

# (payload, response-headers) pair so callers can read the api-credits-*
# quota headers that Twelve Data attaches to every response.
JsonResponse = tuple[dict[str, Any], dict[str, str]]
RequestJson = Callable[[str, dict[str, str]], JsonResponse]


class TwelveDataProviderError(RuntimeError):
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


def _parse_retry_after(headers: Any) -> float | None:
    raw = headers.get("Retry-After") if headers is not None else None
    if raw is None:
        return None
    try:
        return max(0.0, float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _payload_error(payload: Any) -> TwelveDataProviderError | None:
    """Payload-level error detection: Twelve Data signals failures in-band.

    Verified error model (2026-08-11): errors arrive as
    ``{"status": "error", "code": <int>, "message": <str>}`` — sometimes under
    HTTP 200 — and plan-gated (non-US) symbols surface as 404 disguised as an
    invalid symbol. HTTP-status-only handling would silently misclassify both.
    """
    if not isinstance(payload, dict):
        return TwelveDataProviderError(
            "payload_error",
            "Twelve Data response must be a JSON object",
        )
    if str(payload.get("status", "")).lower() == "ok" and "values" in payload:
        return None
    code = payload.get("code")
    message = str(payload.get("message") or "Twelve Data request failed")
    try:
        numeric_code = int(code) if code is not None else None
    except (TypeError, ValueError):
        numeric_code = None
    if numeric_code == 404:
        return TwelveDataProviderError("symbol_not_found_or_plan_gated", message)
    if numeric_code == 429:
        return TwelveDataProviderError("rate_limited", message)
    if numeric_code in (401, 403):
        return TwelveDataProviderError("unauthorized", message)
    return TwelveDataProviderError("payload_error", message)


def _default_request_json(url: str, headers: dict[str, str]) -> JsonResponse:
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            response_headers = dict(response.headers.items())
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        parsed: Any
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {}
        # Only trust the payload when it carries Twelve Data's structured
        # error shape; otherwise the HTTP status code is authoritative.
        payload_error = (
            _payload_error(parsed)
            if isinstance(parsed, dict)
            and any(key in parsed for key in ("status", "code", "message"))
            else None
        )
        if payload_error is not None:
            # HTTP status and payload disagree by design on this API; the
            # payload wins when it carries a structured error.
            if payload_error.code == "rate_limited":
                payload_error.retry_after_seconds = _parse_retry_after(exc.headers)
            raise payload_error from exc
        if exc.code == 404:
            raise TwelveDataProviderError(
                "symbol_not_found_or_plan_gated",
                f"Twelve Data returned HTTP 404: {body[:200]}",
            ) from exc
        if exc.code == 429:
            raise TwelveDataProviderError(
                "rate_limited",
                "Twelve Data rate limit exceeded",
                retry_after_seconds=_parse_retry_after(exc.headers),
            ) from exc
        if exc.code in (401, 403):
            raise TwelveDataProviderError(
                "unauthorized",
                f"Twelve Data rejected the API key (HTTP {exc.code})",
            ) from exc
        raise TwelveDataProviderError(
            "http_error",
            f"Twelve Data request failed with HTTP {exc.code}",
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TwelveDataProviderError(
            "provider_unavailable",
            f"Twelve Data request failed: {type(exc).__name__}",
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TwelveDataProviderError(
            "payload_error",
            "Twelve Data returned a non-JSON response",
        ) from exc
    error = _payload_error(payload)
    if error is not None:
        raise error
    return payload, response_headers


class TwelveDataDailyProvider:
    """Read-only daily OHLCV backup lane (split-adjusted, EOD).

    US-listed symbols only: the verified Basic plan returns split-adjusted
    daily bars (``adjust=splits`` default, 11+ year depth, 1 credit/symbol)
    for US tickers and 404-plan-gates everything else. Latest bar is the
    prior session; ``knowledge_ts`` therefore uses the download time.
    """

    provider_name = "twelvedata"

    def __init__(
        self,
        api_key: str | SecretStr | None,
        *,
        request_json: RequestJson = _default_request_json,
        rate_limit_max_retries: int = 1,
        rate_limit_retry_seconds: float = 65.0,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = (
            api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        )
        self.request_json = request_json
        self.rate_limit_max_retries = rate_limit_max_retries
        self.rate_limit_retry_seconds = rate_limit_retry_seconds
        self._sleep_func = sleep_func
        self.last_api_credits_used: int | None = None
        self.last_api_credits_left: int | None = None

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Same US-only discipline as the Futu lane: plain ticker or US.-prefixed."""
        normalized = symbol.upper().strip()
        if not normalized:
            raise TwelveDataProviderError("invalid_symbol", "symbol must not be empty")
        if normalized.startswith("US."):
            normalized = normalized.split(".", 1)[1]
        if not normalized or "." in normalized or any(ch.isspace() for ch in normalized):
            raise TwelveDataProviderError(
                "invalid_symbol",
                f"Twelve Data backup lane expects plain US tickers: {symbol}",
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
            raise ValueError(f"Twelve Data provider only supports daily OHLCV: {interval}")
        if not self.api_key:
            raise ValueError("Twelve Data API key is required")

        rows: list[dict[str, object]] = []
        for symbol in symbols:
            rows.extend(
                self._fetch_symbol(self.normalize_symbol(symbol), start=start, end=end)
            )
        return normalize_ohlcv_dataframe(
            pd.DataFrame(rows),
            provider=self.provider_name,
            interval=interval,
        )

    def _fetch_symbol(self, symbol: str, *, start: str, end: str) -> list[dict[str, object]]:
        query = urlencode(
            {
                "symbol": symbol,
                "interval": "1day",
                "start_date": start,
                "end_date": end,
                "outputsize": 5000,
                "order": "ASC",
                "format": "JSON",
                "apikey": self.api_key,
            }
        )
        url = f"{BASE_URL}/time_series?{query}"
        payload, headers = self._request_with_rate_limit_retry(url)
        self._track_credits(headers)

        # Payload-level error detection also runs here so injected/transport
        # wrappers cannot smuggle an in-band error body through as data.
        payload_error = _payload_error(payload)
        if payload_error is not None:
            raise payload_error

        meta = payload.get("meta")
        if isinstance(meta, dict):
            meta_symbol = str(meta.get("symbol", "")).upper().strip()
            if meta_symbol and meta_symbol != symbol:
                raise TwelveDataProviderError(
                    "payload_error",
                    f"Twelve Data returned meta.symbol={meta_symbol} for request {symbol}",
                )
        values = payload.get("values")
        if not isinstance(values, list) or not values:
            raise TwelveDataProviderError(
                "no_data",
                f"Twelve Data returned no daily rows for {symbol}",
            )

        download_ts = pd.Timestamp.now(tz="UTC").isoformat()
        rows: list[dict[str, object]] = []
        for item in values:
            if not isinstance(item, dict) or "datetime" not in item:
                raise TwelveDataProviderError(
                    "payload_error",
                    f"Twelve Data row is missing datetime for {symbol}",
                )
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": item["datetime"],
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "close": item.get("close"),
                    "volume": item.get("volume"),
                    # Verified plan behavior: /time_series defaults to
                    # split-adjusted (adjust=splits) daily bars.
                    "price_adjustment": "splits",
                    "event_ts": item["datetime"],
                    "knowledge_ts": download_ts,
                }
            )
        return rows

    def _request_with_rate_limit_retry(self, url: str) -> JsonResponse:
        last_error: TwelveDataProviderError | None = None
        for attempt in range(self.rate_limit_max_retries + 1):
            try:
                return self.request_json(url, {"Content-Type": "application/json"})
            except TwelveDataProviderError as exc:
                if exc.code != "rate_limited" or attempt >= self.rate_limit_max_retries:
                    raise
                last_error = exc
                self._sleep_func(exc.retry_after_seconds or self.rate_limit_retry_seconds)
        assert last_error is not None  # for type checkers; loop always raises/returns
        raise last_error

    def _track_credits(self, headers: dict[str, str]) -> None:
        lowered = {key.lower(): value for key, value in headers.items()}
        for attr, header in (
            ("last_api_credits_used", "api-credits-used"),
            ("last_api_credits_left", "api-credits-left"),
        ):
            raw = lowered.get(header)
            if raw is None:
                continue
            try:
                setattr(self, attr, int(str(raw).strip()))
            except (TypeError, ValueError):
                continue
