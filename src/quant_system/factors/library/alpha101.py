from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import numpy as np
import pandas as pd

from quant_system.factors.base import BaseFactor

CITATION = "Kakushadze 2016, 101 Formulaic Alphas"


class Alpha101Factor(BaseFactor):
    """Base class for fixed-formula Alpha101 factors."""

    direction = "neutral"
    formula: ClassVar[str]
    required_columns: ClassVar[tuple[str, ...]] = (
        "open",
        "high",
        "low",
        "close",
        "volume",
    )

    def __init__(self, *, lookback: int | None = None) -> None:
        if lookback is not None and lookback != self.default_lookback:
            raise ValueError(
                f"{self.factor_id} is a fixed-window paper formula; "
                f"lookback must be {self.default_lookback}"
            )
        super().__init__(lookback=self.default_lookback)

    def _alpha_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = [column for column in self.required_columns if column not in frame.columns]
        if missing:
            raise ValueError(f"missing Alpha101 input columns: {', '.join(missing)}")
        prepared = frame.copy()
        for column in self.required_columns:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
        if "vwap" in prepared.columns:
            prepared["vwap"] = pd.to_numeric(prepared["vwap"], errors="coerce")
        else:
            prepared["vwap"] = (
                prepared["high"] + prepared["low"] + prepared["close"]
            ) / 3
        return prepared


class Alpha101_001(Alpha101Factor):
    factor_id = "alpha101_001"
    factor_name = "Alpha101 001"
    default_lookback = 20
    formula = (
        r"\operatorname{rank}(\operatorname{ts\_argmax}("
        r"\operatorname{signedpower}((returns < 0 ? stddev(returns,20) : close),2),5)) - 0.5"
    )
    description = f"{CITATION}; Alpha#1 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        returns = _returns(alpha)
        selected = alpha["close"].where(returns >= 0, _ts_std(returns, 20, alpha))
        return _rank(alpha, _ts_argmax(_signed_power(selected, 2.0), 5, alpha)) - 0.5


class Alpha101_002(Alpha101Factor):
    factor_id = "alpha101_002"
    factor_name = "Alpha101 002"
    default_lookback = 6
    formula = (
        r"-1 * correlation(rank(delta(log(volume),2)), "
        r"rank((close-open)/open), 6)"
    )
    description = f"{CITATION}; Alpha#2 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        volume_delta = _delta(np.log(alpha["volume"]), 2, alpha)
        intraday_return = (alpha["close"] - alpha["open"]) / alpha["open"]
        return -1 * _correlation(
            _rank(alpha, volume_delta),
            _rank(alpha, intraday_return),
            6,
            alpha,
        )


class Alpha101_003(Alpha101Factor):
    factor_id = "alpha101_003"
    factor_name = "Alpha101 003"
    default_lookback = 10
    formula = r"-1 * correlation(rank(open), rank(volume), 10)"
    description = f"{CITATION}; Alpha#3 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        return -1 * _correlation(
            _rank(alpha, alpha["open"]),
            _rank(alpha, alpha["volume"]),
            10,
            alpha,
        )


class Alpha101_004(Alpha101Factor):
    factor_id = "alpha101_004"
    factor_name = "Alpha101 004"
    default_lookback = 9
    formula = r"-1 * ts_rank(rank(low), 9)"
    description = f"{CITATION}; Alpha#4 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        return -1 * _ts_rank(_rank(alpha, alpha["low"]), 9, alpha)


class Alpha101_005(Alpha101Factor):
    factor_id = "alpha101_005"
    factor_name = "Alpha101 005"
    default_lookback = 10
    formula = r"rank(open - sum(vwap,10)/10) * (-1 * abs(rank(close - vwap)))"
    description = (
        f"{CITATION}; Alpha#5 original formula: ${formula}$. "
        "Implementation uses a `vwap` column when present, otherwise a typical-price proxy."
    )

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        return _rank(alpha, alpha["open"] - _ts_sum(alpha["vwap"], 10, alpha) / 10) * (
            -1 * _rank(alpha, alpha["close"] - alpha["vwap"]).abs()
        )


class Alpha101_006(Alpha101Factor):
    factor_id = "alpha101_006"
    factor_name = "Alpha101 006"
    default_lookback = 10
    formula = r"-1 * correlation(open, volume, 10)"
    description = f"{CITATION}; Alpha#6 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        return -1 * _correlation(alpha["open"], alpha["volume"], 10, alpha)


