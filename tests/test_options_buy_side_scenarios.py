from __future__ import annotations

import pytest

from quant_system.options.buy_side_scenarios import (
    BuySideScenarioLabInput,
    BuySideUserScenarioPnL,
    run_buy_side_scenario_lab,
)
from quant_system.options.models import BuySideStrategyLeg


def _long_call(**overrides) -> BuySideStrategyLeg:
    params = {
        "symbol": "US.AAPL260619C100000",
        "option_type": "CALL",
        "side": "long",
        "expiry": "2026-06-19",
        "as_of_date": "2026-05-20",
        "strike": 100.0,
        "spot": 100.0,
        "bid": 5.0,
        "ask": 5.0,
        "implied_volatility": 0.25,
        "delta": 0.50,
        "gamma": 0.02,
        "theta": -0.10,
        "vega": 0.20,
        "open_interest": 500,
        "volume": 100,
    }
    params.update(overrides)
    return BuySideStrategyLeg(**params)


def _short_call(**overrides) -> BuySideStrategyLeg:
    params = {
        "symbol": "US.AAPL260619C110000",
        "option_type": "CALL",
        "side": "short",
        "expiry": "2026-06-19",
        "as_of_date": "2026-05-20",
        "strike": 110.0,
        "spot": 100.0,
        "bid": 2.0,
        "ask": 2.0,
        "implied_volatility": 0.23,
        "delta": 0.30,
        "gamma": 0.01,
        "theta": -0.05,
        "vega": 0.12,
        "open_interest": 500,
        "volume": 100,
    }
    params.update(overrides)
    return BuySideStrategyLeg(**params)


def test_long_call_positive_spot_move() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call()],
            spot_change_pct=[10],
            iv_change_vol_points=[0],
            days_passed=[0],
        )
    )

    row = result.results[0]
    assert row.estimated_pnl == pytest.approx(600.0)
    assert row.approximation_reliability == "high"


def test_long_call_iv_crush_uses_vega_per_vol_point() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call()],
            spot_change_pct=[0],
            iv_change_vol_points=[-5],
            days_passed=[0],
        )
    )

    assert result.results[0].estimated_pnl == pytest.approx(-100.0)
    assert "GREEK_UNIT_ASSUMPTION" in result.results[0].warnings


def test_spread_capped_upside_approximation() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call(), _short_call()],
            spot_change_pct=[30],
            iv_change_vol_points=[0],
            days_passed=[0],
        )
    )

    row = result.results[0]
    assert row.estimated_pnl == pytest.approx(1050.0)
    assert row.approximation_reliability == "low"


def test_theta_decay_with_no_spot_move() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call()],
            spot_change_pct=[0],
            iv_change_vol_points=[0],
            days_passed=[7],
        )
    )

    assert result.results[0].estimated_pnl == pytest.approx(-70.0)


def test_missing_greeks_returns_warning_and_uses_entry_value() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call(delta=None, gamma=None, theta=None, vega=None)],
            spot_change_pct=[10],
            iv_change_vol_points=[-5],
            days_passed=[7],
        )
    )

    assert result.results[0].estimated_pnl == pytest.approx(0.0)
    assert "MISSING_GREEKS" in result.results[0].warnings


def test_option_value_floor_at_zero() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call(delta=0.1, gamma=0.0, theta=-1.0, vega=0.0)],
            spot_change_pct=[-20],
            iv_change_vol_points=[0],
            days_passed=[30],
        )
    )

    assert result.results[0].estimated_value == pytest.approx(0.0)
    assert result.results[0].estimated_pnl == pytest.approx(-500.0)


def test_user_defined_scenario_ev() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call()],
            spot_change_pct=[0],
            iv_change_vol_points=[0],
            days_passed=[0],
            user_scenarios=[
                BuySideUserScenarioPnL(
                    label="bull",
                    probability=0.3,
                    spot_change_pct=10,
                    iv_change_vol_points=0,
                    days_passed=0,
                ),
                BuySideUserScenarioPnL(
                    label="base",
                    probability=0.4,
                    spot_change_pct=0,
                    iv_change_vol_points=0,
                    days_passed=0,
                ),
                BuySideUserScenarioPnL(
                    label="bear",
                    probability=0.3,
                    spot_change_pct=-10,
                    iv_change_vol_points=0,
                    days_passed=0,
                ),
            ],
        )
    )

    assert result.scenario_ev is not None
    assert result.scenario_ev.expected_value == pytest.approx(60.0)
    assert len(result.scenario_ev.contributions) == 3
    assert result.scenario_ev.contributions[0].pnl == pytest.approx(600.0)


def test_bad_user_probability_skips_ev_with_warning() -> None:
    result = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=100.0,
            current_date="2026-05-20",
            legs=[_long_call()],
            spot_change_pct=[0],
            iv_change_vol_points=[0],
            days_passed=[0],
            user_scenarios=[
                BuySideUserScenarioPnL(
                    label="bull",
                    probability=0.7,
                    spot_change_pct=10,
                    iv_change_vol_points=0,
                    days_passed=0,
                ),
                BuySideUserScenarioPnL(
                    label="bear",
                    probability=0.2,
                    spot_change_pct=-10,
                    iv_change_vol_points=0,
                    days_passed=0,
                ),
            ],
        )
    )

    assert result.scenario_ev is None
    assert "INVALID_USER_SCENARIO_PROBABILITIES" in result.warnings
