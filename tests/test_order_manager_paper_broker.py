import pandas as pd
import pytest

from quant_system.execution.models import OrderRequest, OrderSide, OrderStatus
from quant_system.execution.order_manager import OrderManager
from quant_system.execution.paper_broker import PaperBroker
from quant_system.execution.portfolio import PaperPortfolio
from quant_system.risk.engine import RiskEngine
from quant_system.risk.models import RiskContext, RiskLimits


def _request(quantity: float = 10, symbol: str = "SPY") -> OrderRequest:
    return OrderRequest(
        timestamp=pd.Timestamp("2024-01-03", tz="UTC"),
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=quantity,
        limit_price=100.0,
        reason="test",
    )


def _context() -> RiskContext:
    return RiskContext(
        cash=10_000.0,
        equity=10_000.0,
        peak_equity=10_000.0,
        daily_pnl=0.0,
        positions={},
        latest_prices={"SPY": 100.0},
    )


def _limits(**overrides) -> RiskLimits:
    payload = {"kill_switch": False}
    payload.update(overrides)
    return RiskLimits(**payload)


def test_order_manager_rejects_order_before_broker_submission_when_risk_fails() -> None:
    broker = PaperBroker(portfolio=PaperPortfolio(initial_cash=10_000))
    manager = OrderManager(
        risk_engine=RiskEngine(_limits(max_order_value=100)),
        broker=broker,
    )

    order = manager.create_and_submit(_request(quantity=2), _context())

    assert order.status == OrderStatus.REJECTED
    assert broker.submitted_order_ids == []
    assert len(manager.risk_breach_log) == 1
    assert [event.status for event in manager.order_event_log] == [
        OrderStatus.CREATED,
        OrderStatus.REJECTED,
    ]


def test_order_manager_records_created_submitted_partial_and_filled_statuses() -> None:
    broker = PaperBroker(
        portfolio=PaperPortfolio(initial_cash=10_000),
        max_fill_ratio_per_tick=0.5,
    )
    manager = OrderManager(
        risk_engine=RiskEngine(_limits(max_order_value=10_000, max_position_size=1.0)),
        broker=broker,
    )

    order = manager.create_and_submit(_request(quantity=10), _context())
    manager.process_market_data(
        timestamp=pd.Timestamp("2024-01-03 10:00", tz="UTC"),
        prices={"SPY": 100.0},
    )
    assert order.status == OrderStatus.PARTIALLY_FILLED
    manager.process_market_data(
        timestamp=pd.Timestamp("2024-01-03 10:01", tz="UTC"),
        prices={"SPY": 100.0},
    )

    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == pytest.approx(10)
    assert broker.portfolio.position("SPY") == pytest.approx(10)
    assert broker.portfolio.cash == pytest.approx(9_000)
    assert [fill.quantity for fill in manager.trade_log] == [5, 5]
    assert [event.status for event in manager.order_event_log] == [
        OrderStatus.CREATED,
        OrderStatus.SUBMITTED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
    ]


def test_order_manager_can_cancel_submitted_order() -> None:
    broker = PaperBroker(
        portfolio=PaperPortfolio(initial_cash=10_000),
        max_fill_ratio_per_tick=0.0,
    )
    manager = OrderManager(
        risk_engine=RiskEngine(_limits(max_order_value=10_000, max_position_size=1.0)),
        broker=broker,
    )

    order = manager.create_and_submit(_request(quantity=10), _context())
    cancelled = manager.cancel_order(order.order_id, reason="test_cancel")

    assert cancelled.status == OrderStatus.CANCELLED
    assert manager.order_event_log[-1].status == OrderStatus.CANCELLED


def test_paper_broker_caps_buy_fill_to_available_cash() -> None:
    broker = PaperBroker(portfolio=PaperPortfolio(initial_cash=100))
    manager = OrderManager(
        risk_engine=RiskEngine(_limits(max_order_value=10_000, max_position_size=1.0)),
        broker=broker,
    )

    order = manager.create_and_submit(_request(quantity=10), _context())
    manager.process_market_data(
        timestamp=pd.Timestamp("2024-01-03 10:00", tz="UTC"),
        prices={"SPY": 100.0},
    )

    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == pytest.approx(1)
    assert broker.portfolio.cash == pytest.approx(0)
    assert broker.portfolio.position("SPY") == pytest.approx(1)


def test_paper_broker_does_not_create_naked_short_positions() -> None:
    broker = PaperBroker(portfolio=PaperPortfolio(initial_cash=10_000))
    manager = OrderManager(
        risk_engine=RiskEngine(_limits(max_order_value=10_000, max_position_size=1.0)),
        broker=broker,
    )
    request = OrderRequest(
        timestamp=pd.Timestamp("2024-01-03", tz="UTC"),
        symbol="SPY",
        side=OrderSide.SELL,
        quantity=5,
        limit_price=100.0,
        reason="test",
    )

    order = manager.create_and_submit(request, _context())
    fills = manager.process_market_data(
        timestamp=pd.Timestamp("2024-01-03 10:00", tz="UTC"),
        prices={"SPY": 100.0},
    )

    assert order.status == OrderStatus.SUBMITTED
    assert fills == []
    assert broker.portfolio.cash == pytest.approx(10_000)
    assert broker.portfolio.position("SPY") == pytest.approx(0)
