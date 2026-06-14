from __future__ import annotations

import pandas as pd
import pytest

from quant_system.backtest.models import BacktestConfig, OrderSide, TargetWeight
from quant_system.backtest.order_generation import OrderGenerator
from quant_system.backtest.portfolio import Portfolio
from quant_system.execution.models import OrderSide as ExecutionOrderSide
from quant_system.execution.pipeline import _generate_rebalance_requests
from quant_system.execution.portfolio import PaperPortfolio


def test_backtest_order_generator_keeps_order_at_min_value_boundary() -> None:
    timestamp = pd.Timestamp("2024-01-03", tz="UTC")
    generator = OrderGenerator(BacktestConfig(initial_cash=1_000, min_order_value=100))

    orders = generator.generate_orders(
        timestamp=timestamp,
        targets=[TargetWeight(timestamp=timestamp, symbol="SPY", target_weight=0.1)],
        portfolio=Portfolio(initial_cash=1_000),
        prices={"SPY": 100.0},
    )

    assert len(orders) == 1
    assert orders[0].side == OrderSide.BUY
    assert orders[0].quantity == pytest.approx(1.0)


def test_paper_rebalance_keeps_order_at_min_value_boundary() -> None:
    timestamp = pd.Timestamp("2024-01-03", tz="UTC")

    requests = _generate_rebalance_requests(
        timestamp=timestamp,
        targets=[TargetWeight(timestamp=timestamp, symbol="SPY", target_weight=0.1)],
        portfolio=PaperPortfolio(initial_cash=1_000),
        prices={"SPY": 100.0},
        min_order_value=100,
    )

    assert len(requests) == 1
    assert requests[0].side == ExecutionOrderSide.BUY
    assert requests[0].quantity == pytest.approx(1.0)
