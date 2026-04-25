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
