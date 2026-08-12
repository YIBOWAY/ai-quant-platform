"""Explicit opt-in backup chain for daily ETF bars (disaster recovery).

Futu remains the primary market-data lane. This module never falls back
silently: callers must pass a non-empty ``backup_providers`` chain, and every
served response carries honest ``provider``/``source`` provenance plus an
explicit ``fallbacks`` list recording why each earlier lane was skipped.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from quant_system.config.settings import Settings
from quant_system.data.equity_bar_cache import EquityBarCache
from quant_system.data.price_history import (
    HistoricalPriceReadError,
    HistoricalPriceSnapshot,
    _invalid_request,
    _normalize_request_symbols,
    _parse_window,
    read_historical_prices,
)
from quant_system.data.providers.tiingo import TiingoEODProvider, TiingoProviderError
from quant_system.data.providers.twelvedata import (
    TwelveDataDailyProvider,
    TwelveDataProviderError,
)

# Canonical adjustment labels per backup lane. Cache rows are provider-tagged
# (the EquityBarCache primary key includes provider), so same-symbol futu and
# backup rows can never contaminate each other.
BACKUP_PROVIDER_ADJUSTMENTS: dict[str, str] = {
    "twelvedata": "splits",
    "tiingo": "adjusted",
}
SUPPORTED_BACKUP_PROVIDERS: tuple[str, ...] = tuple(BACKUP_PROVIDER_ADJUSTMENTS)

BackupProviderBuilder = Callable[[Settings, str], Any]

DEFAULT_LOOKBACK_CALENDAR_DAYS = 419


@dataclass(frozen=True)
class BackupChainResult:
    """A served snapshot plus the explicit degradation trail."""

    snapshot: HistoricalPriceSnapshot
    fallbacks: list[dict[str, str]] = field(default_factory=list)

    @property
    def served_by(self) -> str:
        return self.snapshot.provider

    def to_dict(self) -> dict[str, Any]:
        payload = self.snapshot.to_dict()
        payload["served_by"] = self.served_by
        payload["fallbacks"] = list(self.fallbacks)
        return payload


def default_backup_window(
    *,
    now: datetime | None = None,
    lookback_calendar_days: int = DEFAULT_LOOKBACK_CALENDAR_DAYS,
) -> tuple[str, str]:
    """Default (start, end) window: through the last completed US session."""
    clock = now or datetime.now(tz=UTC)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=UTC)
    # EOD lanes: latest available bar is the prior US session. During the
    # weekend this walks back to Friday.
    end_day = clock.date() - timedelta(days=1)
    while end_day.weekday() >= 5:
        end_day -= timedelta(days=1)
    start_day = end_day - timedelta(days=lookback_calendar_days)
    return start_day.isoformat(), end_day.isoformat()


def build_backup_provider(settings: Settings, name: str) -> Any:
    """Build an explicit backup provider from env-configured keys only."""
    normalized = name.lower().strip()
    if normalized == "twelvedata":
        api_key = settings.api_keys.twelvedata_api_key
        if api_key is None or not api_key.get_secret_value().strip():
            raise HistoricalPriceReadError(
                code="historical_prices_backup_unavailable",
                message="QS_TWELVEDATA_API_KEY is not configured",
                provider="twelvedata",
                provider_code="missing_api_key",
            )
        return TwelveDataDailyProvider(api_key=api_key)
    if normalized == "tiingo":
        token = settings.api_keys.tiingo_api_token
        if token is None or not token.get_secret_value().strip():
            raise HistoricalPriceReadError(
                code="historical_prices_backup_unavailable",
                message="QS_TIINGO_API_TOKEN is not configured",
                provider="tiingo",
                provider_code="missing_api_key",
            )
        return TiingoEODProvider(api_token=token, strict_symbols=True)
    raise _invalid_request(
        f"unsupported backup provider: {name} "
        f"(supported: {', '.join(SUPPORTED_BACKUP_PROVIDERS)})"
    )


def read_daily_bars_with_backup(
    *,
    settings: Settings,
    symbols: list[str],
    start: str,
    end: str,
    backup_providers: tuple[str, ...] | list[str],
    provider_builder: BackupProviderBuilder = build_backup_provider,
    cache: EquityBarCache | None = None,
    primary_reader: Callable[..., HistoricalPriceSnapshot] = read_historical_prices,
    as_of: pd.Timestamp | None = None,
) -> BackupChainResult:
    """Read daily bars from Futu, falling back through an explicit backup chain.

    The Futu primary read is identical to ``read_historical_prices`` — default
    platform behavior is unchanged. Backups are tried strictly in the given
    order, only after the primary fails, and each failure is recorded in the
    result's ``fallbacks``. Every lane fails closed: if no lane serves, a
    ``historical_prices_backup_chain_exhausted`` error is raised.

    ``as_of`` pins the cache-expiry clock (tests/replays); production callers
    leave it unset.
    """
    if not backup_providers:
        raise _invalid_request(
            "backup reads require an explicit non-empty backup provider chain"
        )
    chain: list[str] = []
    for name in backup_providers:
        normalized = str(name).lower().strip()
        if normalized not in BACKUP_PROVIDER_ADJUSTMENTS:
            raise _invalid_request(
                f"unsupported backup provider: {name} "
                f"(supported: {', '.join(SUPPORTED_BACKUP_PROVIDERS)})"
            )
        if normalized in chain:
            raise _invalid_request(f"duplicate backup provider: {normalized}")
        chain.append(normalized)

    normalized_symbols = _normalize_request_symbols(symbols)
    start_date, end_date = _parse_window(start, end)

    fallbacks: list[dict[str, str]] = []

    try:
        snapshot = primary_reader(
            settings=settings,
            symbols=normalized_symbols,
            start=start,
            end=end,
            provider="futu",
            interval="1d",
            adjustment="qfq",
            cache=cache,
        )
        return BackupChainResult(snapshot=snapshot, fallbacks=fallbacks)
    except HistoricalPriceReadError as exc:
        if exc.code == "historical_prices_invalid_request":
            # Caller bug (bad symbols/window) must never be masked by backups.
            raise
        fallbacks.append(
            {
                "provider": exc.provider,
                "code": exc.provider_code or exc.code,
                "message": exc.message,
            }
        )

    for name in chain:
        adjustment = BACKUP_PROVIDER_ADJUSTMENTS[name]
        served = _read_backup_lane(
            settings=settings,
            name=name,
            adjustment=adjustment,
            symbols=normalized_symbols,
            start=start,
            end=end,
            start_date=start_date,
            end_date=end_date,
            provider_builder=provider_builder,
            cache=cache,
            fallbacks=fallbacks,
            as_of=as_of,
        )
        if served is not None:
            return BackupChainResult(snapshot=served, fallbacks=fallbacks)

    reasons = "; ".join(
        f"{item['provider']}: {item['code']}" for item in fallbacks
    )
    raise HistoricalPriceReadError(
        code="historical_prices_backup_chain_exhausted",
        message=f"no provider in the backup chain could serve daily bars ({reasons})",
        provider="backup_chain",
    )


def _read_backup_lane(
    *,
    settings: Settings,
    name: str,
    adjustment: str,
    symbols: list[str],
    start: str,
    end: str,
    start_date: date,
    end_date: date,
    provider_builder: BackupProviderBuilder,
    cache: EquityBarCache | None,
    fallbacks: list[dict[str, str]],
    as_of: pd.Timestamp | None = None,
) -> HistoricalPriceSnapshot | None:
    if cache is not None:
        try:
            cached_frame = cache.read(
                provider=name,
                symbols=symbols,
                interval="1d",
                adjustment=adjustment,
                start=start,
                end=end,
                as_of=as_of,
            )
        except Exception:  # noqa: BLE001 - a broken optional cache must not block a live lane
            cached_frame = None
        if cached_frame is not None:
            try:
                return _materialize_backup_snapshot(
                    cached_frame,
                    symbols=symbols,
                    start=start,
                    end=end,
                    start_date=start_date,
                    end_date=end_date,
                    expected_provider=name,
                    expected_adjustment=adjustment,
                    source=f"{name}_cache",
                )
            except HistoricalPriceReadError as exc:
                fallbacks.append(
                    {
                        "provider": name,
                        "code": exc.provider_code or exc.code,
                        "message": f"cached {name} rows failed validation: {exc.message}",
                    }
                )

    try:
        provider = provider_builder(settings, name)
    except HistoricalPriceReadError as exc:
        fallbacks.append(
            {
                "provider": name,
                "code": exc.provider_code or exc.code,
                "message": exc.message,
            }
        )
        return None

    try:
        frame = provider.fetch_ohlcv(symbols, start=start, end=end, interval="1d")
    except (TwelveDataProviderError, TiingoProviderError) as exc:
        fallbacks.append(
            {"provider": name, "code": exc.code, "message": exc.message}
        )
        return None
    except Exception as exc:  # noqa: BLE001 - record honestly, try the next lane
        fallbacks.append(
            {
                "provider": name,
                "code": type(exc).__name__,
                "message": f"{name} daily bar read failed: {type(exc).__name__}",
            }
        )
        return None

    try:
        snapshot = _materialize_backup_snapshot(
            frame,
            symbols=symbols,
            start=start,
            end=end,
            start_date=start_date,
            end_date=end_date,
            expected_provider=name,
            expected_adjustment=adjustment,
            source=name,
        )
    except HistoricalPriceReadError as exc:
        fallbacks.append(
            {
                "provider": name,
                "code": exc.provider_code or exc.code,
                "message": exc.message,
            }
        )
        return None

    if cache is not None:
        with suppress(Exception):  # optional cache failure must not replace the live lane
            cache.write(
                frame,
                provider=name,
                symbols=symbols,
                interval="1d",
                adjustment=adjustment,
                start=start,
                end=end,
            )
    return snapshot


def _materialize_backup_snapshot(
    frame: Any,
    *,
    symbols: list[str],
    start: str,
    end: str,
    start_date: date,
    end_date: date,
    expected_provider: str,
    expected_adjustment: str,
    source: str,
) -> HistoricalPriceSnapshot:
    """Validate a backup frame with the same strictness as the Futu lane."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise _contract_invalid(expected_provider, "backup provider returned no rows")
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
            expected_provider,
            f"backup price frame missing fields: {', '.join(missing)}",
        )

    normalized = frame.loc[:, sorted(required)].copy()
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper().str.strip()
    if set(normalized["symbol"]) != set(symbols):
        raise _contract_invalid(
            expected_provider, "backup price symbols do not match the request"
        )
    if set(normalized["provider"].astype(str).str.lower()) != {expected_provider}:
        raise _contract_invalid(
            expected_provider,
            f"backup price provenance is not {expected_provider}",
        )
    if set(normalized["interval"].astype(str)) != {"1d"}:
        raise _contract_invalid(expected_provider, "backup price interval is not 1d")
    if set(normalized["price_adjustment"].astype(str).str.lower()) != {expected_adjustment}:
        raise _contract_invalid(
            expected_provider,
            f"backup price adjustment is not uniformly {expected_adjustment}",
        )
    try:
        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"], utc=True, errors="raise"
        )
        normalized["knowledge_ts"] = pd.to_datetime(
            normalized["knowledge_ts"], utc=True, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise _contract_invalid(
            expected_provider, "backup price timestamps are invalid"
        ) from exc
    if normalized["timestamp"].isna().any() or normalized["knowledge_ts"].isna().any():
        raise _contract_invalid(
            expected_provider, "backup price timestamps must not be null"
        )
    normalized["date"] = normalized["timestamp"].dt.date
    if normalized.duplicated(subset=["symbol", "date"]).any():
        raise _contract_invalid(
            expected_provider, "backup prices contain duplicate symbol-date rows"
        )
    if any(day < start_date or day > end_date for day in normalized["date"]):
        raise _contract_invalid(
            expected_provider, "backup prices fall outside the requested window"
        )

    closes = pd.to_numeric(normalized["close"], errors="coerce")
    if any(not math.isfinite(float(value)) or float(value) <= 0 for value in closes):
        raise _contract_invalid(
            expected_provider, "backup price closes must be finite and positive"
        )
    normalized["close"] = closes.astype(float)
    normalized = normalized.sort_values(["symbol", "date"], ignore_index=True)

    series: list[dict[str, Any]] = []
    for symbol in symbols:
        rows = normalized[normalized["symbol"] == symbol]
        if rows.empty:
            raise _contract_invalid(
                expected_provider, f"backup prices are missing symbol {symbol}"
            )
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
        provider=expected_provider,
        source=source,
        interval="1d",
        adjustment=expected_adjustment,
        start=start,
        end=end,
        fetched_at=fetched_at,
        symbols=list(symbols),
        series=series,
    )


def _contract_invalid(provider: str, message: str) -> HistoricalPriceReadError:
    return HistoricalPriceReadError(
        code="historical_prices_contract_invalid",
        message=message,
        provider=provider,
        provider_code="contract_invalid",
    )
