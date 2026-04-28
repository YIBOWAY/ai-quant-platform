from __future__ import annotations

import numpy as np
import pandas as pd

from quant_system.factors.base import BaseFactor


class MomentumFactor(BaseFactor):
    factor_id = "momentum"
    factor_name = "Momentum"
    default_lookback = 20
    direction = "higher_is_better"
    description = "Close-to-close momentum over a trailing window."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        return frame.groupby("symbol", sort=False)["close"].pct_change(self.lookback)


class VolatilityFactor(BaseFactor):
    factor_id = "volatility"
    factor_name = "Volatility"
    default_lookback = 20
    direction = "lower_is_better"
    description = "Trailing realized volatility from close-to-close returns."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        returns = frame.groupby("symbol", sort=False)["close"].pct_change()
        return returns.groupby(frame["symbol"], sort=False).transform(
            lambda series: series.rolling(self.lookback, min_periods=self.lookback).std()
        )


class LiquidityFactor(BaseFactor):
    factor_id = "liquidity"
    factor_name = "Liquidity"
    default_lookback = 20
    direction = "higher_is_better"
    description = "Log trailing average dollar volume."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        dollar_volume = frame["close"] * frame["volume"]
        rolling_mean = dollar_volume.groupby(frame["symbol"], sort=False).transform(
            lambda series: series.rolling(self.lookback, min_periods=self.lookback).mean()
        )
        return pd.Series(np.log1p(rolling_mean), index=frame.index)


class RSIFactor(BaseFactor):
    factor_id = "rsi"
    factor_name = "Relative Strength Index"
    default_lookback = 14
    direction = "lower_is_better"
    description = "Trailing RSI oscillator; lower values represent stronger oversold pressure."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        delta = frame.groupby("symbol", sort=False)["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.groupby(frame["symbol"], sort=False).transform(
            lambda series: series.rolling(self.lookback, min_periods=self.lookback).mean()
        )
        avg_loss = loss.groupby(frame["symbol"], sort=False).transform(
            lambda series: series.rolling(self.lookback, min_periods=self.lookback).mean()
        )
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        # 边界处理：纯涨窗 -> 100；纯跌窗 -> 0；完全平盘 -> 50
        rsi = rsi.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
        rsi = rsi.mask((avg_gain == 0) & (avg_loss > 0), 0.0)
        rsi = rsi.mask((avg_gain == 0) & (avg_loss == 0), 50.0)
        return pd.Series(rsi, index=frame.index)


class MACDFactor(BaseFactor):
    factor_id = "macd"
    factor_name = "MACD Histogram"
    default_lookback = 12
    direction = "higher_is_better"
    description = (
        "MACD histogram from trailing exponential moving averages. 使用 "
        "(fast=L, slow=2L, signal=L) 简化参数化；经典 (12,26,9) 不能精确复现。"
    )

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        fast_span = max(2, self.lookback)
        slow_span = max(fast_span + 1, self.lookback * 2)
        signal_span = max(2, self.lookback)
        close = frame["close"]
        fast_ema = close.groupby(frame["symbol"], sort=False).transform(
            lambda series: series.ewm(
                span=fast_span,
                adjust=False,
                min_periods=fast_span,
            ).mean()
        )
        slow_ema = close.groupby(frame["symbol"], sort=False).transform(
            lambda series: series.ewm(
                span=slow_span,
                adjust=False,
                min_periods=slow_span,
            ).mean()
        )
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.groupby(frame["symbol"], sort=False).transform(
            lambda series: series.ewm(
                span=signal_span,
                adjust=False,
                min_periods=signal_span,
            ).mean()
        )
        return pd.Series(macd_line - signal_line, index=frame.index)
