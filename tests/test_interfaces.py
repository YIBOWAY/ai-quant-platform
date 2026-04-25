from typing import get_type_hints

import pandas as pd

from quant_system.core.interfaces import (
    Constraint,
    Factor,
    FactorContext,
    PortfolioOptimizer,
    RiskModel,
    Strategy,
    StrategyContext,
    TargetPosition,
)


def test_target_position_keeps_strategy_output_separate_from_orders() -> None:
    target = TargetPosition(asset="SPY", target_weight=0.25, reason="example")

    assert target.asset == "SPY"
    assert target.target_weight == 0.25
    assert target.reason == "example"


def test_factor_context_carries_point_in_time_frames() -> None:
    ohlcv = pd.DataFrame({"close": [100.0]})
    ctx = FactorContext(ohlcv=ohlcv)

    assert ctx.ohlcv.equals(ohlcv)


def test_phase_0_protocols_expose_expected_methods() -> None:
    assert "compute" in Factor.__dict__
    assert "target_weights" in Strategy.__dict__
    assert "solve" in PortfolioOptimizer.__dict__


def test_factor_protocol_signature_matches_phase_2_base_factor() -> None:
    hints = get_type_hints(Factor.compute)

    assert hints["ohlcv"] is pd.DataFrame
    assert hints["return"] is pd.DataFrame


def test_optimizer_signature_mentions_risk_model_and_constraints() -> None:
    hints = get_type_hints(PortfolioOptimizer.solve)

    assert hints["risk_model"] is RiskModel
    assert hints["constraints"] == list[Constraint]
    assert hints["return"] == pd.Series


def test_strategy_context_is_explicitly_not_a_broker_context() -> None:
    ctx = StrategyContext(
        timestamp=pd.Timestamp("2026-01-02"),
        prices=pd.DataFrame({"close": [100.0]}),
        positions=pd.Series({"SPY": 0.0}),
    )

    assert not hasattr(ctx, "broker")
    assert ctx.timestamp == pd.Timestamp("2026-01-02")
