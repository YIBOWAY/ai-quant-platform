from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.factors.examples import LiquidityFactor, MomentumFactor
from quant_system.factors.pipeline import build_factor_signal_frame, compute_factor_pipeline


def test_factor_pipeline_combines_multiple_factor_outputs() -> None:
    frame = SampleOHLCVProvider().fetch_ohlcv(
        ["SPY", "AAPL"],
        start="2024-01-02",
        end="2024-01-31",
    )

    result = compute_factor_pipeline(
        frame,
        factors=[MomentumFactor(lookback=3), LiquidityFactor(lookback=3)],
    )

    assert set(result["factor_id"]) == {"momentum", "liquidity"}
    assert result["symbol"].nunique() == 2
    assert (result["tradeable_ts"] > result["signal_ts"]).all()


def test_build_factor_signal_frame_provides_phase_3_score_interface() -> None:
    frame = SampleOHLCVProvider().fetch_ohlcv(
        ["SPY", "AAPL"],
        start="2024-01-02",
        end="2024-01-31",
    )
    factor_results = compute_factor_pipeline(
        frame,
        factors=[MomentumFactor(lookback=3), LiquidityFactor(lookback=3)],
    )

    signal_frame = build_factor_signal_frame(factor_results)

    assert {"symbol", "signal_ts", "tradeable_ts", "score"}.issubset(signal_frame.columns)
    assert {"momentum", "liquidity"}.issubset(signal_frame.columns)
    assert signal_frame["score"].notna().all()
