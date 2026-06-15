from __future__ import annotations

import pandas as pd

from quant_system.backtest.metrics import PerformanceMetrics, calculate_performance_metrics


def build_benchmark_curve(ohlcv: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    normalized_symbol = symbol.upper().strip()
    if ohlcv.empty:
        return pd.DataFrame(columns=["timestamp", "equity"])

    frame = ohlcv.copy()
    if "symbol" in frame.columns:
        symbols = frame["symbol"].astype(str).str.upper().str.strip()
        frame = frame.loc[symbols == normalized_symbol]
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "equity"])

    sorted_ohlcv = frame.sort_values("timestamp")
    prices = pd.to_numeric(sorted_ohlcv["close"], errors="coerce")
    first_price = prices.dropna().iloc[0] if not prices.dropna().empty else None
    if first_price is None or float(first_price) <= 0:
        return pd.DataFrame(columns=["timestamp", "equity"])
    equity = prices / float(first_price)
    return pd.DataFrame({"timestamp": sorted_ohlcv["timestamp"], "equity": equity})


def calculate_benchmark_metrics(curve: pd.DataFrame) -> PerformanceMetrics:
    return calculate_performance_metrics(
        curve,
        pd.DataFrame(),
        initial_cash=1.0,
    )
