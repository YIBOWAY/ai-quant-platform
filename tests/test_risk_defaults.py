from quant_system.risk.defaults import RiskDefaults, get_default_risk_limits


def test_default_risk_limits_match_phase_0_safety_boundary() -> None:
    limits = get_default_risk_limits()

    assert isinstance(limits, RiskDefaults)
    assert limits.max_position_size == 0.05
    assert limits.max_daily_loss == 0.02
    assert limits.max_drawdown == 0.10
    assert limits.max_order_value == 10_000
    assert limits.max_turnover == 1.0


def test_default_risk_limits_are_independent_objects() -> None:
    first = get_default_risk_limits()
    second = get_default_risk_limits()

    first.blocked_symbols.append("BAD")

    assert second.blocked_symbols == []

