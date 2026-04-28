from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.execution.pipeline import run_signal_paper_trading
from quant_system.experiments.models import FactorBlendConfig, FactorDirection, FactorWeight
from quant_system.experiments.scoring import build_multifactor_score_frame
from quant_system.factors.examples import MACDFactor, MomentumFactor, RSIFactor
from quant_system.factors.pipeline import compute_factor_pipeline


def _sample_ohlcv():
    frame = SampleOHLCVProvider().fetch_ohlcv(
        ["SPY", "QQQ"],
        start="2024-01-02",
        end="2024-03-29",
    )
    qqq_mask = frame["symbol"] == "QQQ"
    qqq_index = frame.loc[qqq_mask].groupby("symbol").cumcount()
    frame.loc[qqq_mask, "open"] = 130 - qqq_index * 0.20
    frame.loc[qqq_mask, "close"] = frame.loc[qqq_mask, "open"] - 0.40
    frame.loc[qqq_mask, "high"] = frame.loc[qqq_mask, "open"] + 0.25
    frame.loc[qqq_mask, "low"] = frame.loc[qqq_mask, "close"] - 0.25
    return frame


def _score_frame(factors):
    factor_results = compute_factor_pipeline(_sample_ohlcv(), factors=factors)
    config = FactorBlendConfig(
        factors=[
            FactorWeight(
                factor_id=factor.factor_id,
                weight=1.0,
                direction=(
                    FactorDirection.LOWER_IS_BETTER
                    if factor.direction == "lower_is_better"
                    else FactorDirection.HIGHER_IS_BETTER
                ),
            )
            for factor in factors
        ],
        rebalance_every_n_bars=5,
    )
    return build_multifactor_score_frame(factor_results, config)


def test_single_factor_signal_feeds_phase_5_paper_trading(tmp_path) -> None:
    result = run_signal_paper_trading(
        ohlcv=_sample_ohlcv(),
        signal_frame=_score_frame([RSIFactor(lookback=5)]),
        output_dir=tmp_path / "single",
        top_n=1,
        target_gross_exposure=0.25,
        initial_cash=100_000,
        max_order_value=50_000,
        max_position_size=0.50,
        kill_switch=False,
    )

    assert result.order_count > 0
    assert result.trade_count > 0
    assert result.final_equity > 0
    assert result.trades_path.exists()
    assert result.risk_breaches_path.exists()


def test_multi_factor_signal_feeds_phase_5_paper_trading(tmp_path) -> None:
    result = run_signal_paper_trading(
        ohlcv=_sample_ohlcv(),
        signal_frame=_score_frame(
            [
                MomentumFactor(lookback=5),
                RSIFactor(lookback=5),
                MACDFactor(lookback=5),
            ]
        ),
        output_dir=tmp_path / "multi",
        top_n=1,
        target_gross_exposure=0.25,
        initial_cash=100_000,
        max_order_value=50_000,
        max_position_size=0.50,
        kill_switch=False,
    )

    assert result.order_count > 0
    assert result.trade_count > 0
    assert result.final_equity > 0
    assert result.trades_path.exists()
    assert result.risk_breaches_path.exists()
