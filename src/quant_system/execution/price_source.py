from __future__ import annotations

from datetime import UTC, datetime

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
