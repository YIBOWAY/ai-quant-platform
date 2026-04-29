from __future__ import annotations

from quant_system.config.settings import Settings
from quant_system.data.providers.base import HistoricalDataProvider
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

    if name == "tiingo" and token_value:
        return TiingoEODProvider(api_token=token), "tiingo"
    if name == "tiingo" and not token_value:
        return SampleOHLCVProvider(), "sample (tiingo: missing token)"
    return SampleOHLCVProvider(), "sample"
