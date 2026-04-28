from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.factors.library.alpha101 import (
    ALPHA101_FACTORS,
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
from quant_system.factors.registry import build_default_factor_registry, register_alpha101_library

runner = CliRunner()


def _alpha101_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=90, freq="B", tz="UTC")
    symbols = ["AAA", "BBB", "CCC"]
    rows: list[dict[str, object]] = []
    for symbol_index, symbol in enumerate(symbols, start=1):
        for date_index, timestamp in enumerate(dates, start=1):
            seasonal = ((date_index + symbol_index) % 7 - 3) * 0.35
            drift = date_index * (0.35 + symbol_index * 0.12)
            close = 20 + symbol_index * 15 + drift + seasonal
            open_price = close * (1 + ((date_index + symbol_index) % 5 - 2) * 0.002)
            high = max(open_price, close) + 0.30 + symbol_index * 0.03
            low = min(open_price, close) - 0.25 - symbol_index * 0.02
            volume = (
                10_000
                + date_index * (70 + symbol_index * 15)
                + ((date_index * (symbol_index + 2)) % 19) * 650
            )
            vwap = (open_price + high + low + close) / 4
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "vwap": vwap,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(days=1),
                }
            )
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("factor_cls", "reference_fn"),
    [
        (Alpha101_001, lambda frame: _alpha001(frame)),
        (Alpha101_002, lambda frame: _alpha002(frame)),
        (Alpha101_003, lambda frame: _alpha003(frame)),
        (Alpha101_004, lambda frame: _alpha004(frame)),
        (Alpha101_005, lambda frame: _alpha005(frame)),
        (Alpha101_006, lambda frame: _alpha006(frame)),
        (Alpha101_007, lambda frame: _alpha007(frame)),
        (Alpha101_008, lambda frame: _alpha008(frame)),
        (Alpha101_009, lambda frame: _alpha009(frame)),
        (Alpha101_010, lambda frame: _alpha010(frame)),
    ],
)
def test_alpha101_factor_matches_formula_reference(factor_cls, reference_fn) -> None:
    frame = _alpha101_frame()
    factor = factor_cls()

    result = factor.compute(frame)
    expected_values = reference_fn(_prepare_reference_frame(frame))

    expected = pd.DataFrame(
        {
            "symbol": frame.sort_values(["symbol", "timestamp"])["symbol"].str.upper(),
            "signal_ts": pd.to_datetime(
                frame.sort_values(["symbol", "timestamp"])["timestamp"],
                utc=True,
            ),
            "expected": expected_values,
        }
    ).dropna()
    merged = result.merge(expected, on=["symbol", "signal_ts"], how="inner")

    assert not result.empty
    assert not merged.empty
    assert (result["tradeable_ts"] > result["signal_ts"]).all()
    assert result["value"].to_numpy() == pytest.approx(merged["expected"].to_numpy())
    assert "Kakushadze 2016" in factor.metadata.description
    assert f"Alpha#{factor.factor_id[-3:].lstrip('0')}" in factor.metadata.description


def test_alpha101_library_registers_explicitly_without_polluting_default_registry() -> None:
    default_registry = build_default_factor_registry()
    assert all(not factor_id.startswith("alpha101_") for factor_id in default_registry.factor_ids())

    register_alpha101_library(default_registry)

    alpha_ids = [
        factor_id
        for factor_id in default_registry.factor_ids()
        if factor_id.startswith("alpha101_")
    ]
    assert alpha_ids == [f"alpha101_{index:03d}" for index in range(1, 11)]
    assert len(ALPHA101_FACTORS) == 10


def test_factor_register_library_cli_lists_alpha101_without_changing_default_list() -> None:
    result = runner.invoke(app, ["factor", "register-library", "--name", "alpha101"])
    default_result = runner.invoke(app, ["factor", "list"])

    assert result.exit_code == 0
    assert "library=alpha101" in result.output
    assert "registered_factors=10" in result.output
    assert "factor_id=alpha101_001" in result.output
    assert "factor_id=alpha101_010" in result.output
    assert default_result.exit_code == 0
    assert "alpha101_001" not in default_result.output


