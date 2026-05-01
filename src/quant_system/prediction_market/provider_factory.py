from __future__ import annotations

from quant_system.config.settings import Settings
from quant_system.prediction_market.data.base import PredictionMarketDataProvider
from quant_system.prediction_market.data.polymarket_readonly import PolymarketReadOnlyProvider
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider


def build_prediction_market_provider(
    settings: Settings,
    *,
    requested: str | None = None,
) -> tuple[PredictionMarketDataProvider, str]:
    name = (requested or settings.prediction_market.provider).lower().strip()
    if name == "sample":
        return SamplePredictionMarketProvider(), "sample"
    if name == "polymarket":
        config = settings.prediction_market
        return (
            PolymarketReadOnlyProvider(
                gamma_base_url=config.polymarket_gamma_base_url,
                clob_base_url=config.polymarket_clob_base_url,
                timeout_seconds=config.polymarket_request_timeout_seconds,
                max_retries=config.polymarket_max_retries,
                rate_limit_per_second=config.polymarket_rate_limit_per_second,
            ),
            "polymarket",
        )
    raise ValueError(f"unknown prediction market provider {name!r}")
