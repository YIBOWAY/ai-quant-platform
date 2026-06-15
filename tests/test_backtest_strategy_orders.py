import pandas as pd
import pytest

from quant_system.backtest.models import BacktestConfig, OrderSide, TargetWeight
from quant_system.backtest.order_generation import OrderGenerator
from quant_system.backtest.portfolio import Portfolio
from quant_system.backtest.strategy import MeanReversionTopN, ScoreSignalStrategy


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


def test_order_generator_can_floor_orders_to_whole_shares() -> None:
    timestamp = pd.Timestamp("2024-01-03", tz="UTC")
    generator = OrderGenerator(
        BacktestConfig(
            initial_cash=1_050,
            min_order_value=1,
            whole_share_orders=True,
        )
    )

    orders = generator.generate_orders(
        timestamp=timestamp,
        targets=[TargetWeight(timestamp=timestamp, symbol="SPY", target_weight=1.0)],
        portfolio=Portfolio(initial_cash=1_050),
        prices={"SPY": 100.0},
    )

    assert len(orders) == 1
    assert orders[0].side == OrderSide.BUY
    assert orders[0].quantity == pytest.approx(10)


def test_mean_reversion_selects_lowest_scores_unlike_score_strategy() -> None:
    timestamp = pd.Timestamp("2024-01-03", tz="UTC")
    signal_frame = pd.DataFrame(
        {
            "symbol": ["SPY", "QQQ", "IWM"],
            "tradeable_ts": [timestamp, timestamp, timestamp],
            # SPY best momentum, IWM worst (even negative).
            "score": [0.9, 0.1, -0.4],
        }
    )

    momentum = ScoreSignalStrategy(signal_frame, top_n=1, target_gross_exposure=1.0)
    reversion = MeanReversionTopN(signal_frame, top_n=1, target_gross_exposure=1.0)

    momentum_targets = momentum.target_weights(timestamp)
    reversion_targets = reversion.target_weights(timestamp)

    assert momentum_targets and momentum_targets[0].symbol == "SPY"
    # Contrarian: picks the worst performer, including a negative score that the
    # long-only score gate would have dropped.
    assert reversion_targets and reversion_targets[0].symbol == "IWM"
    assert reversion_targets[0].target_weight == pytest.approx(1.0)


def test_backtest_strategy_factory_dispatch_and_unknown_id() -> None:
    from quant_system.backtest.pipeline import (
        _build_backtest_strategy,
        _resolve_strategy_id,
    )

    timestamp = pd.Timestamp("2024-01-03", tz="UTC")
    signal_frame = pd.DataFrame(
        {
            "symbol": ["SPY", "QQQ"],
            "tradeable_ts": [timestamp, timestamp],
            "score": [0.9, -0.2],
        }
    )

    assert _resolve_strategy_id("cross_sectional_top_n") == "cross_sectional_top_n"
    assert _resolve_strategy_id("mean_reversion_top_n") == "mean_reversion_top_n"
    assert isinstance(
        _build_backtest_strategy("cross_sectional_top_n", signal_frame, top_n=1),
        ScoreSignalStrategy,
    )
    assert isinstance(
        _build_backtest_strategy("mean_reversion_top_n", signal_frame, top_n=1),
        MeanReversionTopN,
    )

    # A registered-but-not-runnable strategy (replication) is rejected clearly.
    with pytest.raises(ValueError, match="not runnable by the backtest engine"):
        _resolve_strategy_id("reversal_momentum")