def _prepare_reference_frame(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    prepared["symbol"] = prepared["symbol"].astype(str).str.upper().str.strip()
    prepared["timestamp"] = pd.to_datetime(prepared["timestamp"], utc=True)
    for column in ["open", "high", "low", "close", "volume", "vwap"]:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    return prepared.sort_values(["symbol", "timestamp"], ignore_index=True)


def _rank(frame: pd.DataFrame, values: pd.Series) -> pd.Series:
    return values.groupby(frame["timestamp"], sort=False).rank(pct=True)


def _delta(values: pd.Series, periods: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).diff(periods)


def _delay(values: pd.Series, periods: int, frame: pd.DataFrame) -> pd.Series:
    return values.groupby(frame["symbol"], sort=False).shift(periods)


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


def _alpha001(frame: pd.DataFrame) -> pd.Series:
    returns = _returns(frame)
    replacement = _ts_std(returns, 20, frame)
    selected = frame["close"].where(returns >= 0, replacement)
    return _rank(frame, _ts_argmax(_signed_power(selected, 2.0), 5, frame)) - 0.5


def _alpha002(frame: pd.DataFrame) -> pd.Series:
    volume_delta = _delta(np.log(frame["volume"]), 2, frame)
    intraday_return = (frame["close"] - frame["open"]) / frame["open"]
    return -1 * _correlation(_rank(frame, volume_delta), _rank(frame, intraday_return), 6, frame)


def _alpha003(frame: pd.DataFrame) -> pd.Series:
    return -1 * _correlation(_rank(frame, frame["open"]), _rank(frame, frame["volume"]), 10, frame)


def _alpha004(frame: pd.DataFrame) -> pd.Series:
    return -1 * _ts_rank(_rank(frame, frame["low"]), 9, frame)


def _alpha005(frame: pd.DataFrame) -> pd.Series:
    vwap = frame["vwap"]
    return _rank(frame, frame["open"] - _ts_sum(vwap, 10, frame) / 10) * (
        -1 * _rank(frame, frame["close"] - vwap).abs()
    )


def _alpha006(frame: pd.DataFrame) -> pd.Series:
    return -1 * _correlation(frame["open"], frame["volume"], 10, frame)


def _alpha007(frame: pd.DataFrame) -> pd.Series:
    adv20 = _ts_mean(frame["volume"], 20, frame)
    close_delta = _delta(frame["close"], 7, frame)
    active = -1 * _ts_rank(close_delta.abs(), 60, frame) * np.sign(close_delta)
    return pd.Series(np.where(adv20 < frame["volume"], active, -1.0), index=frame.index)


def _alpha008(frame: pd.DataFrame) -> pd.Series:
    product = _ts_sum(frame["open"], 5, frame) * _ts_sum(_returns(frame), 5, frame)
    return -1 * _rank(frame, product - _delay(product, 10, frame))


def _alpha009(frame: pd.DataFrame) -> pd.Series:
    close_delta = _delta(frame["close"], 1, frame)
    positive = _ts_min(close_delta, 5, frame) > 0
    negative = _ts_max(close_delta, 5, frame) < 0
    return pd.Series(
        np.where(positive, close_delta, np.where(negative, close_delta, -1 * close_delta)),
        index=frame.index,
    )


def _alpha010(frame: pd.DataFrame) -> pd.Series:
    close_delta = _delta(frame["close"], 1, frame)
    positive = _ts_min(close_delta, 4, frame) > 0
    negative = _ts_max(close_delta, 4, frame) < 0
    conditional = pd.Series(
        np.where(positive, close_delta, np.where(negative, close_delta, -1 * close_delta)),
        index=frame.index,
    )
    return _rank(frame, conditional)
