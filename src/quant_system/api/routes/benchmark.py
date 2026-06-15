from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep
from quant_system.api.errors import provider_unavailable_400
from quant_system.api.schemas.common import dataframe_records
from quant_system.backtest.benchmark import (
    build_benchmark_curve,
    calculate_benchmark_metrics,
)
from quant_system.data.provider_factory import (
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.data.providers.sample import SampleOHLCVProvider

router = APIRouter()


@router.get("/benchmark")
def benchmark(
    settings: SettingsDep,
    symbol: str = "SPY",
    start: str = "",
    end: str = "",
    provider: str | None = None,
) -> dict:
    normalized_symbol = symbol.upper().strip()
    try:
        active_provider, source = build_ohlcv_provider(settings, requested=provider)
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc
    try:
        ohlcv = active_provider.fetch_ohlcv([normalized_symbol], start=start, end=end)
    except Exception as exc:
        if provider is not None:
            raise provider_unavailable_400(
                DataProviderUnavailableError(provider, exc.__class__.__name__)
            ) from exc
        ohlcv = SampleOHLCVProvider().fetch_ohlcv([normalized_symbol], start=start, end=end)
        source = f"sample ({source} failed: {exc.__class__.__name__})"
    curve = build_benchmark_curve(ohlcv, symbol=normalized_symbol)
    metrics = calculate_benchmark_metrics(curve)
    return {
        "symbol": normalized_symbol,
        "source": source,
        "equity_curve": dataframe_records(curve),
        "metrics": metrics.model_dump(),
    }
