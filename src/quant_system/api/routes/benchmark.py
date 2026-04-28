from __future__ import annotations

import pandas as pd
from fastapi import APIRouter

from quant_system.api.schemas.common import dataframe_records
from quant_system.backtest.metrics import calculate_performance_metrics
from quant_system.data.providers.sample import SampleOHLCVProvider

router = APIRouter()


@router.get("/benchmark")
def benchmark(symbol: str = "SPY", start: str = "", end: str = "") -> dict:
    normalized_symbol = symbol.upper().strip()
    ohlcv = SampleOHLCVProvider().fetch_ohlcv([normalized_symbol], start=start, end=end)
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
        "equity_curve": dataframe_records(curve),
        "metrics": metrics.model_dump(),
    }
