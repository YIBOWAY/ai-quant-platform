import inspect

import pytest

from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.factors.examples import (
    LiquidityFactor,
    MACDFactor,
    MomentumFactor,
    RSIFactor,
    VolatilityFactor,
)


def _sample_frame():
    return SampleOHLCVProvider().fetch_ohlcv(
        ["SPY", "AAPL"],
        start="2024-01-02",
        end="2024-01-31",
    )


@pytest.mark.parametrize(
    "factor_cls",
    [MomentumFactor, VolatilityFactor, LiquidityFactor, RSIFactor, MACDFactor],
)
def test_example_factors_emit_actionable_point_in_time_rows(factor_cls) -> None:
    frame = _sample_frame()
    factor = factor_cls(lookback=3)

    result = factor.compute(frame)

    assert not result.empty
    assert {
        "symbol",
        "signal_ts",
        "tradeable_ts",
        "factor_id",
        "factor_version",
        "factor_name",
        "lookback",
        "value",
    }.issubset(result.columns)
    assert result["value"].notna().all()
    assert (result["tradeable_ts"] > result["signal_ts"]).all()


def test_momentum_factor_uses_only_history_available_at_signal_time() -> None:
    frame = _sample_frame()
    factor = MomentumFactor(lookback=3)

    result = factor.compute(frame)
    first_spy = result[result["symbol"] == "SPY"].iloc[0]
    spy_prices = frame[frame["symbol"] == "SPY"].reset_index(drop=True)
    signal_idx = spy_prices.index[spy_prices["timestamp"] == first_spy["signal_ts"]][0]

    expected = (
        spy_prices.loc[signal_idx, "close"] / spy_prices.loc[signal_idx - 3, "close"] - 1.0
    )
    assert first_spy["value"] == pytest.approx(expected)
    assert first_spy["tradeable_ts"] == spy_prices.loc[signal_idx + 1, "timestamp"]


def test_rsi_factor_stays_within_expected_bounds() -> None:
    frame = _sample_frame()
    factor = RSIFactor(lookback=5)

    result = factor.compute(frame)

    assert not result.empty
    assert result["value"].between(0, 100).all()
    assert (result["tradeable_ts"] > result["signal_ts"]).all()


def test_rsi_factor_documents_boundary_handling_in_source() -> None:
    source = inspect.getsource(RSIFactor._compute_values)

    assert "边界处理：纯涨窗 -> 100；纯跌窗 -> 0；完全平盘 -> 50" in source


def test_macd_description_clarifies_simplified_lookback_semantics() -> None:
    metadata = MACDFactor().metadata

    assert "fast=L, slow=2L, signal=L" in metadata.description
    assert "经典 (12,26,9) 不能精确复现" in metadata.description


def test_macd_factor_uses_only_history_available_at_signal_time() -> None:
    frame = _sample_frame()
    factor = MACDFactor(lookback=3)

    result = factor.compute(frame)
    first_spy = result[result["symbol"] == "SPY"].iloc[0]
    spy = frame[frame["symbol"] == "SPY"].sort_values("timestamp").reset_index(drop=True)
    signal_idx = spy.index[spy["timestamp"] == first_spy["signal_ts"]][0]

    mutated = frame.copy()
    future_mask = (mutated["symbol"] == "SPY") & (mutated["timestamp"] > first_spy["signal_ts"])
    mutated.loc[future_mask, "close"] = mutated.loc[future_mask, "close"] * 100
    mutated_result = factor.compute(mutated)
    mutated_first = mutated_result[mutated_result["symbol"] == "SPY"].iloc[0]

    assert signal_idx >= 0
    assert first_spy["value"] == pytest.approx(mutated_first["value"])
