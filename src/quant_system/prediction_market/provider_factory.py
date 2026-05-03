from __future__ import annotations

from quant_system.config.settings import Settings
from quant_system.prediction_market.data.base import PredictionMarketDataProvider
from quant_system.prediction_market.data.polymarket_readonly import PolymarketReadOnlyProvider
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider


def build_prediction_market_provider(
    settings: Settings,
    *,
    requested: str | None = None,
    cache_mode: str | None = None,
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
                data_api_base_url=config.polymarket_data_api_base_url,
                timeout_seconds=config.polymarket_request_timeout_seconds,
                max_retries=config.polymarket_max_retries,
                rate_limit_per_second=config.polymarket_rate_limit_per_second,
                cache_dir=config.polymarket_cache_dir,
                cache_ttl_seconds=config.polymarket_cache_ttl_seconds,
                cache_stale_if_error_seconds=config.polymarket_cache_stale_if_error_seconds,
                cache_mode=(cache_mode or "prefer_cache"),
                user_agent=config.polymarket_user_agent,
            ),
            "polymarket",
        )
    raise ValueError(f"unknown prediction market provider {name!r}")
