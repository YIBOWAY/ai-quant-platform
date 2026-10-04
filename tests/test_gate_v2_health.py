"""Health checks: total-return PSR floor, drawdown cap, volatility cap, reasons."""

from __future__ import annotations

import numpy as np

from quant_system.research import gate_v2 as g
from tests.gate_v2_fixtures import active_series_from, balanced_returns


def test_psr_floor_is_equivalent_to_a_positive_sharpe() -> None:
    positive = g.health_checks_v2(
        active=active_series_from(balanced_returns(200, mean=0.001, spread=0.004)),
        config=g.GATE_V2_CONFIG,
    )
    negative = g.health_checks_v2(
        active=active_series_from(balanced_returns(200, mean=-0.001, spread=0.004)),
        config=g.GATE_V2_CONFIG,
    )
    assert positive["psr_total"]["passed"] is True
    assert negative["psr_total"]["passed"] is False
    assert negative["psr_total"]["reason"] == "psr_total_below_floor"


def test_the_psr_floor_note_is_carried_on_the_record() -> None:
    result = g.health_checks_v2(
        active=active_series_from(balanced_returns(200, mean=0.001, spread=0.004)),
        config=g.GATE_V2_CONFIG,
    )
    assert "floor" in result["psr_floor_note"]


def test_a_deep_drawdown_breaks_the_loss_cap() -> None:
    returns = [0.05] + [-0.45] + [0.0] * 250
    result = g.health_checks_v2(active=active_series_from(returns), config=g.GATE_V2_CONFIG)
    assert result["max_drawdown"]["passed"] is False
    assert result["max_drawdown"]["reason"] == "max_drawdown_above_cap"
    assert result["passed"] is False


def test_a_high_volatility_sleeve_breaks_the_dispersion_cap() -> None:
    returns = [0.03, -0.03] * 150  # annualized vol ~ 0.48
    result = g.health_checks_v2(active=active_series_from(returns), config=g.GATE_V2_CONFIG)
    assert result["annual_volatility"]["passed"] is False
    assert result["annual_volatility"]["reason"] == "annual_volatility_above_cap"


def test_the_three_checks_report_independently() -> None:
    rng = np.random.default_rng(5)
    returns = [float(value) for value in rng.normal(0.0008, 0.006, 260)]
    result = g.health_checks_v2(active=active_series_from(returns), config=g.GATE_V2_CONFIG)
    for block in ("psr_total", "max_drawdown", "annual_volatility"):
        assert "value" in result[block] and "passed" in result[block] and "reason" in result[block]
    assert result["passed"] == (result["reasons"] == [])


def test_insufficient_observation_names_every_block() -> None:
    result = g.health_checks_v2(active=active_series_from([0.001]), config=g.GATE_V2_CONFIG)
    assert result["passed"] is False
    assert result["reasons"] == [
        "insufficient_observations",
        "insufficient_observations",
        "insufficient_observations",
    ]
