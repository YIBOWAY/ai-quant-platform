from __future__ import annotations

import pandas as pd
from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.common import dataframe_records
from quant_system.backtest.metrics import calculate_performance_metrics
from quant_system.data.provider_factory import build_ohlcv_provider
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
    active_provider, source = build_ohlcv_provider(settings, requested=provider)
    try:
        ohlcv = active_provider.fetch_ohlcv([normalized_symbol], start=start, end=end)
    except Exception as exc:
        ohlcv = SampleOHLCVProvider().fetch_ohlcv([normalized_symbol], start=start, end=end)
        source = f"sample ({source} failed: {exc.__class__.__name__})"
    sorted_ohlcv = ohlcv.sort_values("timestamp")
    prices = pd.to_numeric(sorted_ohlcv["close"], errors="coerce")
    equity = prices / float(prices.iloc[0])
    curve = pd.DataFrame({"timestamp": sorted_ohlcv["timestamp"], "equity": equity})
    metrics = calculate_performance_metrics(
        curve,
        pd.DataFrame(),
        initial_cash=1.0,
    )
    return {
        "symbol": normalized_symbol,
        "source": source,
        "equity_curve": dataframe_records(curve),
        "metrics": metrics.model_dump(),
    }
