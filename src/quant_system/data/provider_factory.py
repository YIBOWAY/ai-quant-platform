from __future__ import annotations

from quant_system.config.settings import Settings
from quant_system.data.providers.base import HistoricalDataProvider
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.providers.tiingo import TiingoEODProvider


def build_ohlcv_provider(
    settings: Settings,
    *,
    requested: str | None = None,
) -> tuple[HistoricalDataProvider, str]:
    """Pick a working OHLCV provider without exposing credentials."""

    name = (requested or settings.data.default_data_provider).lower().strip()
    token = settings.api_keys.tiingo_api_token
    token_value = token.get_secret_value().strip() if token else ""

    # Smart default: when the configured default is "sample" but a Tiingo
    # token is actually available, prefer Tiingo so the UI does not silently
    # show synthetic data. Futu is NOT auto-selected because it depends on a
    # locally running OpenD process. An explicit `requested` value is always
    # respected.
    if requested is None and name == "sample" and token_value:
        return TiingoEODProvider(api_token=token), "tiingo (auto-selected)"

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
        return SampleOHLCVProvider(), "sample (futu: disabled)"
    if name == "tiingo" and token_value:
        return TiingoEODProvider(api_token=token), "tiingo"
    if name == "tiingo" and not token_value:
        return SampleOHLCVProvider(), "sample (tiingo: missing token)"
    return SampleOHLCVProvider(), "sample"
