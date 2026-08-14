from __future__ import annotations

import math
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from quant_system.config.settings import Settings
from quant_system.data.equity_bar_cache import EquityBarCache
from quant_system.data.provider_factory import (
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError
from quant_system.data.providers.tiingo import TiingoProviderError

ProviderBuilder = Callable[..., tuple[Any, str]]
MAX_SYMBOLS = 25
MAX_CALENDAR_DAYS = 500

# Each supported daily-history lane emits exactly one adjustment label; the
# request must name it explicitly so provenance is never silently relabelled.
SUPPORTED_PROVIDERS: dict[str, str] = {
    "futu": "qfq",
    "tiingo": "adjusted",
}


class HistoricalPriceReadError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        provider: str = "futu",
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.provider = provider
        self.provider_code = provider_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "provider": self.provider,
            "provider_code": self.provider_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class HistoricalPriceSnapshot:
    provider: str
    source: str
    interval: str
    adjustment: str
    start: str
    end: str
    fetched_at: str
    symbols: list[str]
    series: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "provider": self.provider,
            "source": self.source,
            "interval": self.interval,
            "adjustment": self.adjustment,
            "start": self.start,
            "end": self.end,
            "fetched_at": self.fetched_at,
            "symbols": list(self.symbols),
            "series": self.series,
        }


def _invalid_request(message: str) -> HistoricalPriceReadError:
    return HistoricalPriceReadError(
        code="historical_prices_invalid_request",
        message=message,
    )


def _contract_invalid(message: str) -> HistoricalPriceReadError:
    return HistoricalPriceReadError(
        code="historical_prices_contract_invalid",
        message=message,
    )


def _normalize_request_symbols(
    symbols: list[str],
    *,
    allow_local_markets: bool = False,
) -> list[str]:
    if not symbols:
        raise _invalid_request("at least one --symbol is required")
    if len(symbols) > MAX_SYMBOLS:
        raise _invalid_request(f"at most {MAX_SYMBOLS} symbols may be requested")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_symbol in symbols:
        if not isinstance(raw_symbol, str):
            raise _invalid_request("symbols must be strings")
        try:
            plain_symbol, _futu_symbol = FutuMarketDataProvider.normalize_symbol(
                raw_symbol,
                allow_local_markets=allow_local_markets,
            )
        except FutuProviderError as exc:
            raise _invalid_request(exc.message) from exc
        if plain_symbol in seen:
            raise _invalid_request(f"duplicate normalized symbol: {plain_symbol}")
        seen.add(plain_symbol)
        normalized.append(plain_symbol)
    return normalized


def _parse_window(start: str, end: str) -> tuple[date, date]:
    if not isinstance(start, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) is None:
        raise _invalid_request("start/end must use strict YYYY-MM-DD dates")
    if not isinstance(end, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) is None:
        raise _invalid_request("start/end must use strict YYYY-MM-DD dates")
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except (TypeError, ValueError) as exc:
        raise _invalid_request("start/end must use strict YYYY-MM-DD dates") from exc
    if start_date > end_date:
        raise _invalid_request("start must not be after end")
    inclusive_days = (end_date - start_date).days + 1
    if inclusive_days > MAX_CALENDAR_DAYS:
        raise _invalid_request(
            f"historical price windows may not exceed {MAX_CALENDAR_DAYS} calendar days"
        )
    return start_date, end_date


