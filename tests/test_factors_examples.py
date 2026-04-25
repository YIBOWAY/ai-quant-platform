import pytest

from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.factors.examples import LiquidityFactor, MomentumFactor, VolatilityFactor


def _sample_frame():
    return SampleOHLCVProvider().fetch_ohlcv(
        ["SPY", "AAPL"],
        start="2024-01-02",
        end="2024-01-31",
    )


@pytest.mark.parametrize(
    "factor_cls",
    [MomentumFactor, VolatilityFactor, LiquidityFactor],
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
