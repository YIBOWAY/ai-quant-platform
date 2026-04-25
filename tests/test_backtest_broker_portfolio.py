import pandas as pd
import pytest

from quant_system.backtest.broker import BrokerSimulator
from quant_system.backtest.models import BacktestConfig, Order, OrderSide
from quant_system.backtest.portfolio import Portfolio


def test_broker_applies_slippage_commission_and_updates_cash_for_buy() -> None:
    portfolio = Portfolio(initial_cash=10_000)
    broker = BrokerSimulator(
        BacktestConfig(initial_cash=10_000, commission_bps=5, slippage_bps=10)
    )
    order = Order(
        order_id="order-1",
        timestamp=pd.Timestamp("2024-01-03", tz="UTC"),
        symbol="SPY",
        side=OrderSide.BUY,
        quantity=10,
        reason="test",
    )

    fills = broker.execute_orders([order], {"SPY": 100.0}, portfolio)

    assert len(fills) == 1
    fill = fills[0]
    assert fill.fill_price == pytest.approx(100.10)
    assert fill.gross_value == pytest.approx(1_001.0)
    assert fill.commission == pytest.approx(0.5005)
    assert portfolio.cash == pytest.approx(8_998.4995)
    assert portfolio.position("SPY") == pytest.approx(10)


def test_broker_executes_sells_before_buys_to_free_cash() -> None:
    portfolio = Portfolio(initial_cash=0)
    portfolio.positions["SPY"] = 10
    broker = BrokerSimulator(
        BacktestConfig(initial_cash=0, commission_bps=0, slippage_bps=0)
    )
    timestamp = pd.Timestamp("2024-01-03", tz="UTC")
    orders = [
        Order(
            order_id="buy",
            timestamp=timestamp,
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=5,
            reason="rotate",
        ),
        Order(
            order_id="sell",
            timestamp=timestamp,
            symbol="SPY",
            side=OrderSide.SELL,
            quantity=10,
            reason="rotate",
        ),
    ]

    fills = broker.execute_orders(orders, {"SPY": 100.0, "AAPL": 100.0}, portfolio)

    assert [fill.side for fill in fills] == [OrderSide.SELL, OrderSide.BUY]
    assert portfolio.position("SPY") == pytest.approx(0)
    assert portfolio.position("AAPL") == pytest.approx(5)
    assert portfolio.cash == pytest.approx(500)


def test_portfolio_marks_equity_with_supplied_prices() -> None:
    portfolio = Portfolio(initial_cash=1_000)
    portfolio.positions["SPY"] = 2

    assert portfolio.market_value({"SPY": 105.0}) == pytest.approx(210)
    assert portfolio.equity({"SPY": 105.0}) == pytest.approx(1_210)
