from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

StrategyName = Literal["sell_put", "covered_call"]
VolatilityRegime = Literal["Normal", "Elevated", "Panic", "Unknown"]

REGIME_W_VIX: dict[VolatilityRegime, float] = {
    "Normal": 1.0,
    "Elevated": 0.75,
    "Panic": 0.35,
    "Unknown": 1.0,
}


@dataclass(frozen=True)
class VixRegimeSnapshot:
    volatility_regime: VolatilityRegime
    w_vix: float
    vix_density: float
    term_ratio: float | None
    vix_mean: float | None
    vix_threshold: float


def compute_vix_regime(
    daily_vix: pd.Series,
    daily_vix3m: pd.Series | None = None,
    *,
    signal_date: pd.Timestamp,
    lookback_days: int = 252,
    q: float = 0.75,
    vix_floor: float = 20.0,
    density_threshold: float = 0.25,
    elevated_ratio: float = 0.97,
    panic_ratio: float = 1.00,
    min_days: int = 10,
) -> VixRegimeSnapshot:
    vix_upto = daily_vix.loc[:signal_date].dropna()
    if vix_upto.empty:
        return VixRegimeSnapshot(
            volatility_regime="Unknown",
            w_vix=1.0,
            vix_density=0.0,
            term_ratio=None,
            vix_mean=None,
            vix_threshold=vix_floor,
        )

    window = vix_upto.iloc[-lookback_days:]
    threshold = max(vix_floor, float(window.quantile(q)))
    month_start = signal_date - pd.DateOffset(months=1)
    vix_month = vix_upto.loc[month_start:]
    if vix_month.empty:
        vix_month = vix_upto.iloc[-22:]

    density = float((vix_month > threshold).mean())
    high_time = density > density_threshold
    term_ratio = _mean_term_ratio(vix_month, daily_vix3m, signal_date, min_days=min_days)

    if term_ratio is None:
        regime: VolatilityRegime = "Elevated" if high_time else "Normal"
    elif high_time and term_ratio > panic_ratio:
        regime = "Panic"
    elif high_time or term_ratio > elevated_ratio:
        regime = "Elevated"
    else:
        regime = "Normal"

    return VixRegimeSnapshot(
        volatility_regime=regime,
        w_vix=REGIME_W_VIX[regime],
        vix_density=round(density, 3),
        term_ratio=round(term_ratio, 3) if term_ratio is not None else None,
        vix_mean=round(float(vix_month.mean()), 2),
        vix_threshold=round(threshold, 2),
    )


def seller_regime_penalty(strategy: StrategyName, regime: VolatilityRegime) -> float:
    if regime == "Panic":
        return -40.0 if strategy == "sell_put" else -15.0
    if regime == "Elevated":
        return -15.0 if strategy == "sell_put" else -5.0
    return 0.0


def _mean_term_ratio(
    vix_month: pd.Series,
    daily_vix3m: pd.Series | None,
    signal_date: pd.Timestamp,
    *,
    min_days: int,
) -> float | None:
    if daily_vix3m is None:
        return None
    vix3m_upto = daily_vix3m.loc[:signal_date].dropna()
    common = vix_month.index.intersection(vix3m_upto.index)
    if len(common) < min_days:
        return None
    ratio = (vix_month.loc[common] / vix3m_upto.loc[common]).replace(
        [float("inf"), float("-inf")],
        pd.NA,
    )
    ratio = pd.to_numeric(ratio, errors="coerce").dropna()
    if len(ratio) < min_days:
        return None
    return float(ratio.mean())
