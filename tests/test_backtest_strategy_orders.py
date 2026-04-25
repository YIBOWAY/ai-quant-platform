import pandas as pd
import pytest

from quant_system.backtest.models import BacktestConfig, OrderSide
from quant_system.backtest.order_generation import OrderGenerator
from quant_system.backtest.portfolio import Portfolio
from quant_system.backtest.strategy import ScoreSignalStrategy


def test_score_strategy_only_emits_targets_at_tradeable_timestamp() -> None:
    signal_frame = pd.DataFrame(
        {
            "symbol": ["SPY", "AAPL"],
            "signal_ts": [
                pd.Timestamp("2024-01-02", tz="UTC"),
                pd.Timestamp("2024-01-02", tz="UTC"),
            ],
            "tradeable_ts": [
                pd.Timestamp("2024-01-03", tz="UTC"),
                pd.Timestamp("2024-01-03", tz="UTC"),
            ],
            "score": [0.8, 0.2],
        }
    )
    strategy = ScoreSignalStrategy(signal_frame, top_n=1, target_gross_exposure=1.0)

    assert strategy.target_weights(pd.Timestamp("2024-01-02", tz="UTC")) is None
    targets = strategy.target_weights(pd.Timestamp("2024-01-03", tz="UTC"))

    assert targets is not None
    assert len(targets) == 1
    assert targets[0].symbol == "SPY"
    assert targets[0].target_weight == pytest.approx(1.0)


def test_order_generator_rebalances_to_targets_and_closes_unselected_positions() -> None:
    portfolio = Portfolio(initial_cash=500)
    portfolio.positions["AAPL"] = 5
    generator = OrderGenerator(BacktestConfig(initial_cash=1_000, min_order_value=1))
    timestamp = pd.Timestamp("2024-01-03", tz="UTC")
    strategy = ScoreSignalStrategy(
        pd.DataFrame(
            {
                "symbol": ["SPY"],
                "tradeable_ts": [timestamp],
                "score": [1.0],
            }
        ),
        top_n=1,
    )
    targets = strategy.target_weights(timestamp)

    orders = generator.generate_orders(
        timestamp=timestamp,
        targets=targets or [],
        portfolio=portfolio,
        prices={"SPY": 100.0, "AAPL": 100.0},
    )

    assert {order.symbol for order in orders} == {"SPY", "AAPL"}
    sell = next(order for order in orders if order.symbol == "AAPL")
    buy = next(order for order in orders if order.symbol == "SPY")
    assert sell.side == OrderSide.SELL
    assert sell.quantity == pytest.approx(5)
    assert buy.side == OrderSide.BUY
    assert buy.quantity == pytest.approx(10)
