from quant_system.prediction_market.backtest import (
    PredictionMarketBacktestConfig,
    run_prediction_market_quasi_backtest,
)
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider


def test_prediction_market_quasi_backtest_outputs_metrics() -> None:
    result = run_prediction_market_quasi_backtest(
        provider=SamplePredictionMarketProvider(),
        config=PredictionMarketBacktestConfig(
            min_edge_bps=200,
            capital_limit=1000,
            max_legs=3,
            max_markets=10,
            fee_bps=0,
        ),
    )

    assert result.metrics.market_count == 2
    assert result.metrics.opportunity_count >= 1
    assert result.metrics.trigger_rate > 0
    assert result.metrics.max_edge_bps >= result.metrics.mean_edge_bps
    assert result.equity_curve[-1].cumulative_estimated_edge > 0
    assert all(item.hypothetical is True for item in result.opportunities)


def test_prediction_market_quasi_backtest_filters_by_threshold() -> None:
    result = run_prediction_market_quasi_backtest(
        provider=SamplePredictionMarketProvider(),
        config=PredictionMarketBacktestConfig(
            min_edge_bps=10_000,
            capital_limit=1000,
            max_legs=3,
            max_markets=10,
            fee_bps=0,
        ),
    )

    assert result.metrics.opportunity_count == 0
    assert result.equity_curve == []


def test_prediction_market_quasi_backtest_applies_fee_assumption() -> None:
    no_fee = run_prediction_market_quasi_backtest(
        provider=SamplePredictionMarketProvider(),
        config=PredictionMarketBacktestConfig(min_edge_bps=200, fee_bps=0),
    )
    high_fee = run_prediction_market_quasi_backtest(
        provider=SamplePredictionMarketProvider(),
        config=PredictionMarketBacktestConfig(min_edge_bps=200, fee_bps=100),
    )

    assert high_fee.metrics.total_estimated_edge < no_fee.metrics.total_estimated_edge
