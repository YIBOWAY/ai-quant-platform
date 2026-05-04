from __future__ import annotations

import pytest

from quant_system.options.buy_side_metrics import (
    BuySideMetricThresholds,
    score_buy_side_contract,
)
from quant_system.options.models import BuySideStrategyLeg


def _normal_leg(**overrides) -> BuySideStrategyLeg:
    params = {
        "symbol": "US.AAPL260619C100000",
        "option_type": "CALL",
        "side": "long",
        "expiry": "2026-06-19",
        "as_of_date": "2026-05-20",
        "strike": 100.0,
        "spot": 100.0,
        "bid": 5.0,
        "ask": 5.5,
        "implied_volatility": 0.25,
        "delta": 0.55,
        "gamma": 0.03,
        "theta": -0.10,
        "vega": 0.20,
        "open_interest": 500,
        "volume": 100,
        "update_time": "2026-05-20T20:00:00Z",
    }
    params.update(overrides)
    return BuySideStrategyLeg(**params)


def test_scores_normal_contract_with_core_metrics() -> None:
    result = score_buy_side_contract(
        _normal_leg(),
        atm_call_mid=5.25,
        atm_put_mid=4.75,
        user_target_move_pct=0.12,
        iv_low_1y=0.10,
        iv_high_1y=0.40,
        historical_volatility=0.20,
        iv_crush_vol_points=-5.0,
        now="2026-05-20T20:05:00Z",
    )

    assert result.mid_price == pytest.approx(5.25)
    assert result.bid_ask_spread_abs == pytest.approx(0.5)
    assert result.bid_ask_spread_pct == pytest.approx(0.5 / 5.25)
    assert result.intrinsic_value == pytest.approx(0.0)
    assert result.extrinsic_value == pytest.approx(5.25)
    assert result.break_even_price == pytest.approx(105.25)
    assert result.required_move_pct == pytest.approx(0.0525)
    assert result.expected_move_pct == pytest.approx(0.10)
    assert result.target_vs_expected_move_ratio == pytest.approx(1.2)
    assert result.daily_theta_cost == pytest.approx(0.10)
    assert result.theta_burn_7d == pytest.approx(0.70)
    assert result.vega_pct_of_premium == pytest.approx(0.20 / 5.25)
    assert result.estimated_iv_crush_loss == pytest.approx(1.0)
    assert result.delta_per_dollar == pytest.approx(0.55 * 100 / 5.25)
    assert result.iv_rank == pytest.approx(50.0)
    assert result.iv_hv_ratio == pytest.approx(1.25)
    assert result.contract_quality_score is not None
    assert "GREEK_UNIT_ASSUMPTION" in result.warnings


def test_missing_greeks_degrades_to_none_with_warning() -> None:
    result = score_buy_side_contract(
        _normal_leg(delta=None, gamma=None, theta=None, vega=None)
    )

    assert result.delta_per_dollar is None
    assert result.gamma_theta_ratio is None
    assert result.vega_pct_of_premium is None
    assert "MISSING_GREEKS" in result.warnings


def test_zero_theta_is_safe() -> None:
    result = score_buy_side_contract(_normal_leg(theta=0.0))

    assert result.daily_theta_cost == 0
    assert result.theta_pct_of_premium == 0
    assert result.days_to_lose_30pct is None
    assert result.gamma_theta_ratio is None


def test_wide_spread_is_flagged_and_liquidity_score_is_low() -> None:
    result = score_buy_side_contract(_normal_leg(bid=1.0, ask=1.5))

    assert result.bid_ask_spread_pct == pytest.approx(0.4)
    assert "WIDE_SPREAD" in result.warnings
    assert result.liquidity_score < 70


def test_stale_quote_is_flagged() -> None:
    result = score_buy_side_contract(
        _normal_leg(update_time="2026-05-20T19:00:00Z"),
        now="2026-05-20T20:00:00Z",
        thresholds=BuySideMetricThresholds(stale_quote_minutes=30),
    )

    assert "STALE_QUOTE" in result.warnings
    assert result.quote_staleness_minutes == pytest.approx(60.0)


def test_missing_iv_hv_degrades_gracefully() -> None:
    result = score_buy_side_contract(
        _normal_leg(implied_volatility=None),
        historical_volatility=None,
    )

    assert result.iv_rank is None
    assert result.iv_hv_ratio is None
    assert result.volatility_valuation_score is None
    assert "MISSING_VOLATILITY_DATA" in result.warnings


def test_high_iv_rank_warning() -> None:
    result = score_buy_side_contract(_normal_leg(), iv_rank=82.0)

    assert result.iv_rank == pytest.approx(82.0)
    assert "HIGH_IV_RANK" in result.warnings


def test_vega_unit_convention_is_per_one_vol_point() -> None:
    result = score_buy_side_contract(
        _normal_leg(vega=0.25, bid=10.0, ask=10.0),
        iv_crush_vol_points=-10.0,
    )

    assert result.estimated_iv_crush_loss == pytest.approx(2.5)
    assert result.estimated_iv_crush_loss_pct == pytest.approx(0.25)


def test_target_below_implied_move_warning() -> None:
    result = score_buy_side_contract(
        _normal_leg(),
        atm_call_mid=5.25,
        atm_put_mid=4.75,
        user_target_move_pct=0.05,
    )

    assert result.target_vs_expected_move_ratio == pytest.approx(0.5)
    assert "TARGET_BELOW_IMPLIED_MOVE" in result.warnings
