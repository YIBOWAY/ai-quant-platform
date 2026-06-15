from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite

import pandas as pd
from pydantic import BaseModel

from quant_system.config.settings import Settings, load_settings
from quant_system.data.provider_factory import build_ohlcv_provider


class PricedQuote(BaseModel):
    symbol: str
    price: float
    price_kind: str  # futu_snapshot | last_close
    as_of: str
    source: str  # provider that supplied the price


class HistoricalPriceRange(BaseModel):
    symbol: str
    low: float
    high: float
    close: float
    price_kind: str = "historical_range"
    as_of: str
    source: str


class PriceUnavailableError(RuntimeError):
    """Raised when no price (snapshot or last close) can be obtained."""


class PaperPriceSource:
    """Read-only price source for the interactive paper account.

    Resolution order for a "buy/sell at current price" request:

    1. Futu real-time market snapshot (``fetch_market_snapshots``) when OpenD
       is reachable.
    2. Fallback to the most recent real historical close from the local OHLCV
       cache or Tiingo.

    It is STRICTLY read-only: it never unlocks an account or submits an order.
    The resulting ``price_kind`` is carried all the way to the ledger and the
    UI, so the user always knows whether a fill used a live snapshot or a
    historical close. Synthetic sample data is never eligible for account
    orders.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def get_price(self, symbol: str, *, lookback_days: int = 10) -> PricedQuote:
        normalized = symbol.upper().strip()
        if not normalized:
            raise PriceUnavailableError("symbol must not be empty")

        snapshot = self._try_futu_snapshot(normalized)
        if snapshot is not None:
            return snapshot

        last_close = self._try_last_close(normalized, lookback_days=lookback_days)
        if last_close is not None:
            return last_close

        raise PriceUnavailableError(
            f"no price available for {normalized}: Futu snapshot unreachable and "
            "no recent real historical close found"
        )

    def get_prices(self, symbols: list[str], *, lookback_days: int = 10) -> dict[str, PricedQuote]:
        return {
            symbol.upper().strip(): self.get_price(symbol, lookback_days=lookback_days)
            for symbol in symbols
            if symbol.strip()
        }

    def get_price_range(self, symbol: str, *, start: str, end: str) -> HistoricalPriceRange:
        normalized = symbol.upper().strip()
        if not normalized:
            raise PriceUnavailableError("symbol must not be empty")

        local = self._try_local_range(normalized, start=start, end=end)
        if local is not None:
            return local

        tiingo = self._try_tiingo_range(normalized, start=start, end=end)
        if tiingo is not None:
            return tiingo

        raise PriceUnavailableError(
            f"no historical price range available for {normalized}: "
            "no real local or Tiingo OHLCV data found"
        )

    # --- resolution steps -------------------------------------------------
    def _try_futu_snapshot(self, symbol: str) -> PricedQuote | None:
        if not getattr(self.settings.futu, "enabled", False):
            return None
        try:
            from quant_system.data.providers.futu import (
                FutuMarketDataProvider,
                FutuProviderError,
            )
        except Exception:  # noqa: BLE001 - SDK optional / import guard
            return None
        try:
            futu_settings = self.settings.futu
            provider = FutuMarketDataProvider(
                host=futu_settings.host,
                port=futu_settings.port,
                request_timeout_seconds=futu_settings.request_timeout_seconds,
            )
            _plain, futu_symbol = FutuMarketDataProvider.normalize_symbol(symbol)
            frame = provider.fetch_market_snapshots([futu_symbol])
            if frame.empty or "last" not in frame.columns:
                return None
            price = frame.iloc[0].get("last")
            if price is None or float(price) <= 0:
                return None
            as_of = frame.iloc[0].get("update_time")
            return PricedQuote(
                symbol=symbol,
                price=float(price),
                price_kind="futu_snapshot",
                as_of=str(as_of) if as_of else datetime.now(UTC).isoformat(),
                source="futu",
            )
        except FutuProviderError:
            return None
        except Exception:  # noqa: BLE001 - any OpenD failure -> fall back
            return None

    def _try_last_close(self, symbol: str, *, lookback_days: int) -> PricedQuote | None:
        local = self._try_local_close(symbol, lookback_days=lookback_days)
        if local is not None:
            return local

        try:
            # Never substitute synthetic sample data for an account fill. If
            # neither the local real-data cache nor Tiingo is available, the
            # order must fail before touching the account.
            token = self.settings.api_keys.tiingo_api_token
            token_value = token.get_secret_value().strip() if token else ""
            if not token_value:
                return None
            provider, source = build_ohlcv_provider(self.settings, requested="tiingo")
            if source.lower().startswith("sample"):
                return None
            end = datetime.now(UTC).date()
            start = end.fromordinal(end.toordinal() - max(lookback_days, 1) * 3)
            ohlcv = provider.fetch_ohlcv(
                [symbol],
                start=start.isoformat(),
                end=end.isoformat(),
            )
            if ohlcv is None or ohlcv.empty:
                return None
            rows = ohlcv[ohlcv["symbol"].astype(str).str.upper() == symbol]
            if rows.empty:
                return None
            rows = rows.sort_values("timestamp")
            last = rows.iloc[-1]
            price = float(last.get("close"))
            if price <= 0:
                return None
            return PricedQuote(
                symbol=symbol,
                price=price,
                price_kind="last_close",
                as_of=str(last.get("timestamp")),
                source=source,
            )
        except Exception:  # noqa: BLE001 - no price available
            return None

    def _try_local_close(self, symbol: str, *, lookback_days: int) -> PricedQuote | None:
        path = self.settings.data.parquet_dir / "ohlcv.parquet"
        if not path.exists():
            return None
        try:
            frame = pd.read_parquet(path)
            required = {"symbol", "timestamp", "close", "provider"}
            if not required.issubset(frame.columns):
                return None
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
            rows = frame[
                (frame["symbol"].astype(str).str.upper() == symbol)
                & ~frame["provider"].astype(str).str.contains("sample", case=False, na=True)
            ].copy()
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(
                days=max(lookback_days, 1) * 3
            )
            rows = rows[rows["timestamp"] >= cutoff].sort_values("timestamp")
            if rows.empty:
                return None
            last = rows.iloc[-1]
            price = float(last["close"])
            if price <= 0:
                return None
            provider = str(last["provider"])
            return PricedQuote(
                symbol=symbol,
                price=price,
                price_kind="last_close",
                as_of=str(last["timestamp"]),
                source=f"local:{provider}",
            )
        except Exception:  # noqa: BLE001 - malformed or unreadable local cache
            return None

    def _try_local_range(
        self,
        symbol: str,
        *,
        start: str,
        end: str,
    ) -> HistoricalPriceRange | None:
        path = self.settings.data.parquet_dir / "ohlcv.parquet"
        if not path.exists():
            return None
        try:
            frame = pd.read_parquet(path)
            required = {"symbol", "timestamp", "low", "high", "close", "provider"}
            if not required.issubset(frame.columns):
                return None
            return self._range_from_ohlcv(
                frame,
                symbol,
                start=start,
                end=end,
                source_prefix="local",
            )
        except Exception:  # noqa: BLE001 - malformed or unreadable local cache
            return None

    def _try_tiingo_range(
        self,
        symbol: str,
        *,
        start: str,
        end: str,
    ) -> HistoricalPriceRange | None:
        try:
            token = self.settings.api_keys.tiingo_api_token
            token_value = token.get_secret_value().strip() if token else ""
            if not token_value:
                return None
            provider, source = build_ohlcv_provider(self.settings, requested="tiingo")
            if source.lower().startswith("sample"):
                return None
            frame = provider.fetch_ohlcv([symbol], start=start, end=end)
            return self._range_from_ohlcv(
                frame,
                symbol,
                start=start,
                end=end,
                source=source,
            )
        except Exception:  # noqa: BLE001 - no historical range available
            return None

    def _range_from_ohlcv(
        self,
        frame: pd.DataFrame,
        symbol: str,
        *,
        start: str,
        end: str,
        source: str | None = None,
        source_prefix: str | None = None,
    ) -> HistoricalPriceRange | None:
        required = {"symbol", "timestamp", "low", "high", "close"}
        if frame is None or frame.empty or not required.issubset(frame.columns):
            return None
        rows = frame.copy()
        rows["timestamp"] = pd.to_datetime(rows["timestamp"], utc=True, errors="coerce")
        for column in ("low", "high", "close"):
            rows[column] = pd.to_numeric(rows[column], errors="coerce")
        start_ts = self._utc_timestamp(start)
        end_exclusive = self._utc_timestamp(end) + pd.Timedelta(days=1)
        rows = rows[
            (rows["symbol"].astype(str).str.upper() == symbol)
            & (rows["timestamp"] >= start_ts)
            & (rows["timestamp"] < end_exclusive)
        ].copy()
        if "provider" in rows.columns:
            rows = rows[
                ~rows["provider"].astype(str).str.contains("sample", case=False, na=True)
            ]
        rows = rows.dropna(subset=["timestamp", "low", "high", "close"])
        rows = rows[(rows["low"] > 0) & (rows["high"] > 0) & (rows["close"] > 0)]
        rows = rows[rows["high"] >= rows["low"]].sort_values("timestamp")
        if rows.empty:
            return None
        low = float(rows["low"].min())
        high = float(rows["high"].max())
        close = float(rows.iloc[-1]["close"])
        if not (isfinite(low) and isfinite(high) and isfinite(close)):
            return None
        range_source = source or self._local_range_source(rows, source_prefix=source_prefix)
        return HistoricalPriceRange(
            symbol=symbol,
            low=low,
            high=high,
            close=close,
            as_of=str(rows.iloc[-1]["timestamp"]),
            source=range_source,
        )

    @staticmethod
    def _utc_timestamp(value: str) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("UTC")
        return timestamp.tz_convert("UTC")

    @staticmethod
    def _local_range_source(
        rows: pd.DataFrame,
        *,
        source_prefix: str | None,
    ) -> str:
        if "provider" not in rows.columns:
            return source_prefix or "local"
        providers = sorted({str(provider) for provider in rows["provider"].dropna()})
        provider = providers[0] if len(providers) == 1 else "mixed"
        return f"{source_prefix}:{provider}" if source_prefix else provider
