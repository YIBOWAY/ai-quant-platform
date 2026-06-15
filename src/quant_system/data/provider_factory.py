from __future__ import annotations

import pandas as pd

from quant_system.config.settings import Settings
from quant_system.data.providers.base import HistoricalDataProvider
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.providers.tiingo import TiingoEODProvider
from quant_system.data.storage import LocalDataStorage


class DataProviderUnavailableError(RuntimeError):
    def __init__(self, provider: str, reason: str) -> None:
        self.provider = provider
        self.reason = reason
        super().__init__(f"{provider} provider unavailable: {reason}")


class CachedOHLCVProvider:
    def __init__(
        self,
        *,
        upstream: HistoricalDataProvider,
        storage: LocalDataStorage,
    ) -> None:
        self.upstream = upstream
        self.storage = storage
        self.provider_name = upstream.provider_name

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if interval != "1d" or not self.storage.parquet_path.exists():
            return self._fetch_and_store(symbols, start=start, end=end, interval=interval)

        try:
            cached = self.storage.load_ohlcv(symbols, start=start, end=end)
        except FileNotFoundError:
            return self._fetch_and_store(symbols, start=start, end=end, interval=interval)

        if self._covers_request(cached, symbols=symbols, start=start, end=end, interval=interval):
            return cached
        return self._fetch_and_store(symbols, start=start, end=end, interval=interval)

    def _fetch_and_store(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str,
    ) -> pd.DataFrame:
        frame = self.upstream.fetch_ohlcv(symbols, start=start, end=end, interval=interval)
        self.storage.save_ohlcv(frame)
        return frame

    def _covers_request(
        self,
        cached: pd.DataFrame,
        *,
        symbols: list[str],
        start: str,
        end: str,
        interval: str,
    ) -> bool:
        if cached.empty:
            return False
        normalized_symbols = {symbol.upper() for symbol in symbols}
        cached_symbols = set(cached["symbol"].astype(str).str.upper())
        if not normalized_symbols.issubset(cached_symbols):
            return False
        if "provider" in cached.columns:
            providers = set(cached["provider"].astype(str))
            if providers != {self.provider_name}:
                return False
        if "interval" in cached.columns:
            intervals = set(cached["interval"].astype(str))
            if intervals != {interval}:
                return False
        timestamps = pd.to_datetime(cached["timestamp"], utc=True)
        return (
            timestamps.min() <= pd.Timestamp(start, tz="UTC")
            and timestamps.max() >= pd.Timestamp(end, tz="UTC")
        )


def build_ohlcv_provider(
    settings: Settings,
    *,
    requested: str | None = None,
) -> tuple[HistoricalDataProvider, str]:
    """Pick a working OHLCV provider without exposing credentials."""

    name = (requested or settings.data.default_data_provider).lower().strip()
    if requested is not None and name not in {"sample", "futu", "tiingo"}:
        raise DataProviderUnavailableError(name, "unsupported provider")
    token = settings.api_keys.tiingo_api_token
    token_value = token.get_secret_value().strip() if token else ""

    # Smart default: when the configured default is "sample" but a Tiingo
    # token is actually available, prefer Tiingo so the UI does not silently
    # show synthetic data. Futu is NOT auto-selected because it depends on a
    # locally running OpenD process. An explicit `requested` value is always
    # respected.
    if requested is None and name == "sample" and token_value:
        return _cached_provider(
            TiingoEODProvider(api_token=token),
            settings=settings,
        ), "tiingo (auto-selected)"

    if name == "futu":
        if settings.futu.enabled:
            return (
                FutuMarketDataProvider(
                    host=settings.futu.host,
                    port=settings.futu.port,
                    request_timeout_seconds=settings.futu.request_timeout_seconds,
                    option_quotes_cache_path=(
                        settings.futu.cache_dir / "options_cache.duckdb"
                        if settings.futu.use_cache
                        else None
                    ),
                ),
                "futu",
            )
        if requested is not None:
            raise DataProviderUnavailableError("futu", "disabled")
        return SampleOHLCVProvider(), "sample (futu: disabled)"
    if name == "tiingo" and token_value:
        return _cached_provider(
            TiingoEODProvider(api_token=token),
            settings=settings,
        ), "tiingo"
    if name == "tiingo" and not token_value:
        if requested is not None:
            raise DataProviderUnavailableError("tiingo", "missing token")
        return SampleOHLCVProvider(), "sample (tiingo: missing token)"
    return SampleOHLCVProvider(), "sample"


def _cached_provider(
    upstream: HistoricalDataProvider,
    *,
    settings: Settings,
) -> CachedOHLCVProvider:
    return CachedOHLCVProvider(
        upstream=upstream,
        storage=LocalDataStorage(
            base_dir=settings.data.data_dir,
            parquet_dir=settings.data.parquet_dir,
            duckdb_path=settings.data.duckdb_path,
            reports_dir=settings.data.reports_dir,
        ),
    )