class Alpha101_007(Alpha101Factor):
    factor_id = "alpha101_007"
    factor_name = "Alpha101 007"
    default_lookback = 60
    formula = (
        r"(adv20 < volume) ? "
        r"((-1 * ts_rank(abs(delta(close,7)),60)) * sign(delta(close,7))) : -1"
    )
    description = f"{CITATION}; Alpha#7 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        adv20 = _ts_mean(alpha["volume"], 20, alpha)
        close_delta = _delta(alpha["close"], 7, alpha)
        active = -1 * _ts_rank(close_delta.abs(), 60, alpha) * np.sign(close_delta)
        return pd.Series(
            np.where(adv20 < alpha["volume"], active, -1.0),
            index=alpha.index,
        )


class Alpha101_008(Alpha101Factor):
    factor_id = "alpha101_008"
    factor_name = "Alpha101 008"
    default_lookback = 10
    formula = (
        r"-1 * rank((sum(open,5) * sum(returns,5)) - "
        r"delay((sum(open,5) * sum(returns,5)),10))"
    )
    description = f"{CITATION}; Alpha#8 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        product = _ts_sum(alpha["open"], 5, alpha) * _ts_sum(_returns(alpha), 5, alpha)
        return -1 * _rank(alpha, product - _delay(product, 10, alpha))


class Alpha101_009(Alpha101Factor):
    factor_id = "alpha101_009"
    factor_name = "Alpha101 009"
    default_lookback = 5
    formula = (
        r"(0 < ts_min(delta(close,1),5)) ? delta(close,1) : "
        r"((ts_max(delta(close,1),5) < 0) ? delta(close,1) : -1 * delta(close,1))"
    )
    description = f"{CITATION}; Alpha#9 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        close_delta = _delta(alpha["close"], 1, alpha)
        positive = _ts_min(close_delta, 5, alpha) > 0
        negative = _ts_max(close_delta, 5, alpha) < 0
        return _conditional_delta(close_delta, positive, negative)


class Alpha101_010(Alpha101Factor):
    factor_id = "alpha101_010"
    factor_name = "Alpha101 010"
    default_lookback = 4
    formula = (
        r"rank((0 < ts_min(delta(close,1),4)) ? delta(close,1) : "
        r"((ts_max(delta(close,1),4) < 0) ? delta(close,1) : -1 * delta(close,1)))"
    )
    description = f"{CITATION}; Alpha#10 original formula: ${formula}$."

    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        alpha = self._alpha_frame(frame)
        close_delta = _delta(alpha["close"], 1, alpha)
        positive = _ts_min(close_delta, 4, alpha) > 0
        negative = _ts_max(close_delta, 4, alpha) < 0
        return _rank(alpha, _conditional_delta(close_delta, positive, negative))


ALPHA101_FACTORS: tuple[type[Alpha101Factor], ...] = (
    Alpha101_001,
    Alpha101_002,
    Alpha101_003,
    Alpha101_004,
    Alpha101_005,
    Alpha101_006,
    Alpha101_007,
    Alpha101_008,
    Alpha101_009,
    Alpha101_010,
)


def _rank(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    return values.groupby(frame["timestamp"], sort=False).rank(pct=True)


def _delta(values: pd.Series, periods: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).diff(periods)


def _delay(values: pd.Series, periods: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).shift(periods)


def _rolling_transform(
    values: pd.Series,
    window: int,
    frame: pd.DataFrame,
    function: str | Callable[[pd.Series], float],
) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).apply(function)
        if callable(function)
        else getattr(series.rolling(window, min_periods=window), function)()
    )


def _ts_sum(values: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).sum()
    )


def _ts_mean(values: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).mean()
    )


def _ts_std(values: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).std()
    )


def _ts_min(values: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).min()
    )


def _ts_max(values: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).max()
    )


def _ts_rank(values: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).apply(
            lambda rolling_values: pd.Series(rolling_values).rank(pct=True).iloc[-1],
            raw=False,
        )
    )


def _ts_argmax(values: pd.Series, window: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).transform(
        lambda series: series.rolling(window, min_periods=window).apply(
            lambda rolling_values: float(np.argmax(rolling_values) + 1),
            raw=True,
        )
    )


def _correlation(
    left: pd.Series,
    right: pd.Series,
    window: int,
    frame: pd.DataFrame,
) -> pd.Series:
    return left.groupby(frame["symbol"], sort=False, group_keys=False).apply(
        lambda series: series.rolling(window, min_periods=window).corr(right.loc[series.index])
    )


def _signed_power(values: pd.Series, exponent: float) -> pd.Series:
    return np.sign(values) * np.abs(values) ** exponent


def _returns(frame: pd.DataFrame) -> pd.Series:
    return frame.groupby("symbol", sort=False)["close"].pct_change()


def _conditional_delta(
    close_delta: pd.Series,
    positive: pd.Series,
    negative: pd.Series,
) -> pd.Series:
    return pd.Series(
        np.where(positive, close_delta, np.where(negative, close_delta, -1 * close_delta)),
        index=close_delta.index,
    )
