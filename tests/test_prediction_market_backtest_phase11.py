from quant_system.prediction_market.backtest import (
    PredictionMarketBacktestConfig,
    run_prediction_market_quasi_backtest,
)
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.models import (
    CLOBOrder,
    Market,
    OrderBookSnapshot,
    Outcome,
    PriceHistoryPoint,
)


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


def test_prediction_market_quasi_backtest_prefers_real_price_history_when_available() -> None:
    market = Market(
        market_id="real-binary-1",
        event_id="event-1",
        condition_id="condition-1",
        question="Will real history be used?",
        outcomes=[
            Outcome(name="YES", outcome_index=0, token_id="yes-token"),
            Outcome(name="NO", outcome_index=1, token_id="no-token"),
        ],
    )

    class HistoricalProvider:
        def list_markets(self, limit=None):
            return [market]

        def get_order_books(self, market_id: str):
            return [
                OrderBookSnapshot(
                    market_id=market_id,
                    condition_id="condition-1",
                    token_id="yes-token",
                    bids=[CLOBOrder(price=0.48, size=100)],
                    asks=[CLOBOrder(price=0.49, size=100)],
                ),
                OrderBookSnapshot(
                    market_id=market_id,
                    condition_id="condition-1",
                    token_id="no-token",
                    bids=[CLOBOrder(price=0.49, size=100)],
                    asks=[CLOBOrder(price=0.50, size=100)],
                ),
            ]

        def get_price_history(self, token_id: str, interval: str = "1d", fidelity: int = 60):
            assert interval == "1d"
            assert fidelity == 60
            if token_id == "yes-token":
                return [
                    PriceHistoryPoint(timestamp="2026-01-01T00:00:00Z", price=0.46),
                    PriceHistoryPoint(timestamp="2026-01-02T00:00:00Z", price=0.47),
                ]
            return [
                PriceHistoryPoint(timestamp="2026-01-01T00:00:00Z", price=0.49),
                PriceHistoryPoint(timestamp="2026-01-02T00:00:00Z", price=0.48),
            ]

    result = run_prediction_market_quasi_backtest(
        provider=HistoricalProvider(),
        config=PredictionMarketBacktestConfig(min_edge_bps=200, capital_limit=500),
    )

    assert result.metrics.market_count == 1
    assert result.metrics.opportunity_count == 2
    assert len(result.equity_curve) == 2
    assert any("historical last-trade price observations" in item for item in result.assumptions)
