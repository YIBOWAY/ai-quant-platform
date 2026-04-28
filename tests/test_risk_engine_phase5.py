import pandas as pd

from quant_system.execution.models import OrderRequest, OrderSide
from quant_system.risk.engine import RiskEngine
from quant_system.risk.models import RiskContext, RiskLimits


def _limits(**overrides) -> RiskLimits:
    payload = {"kill_switch": False}
    payload.update(overrides)
    return RiskLimits(**payload)


def _request(symbol: str = "SPY", quantity: float = 10, price: float = 100) -> OrderRequest:
    return OrderRequest(
        timestamp=pd.Timestamp("2024-01-03", tz="UTC"),
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=quantity,
        limit_price=price,
        reason="test",
    )


def _context(**overrides) -> RiskContext:
    payload = {
        "cash": 10_000.0,
        "equity": 10_000.0,
        "peak_equity": 10_000.0,
        "daily_pnl": 0.0,
        "positions": {},
        "latest_prices": {"SPY": 100.0, "AAPL": 100.0},
    }
    payload.update(overrides)
    return RiskContext(**payload)


def test_risk_engine_rejects_order_above_max_order_value() -> None:
    engine = RiskEngine(_limits(max_order_value=1_000))

    decision = engine.check_order(_request(quantity=20), _context())

    assert decision.approved is False
    assert decision.breaches[0].rule_name == "max_order_value"


def test_risk_engine_rejects_blocked_symbol_and_symbols_outside_allowlist() -> None:
    engine = RiskEngine(
        _limits(allowed_symbols=["SPY"], blocked_symbols=["AAPL"])
    )

    blocked = engine.check_order(_request(symbol="AAPL"), _context())
    not_allowed = engine.check_order(_request(symbol="QQQ"), _context())

    assert blocked.approved is False
    assert blocked.breaches[0].rule_name == "blocked_symbols"
    assert not_allowed.approved is False
    assert not_allowed.breaches[0].rule_name == "allowed_symbols"


def test_risk_engine_kill_switch_blocks_every_new_order() -> None:
    engine = RiskEngine(RiskLimits(kill_switch=True))

    decision = engine.check_order(_request(), _context())

    assert decision.approved is False
    assert decision.breaches[0].rule_name == "kill_switch"


def test_risk_engine_rejects_projected_position_size_daily_loss_and_drawdown() -> None:
    position_engine = RiskEngine(_limits(max_position_size=0.50))
    daily_loss_engine = RiskEngine(_limits(max_position_size=1.0, max_daily_loss=0.02))
    drawdown_engine = RiskEngine(_limits(max_position_size=1.0, max_drawdown=0.10))

    position = position_engine.check_order(_request(quantity=60), _context())
    daily_loss = daily_loss_engine.check_order(_request(), _context(daily_pnl=-300.0))
    drawdown = drawdown_engine.check_order(
        _request(),
        _context(equity=10_000.0, peak_equity=12_000.0),
    )

    assert position.approved is False
    assert position.breaches[0].rule_name == "max_position_size"
    assert daily_loss.approved is False
    assert daily_loss.breaches[0].rule_name == "max_daily_loss"
    assert drawdown.approved is False
    assert drawdown.breaches[0].rule_name == "max_drawdown"


def test_risk_engine_checks_portfolio_after_fills() -> None:
    engine = RiskEngine(_limits(max_position_size=0.20, max_daily_loss=0.02))

    decision = engine.check_portfolio(
        _context(
            equity=10_000.0,
            positions={"SPY": 30},
            latest_prices={"SPY": 100.0},
            daily_pnl=-300.0,
        )
    )

    assert decision.approved is False
    assert {breach.rule_name for breach in decision.breaches} == {
        "max_position_size",
        "max_daily_loss",
    }
    assert all(breach.symbol in {"SPY", "PORTFOLIO"} for breach in decision.breaches)


def test_risk_limits_default_to_kill_switch_enabled() -> None:
    assert RiskLimits().kill_switch is True