def read_historical_prices(
    *,
    settings: Settings,
    symbols: list[str],
    start: str,
    end: str,
    provider: str,
    interval: str = "1d",
    adjustment: str = "qfq",
    provider_builder: ProviderBuilder = build_ohlcv_provider,
    cache: EquityBarCache | None = None,
    allow_local_markets: bool = False,
) -> HistoricalPriceSnapshot:
    """Read strict multi-symbol daily history without storage fallback.

    Futu serves the canonical QFQ lane; Tiingo is an explicit adjusted-close
    lane (split+dividend adjusted) whose provenance is recorded as-is. The
    requested ``adjustment`` must match the provider's only supported label so
    data is never silently relabelled.

    ``allow_local_markets`` is an explicit opt-in for read-only lanes that
    need whitelisted local-market codes (HK./JP..). It is off by default so
    every existing caller keeps the exact US-only contract.
    """
    expected_adjustment = SUPPORTED_PROVIDERS.get(provider)
    if expected_adjustment is None:
        raise _invalid_request(
            "historical prices require explicit provider=futu or provider=tiingo"
        )
    if interval != "1d":
        raise _invalid_request("historical prices currently require interval=1d")
    if adjustment != expected_adjustment:
        raise _invalid_request(
            f"historical prices with provider={provider} require "
            f"adjustment={expected_adjustment}"
        )
    normalized_symbols = _normalize_request_symbols(
        symbols,
        allow_local_markets=allow_local_markets,
    )
    start_date, end_date = _parse_window(start, end)

    if cache is not None:
        try:
            cached_frame = cache.read(
                provider=provider,
                symbols=normalized_symbols,
                interval="1d",
                adjustment=expected_adjustment,
                start=start,
                end=end,
            )
        except Exception:  # noqa: BLE001 - a broken optional cache must not block the live read
            cached_frame = None
        if cached_frame is not None:
            return _materialize_snapshot(
                cached_frame,
                symbols=normalized_symbols,
                start=start,
                end=end,
                start_date=start_date,
                end_date=end_date,
                source=f"{provider}_cache",
                provider=provider,
                adjustment=expected_adjustment,
            )

    try:
        active_provider, source = provider_builder(settings, requested=provider)
    except DataProviderUnavailableError as exc:
        raise HistoricalPriceReadError(
            code="historical_prices_provider_unavailable",
            message=str(exc),
            provider=provider,
            provider_code=exc.reason,
        ) from exc
    if (
        source != provider
        or getattr(active_provider, "provider_name", None) != provider
    ):
        raise _contract_invalid(
            f"explicit {provider} provider resolved to a different source"
        )
    fetch_ohlcv = active_provider.fetch_ohlcv
    if allow_local_markets:
        fetch_ohlcv = getattr(active_provider, "fetch_local_market_ohlcv", None)
        if not callable(fetch_ohlcv):
            raise _contract_invalid(
                f"explicit {provider} provider does not support local-market reads"
            )
    try:
        frame = fetch_ohlcv(
            normalized_symbols,
            start=start,
            end=end,
            interval="1d",
        )
    except (FutuProviderError, TiingoProviderError) as exc:
        raise HistoricalPriceReadError(
            code="historical_prices_provider_error",
            message=exc.message,
            provider=provider,
            provider_code=exc.code,
        ) from exc
    except Exception as exc:
        raise HistoricalPriceReadError(
            code="historical_prices_provider_error",
            message=f"{provider} historical price read failed: {type(exc).__name__}",
            provider=provider,
            provider_code=type(exc).__name__,
        ) from exc

    snapshot = _materialize_snapshot(
        frame,
        symbols=normalized_symbols,
        start=start,
        end=end,
        start_date=start_date,
        end_date=end_date,
        source=source,
        provider=provider,
        adjustment=expected_adjustment,
    )
    if cache is not None:
        with suppress(Exception):  # optional cache failure must not replace the live read
            cache.write(
                frame,
                provider=provider,
                symbols=normalized_symbols,
                interval="1d",
                adjustment=expected_adjustment,
                start=start,
                end=end,
            )
    return snapshot


def _materialize_snapshot(
    frame: Any,
    *,
    symbols: list[str],
    start: str,
    end: str,
    start_date: date,
    end_date: date,
    source: str,
    provider: str = "futu",
    adjustment: str = "qfq",
) -> HistoricalPriceSnapshot:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise _contract_invalid(f"{provider} returned no historical price rows")
    required = {
        "symbol",
        "timestamp",
        "close",
        "provider",
        "interval",
        "price_adjustment",
        "knowledge_ts",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise _contract_invalid(
            f"historical price frame missing fields: {', '.join(missing)}"
        )

    normalized = frame.loc[:, sorted(required)].copy()
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper().str.strip()
    if set(normalized["symbol"]) != set(symbols):
        raise _contract_invalid("historical price symbols do not match the request")
    if set(normalized["provider"].astype(str)) != {provider}:
        raise _contract_invalid(
            f"historical price provider provenance is not {provider}"
        )
    if set(normalized["interval"].astype(str)) != {"1d"}:
        raise _contract_invalid("historical price interval provenance is not 1d")
    if set(normalized["price_adjustment"].astype(str).str.lower()) != {adjustment}:
        raise _contract_invalid(
            f"historical price adjustment provenance is not {adjustment}"
        )
    try:
        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"], utc=True, errors="raise"
        )
        normalized["knowledge_ts"] = pd.to_datetime(
            normalized["knowledge_ts"], utc=True, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise _contract_invalid("historical price timestamps are invalid") from exc
    if normalized["timestamp"].isna().any() or normalized["knowledge_ts"].isna().any():
        raise _contract_invalid("historical price timestamps must not be null")
    normalized["date"] = normalized["timestamp"].dt.date
    if normalized.duplicated(subset=["symbol", "date"]).any():
        raise _contract_invalid("historical prices contain duplicate symbol-date rows")
    if any(day < start_date or day > end_date for day in normalized["date"]):
        raise _contract_invalid("historical prices fall outside the requested window")

    closes = pd.to_numeric(normalized["close"], errors="coerce")
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in closes):
        raise _contract_invalid("historical price closes must be finite and positive")
    normalized["close"] = closes.astype(float)
    normalized = normalized.sort_values(["symbol", "date"], ignore_index=True)

    series: list[dict[str, Any]] = []
    for symbol in symbols:
        rows = normalized[normalized["symbol"] == symbol]
        if rows.empty:
            raise _contract_invalid(f"historical prices are missing symbol {symbol}")
        records = [
            {"date": row.date.isoformat(), "close": float(row.close)}
            for row in rows.itertuples(index=False)
        ]
        series.append(
            {
                "symbol": symbol,
                "row_count": len(records),
                "first_date": records[0]["date"],
                "last_date": records[-1]["date"],
                "rows": records,
            }
        )

    fetched_at = normalized["knowledge_ts"].max().isoformat()
    return HistoricalPriceSnapshot(
        provider=provider,
        source=source,
        interval="1d",
        adjustment=adjustment,
        start=start,
        end=end,
        fetched_at=fetched_at,
        symbols=list(symbols),
        series=series,
    )
