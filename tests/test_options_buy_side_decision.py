from __future__ import annotations

import pandas as pd
import pytest

from quant_system.options.buy_side_decision import (
    BuySideDecisionRequest,
    run_buy_side_decision,
)
from quant_system.options.buy_side_scenarios import BuySideUserScenarioPnL
from quant_system.options.market_regime import VixRegimeSnapshot


def _chain() -> pd.DataFrame:
    rows = []
    for expiry, dte in [
        ("2026-05-29", 9),
        ("2026-06-19", 30),
        ("2027-06-18", 394),
    ]:
        for strike, delta, mid, theta, vega, oi in [
            (95.0, 0.80, 8.5, -0.05, 0.18, 900),
            (100.0, 0.56, 5.25, -0.08, 0.20, 800),
            (105.0, 0.35, 2.8, -0.06, 0.16, 600),
            (110.0, 0.24, 1.4, -0.04, 0.12, 500),
        ]:
            rows.append(
                {
                    "symbol": f"US.AAPL{expiry.replace('-', '')}C{int(strike * 1000):06d}",
                    "option_type": "CALL",
                    "expiry": expiry,
                    "strike": strike,
                    "bid": mid - 0.1,
                    "ask": mid + 0.1,
                    "implied_volatility": 0.24,
                    "delta": delta,
                    "gamma": 0.03,
                    "theta": theta,
                    "vega": vega,
                    "open_interest": oi,
                    "volume": 100,
                    "update_time": "2026-05-20T20:00:00Z",
                    "option_expiry_date_distance": dte,
                }
            )
        rows.append(
            {
                "symbol": f"US.AAPL{expiry.replace('-', '')}P100000",
                "option_type": "PUT",
                "expiry": expiry,
                "strike": 100.0,
                "bid": 4.6,
                "ask": 4.9,
                "implied_volatility": 0.25,
                "delta": -0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 900,
                "volume": 100,
                "update_time": "2026-05-20T20:00:00Z",
                "option_expiry_date_distance": dte,
            }
        )
    return pd.DataFrame(rows)


def _request(**overrides) -> BuySideDecisionRequest:
    params = {
        "ticker": "AAPL",
        "spot_price": 100.0,
        "view_type": "short_term_conservative_bullish",
        "target_price": 112.0,
        "target_date": "2026-08-21",
        "max_loss_budget": 800.0,
        "risk_preference": "balanced",
        "allow_capped_upside": True,
        "avoid_high_iv": False,
        "volatility_view": "auto",
        "event_risk": "none",
        "iv_rank": 35.0,
        "historical_volatility": 0.20,
        "as_of_date": "2026-05-20",
    }
    params.update(overrides)
    return BuySideDecisionRequest(**params)


def test_long_term_conservative_prefers_leaps_call_spread() -> None:
    result = run_buy_side_decision(
        _chain(),
        _request(
            view_type="long_term_conservative_bullish",
            target_price=125.0,
            target_date="2027-12-17",
            iv_rank=55,
        ),
        max_recommendations=5,
    )

    assert result.recommendations
    top = result.recommendations[0]
    assert top.strategy_type == "leaps_call_spread"
    assert top.rank == 1
    assert top.primary_risk_source in {"direction", "time", "volatility", "liquidity"}
    assert top.risk_attribution.keys() == {"direction", "time", "volatility", "liquidity"}
    assert "more suitable for the stated thesis" in top.one_line_summary


def test_event_high_iv_demotes_naked_long_call_but_keeps_it_visible() -> None:
    result = run_buy_side_decision(
        _chain(),
        _request(
            view_type="short_term_speculative_bullish",
            volatility_view="expect_iv_crush",
            event_risk="earnings",
            iv_rank=85,
            target_price=118.0,
        ),
        max_recommendations=8,
    )

    assert result.recommendations[0].strategy_type == "bull_call_spread"
    demoted_long_calls = [
        item
        for item in result.recommendations
        if item.strategy_type == "long_call" and item.demotion_badge is not None
    ]
    assert demoted_long_calls
    assert any("IV crush" in " ".join(item.key_risks) for item in demoted_long_calls)


def test_explicit_zero_iv_change_does_not_invent_crush_loss() -> None:
    result = run_buy_side_decision(
        _chain(),
        _request(expected_iv_change_vol_points=0.0),
        max_recommendations=8,
    )

    assert result.recommendations
    assert all(
        item.estimated_iv_change_pct == pytest.approx(0.0) for item in result.recommendations
    )


def test_long_term_aggressive_low_iv_prefers_leaps_call() -> None:
    result = run_buy_side_decision(
        _chain(),
        _request(
            view_type="long_term_aggressive_bullish",
            target_price=130.0,
            target_date="2027-12-17",
            max_loss_budget=1000.0,
            iv_rank=25,
            risk_preference="aggressive",
        ),
        max_recommendations=5,
    )

    assert result.recommendations
    assert result.recommendations[0].strategy_type == "leaps_call"


def test_decision_explanations_avoid_advice_language() -> None:
    result = run_buy_side_decision(_chain(), _request(), max_recommendations=5)
    banned = ["buy this", "best trade", "guaranteed", "risk-free"]

    for recommendation in result.recommendations:
        text = " ".join(
            [
                recommendation.one_line_summary,
                *recommendation.key_reasons,
                *recommendation.key_risks,
            ]
        ).lower()
        assert not any(term in text for term in banned)


def test_decision_ranking_is_deterministic() -> None:
    request = _request(iv_rank=35)

    first = run_buy_side_decision(_chain(), request, max_recommendations=8)
    second = run_buy_side_decision(_chain(), request, max_recommendations=8)

    assert [
        (item.rank, item.strategy_type, item.score, item.break_even)
        for item in first.recommendations
    ] == [
        (item.rank, item.strategy_type, item.score, item.break_even)
        for item in second.recommendations
    ]


def test_reward_risk_is_an_explicit_ranking_key_when_scores_tie() -> None:
    chain = pd.DataFrame(
        [
            {
                "symbol": "US.AAPL20260619C100000",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 5.0,
                "ask": 5.0,
                "implied_volatility": 0.25,
                "delta": 0.55,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 30,
            },
            {
                "symbol": "US.AAPL20260619C110000",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 110.0,
                "bid": 1.0,
                "ask": 1.0,
                "implied_volatility": 0.24,
                "delta": 0.30,
                "gamma": 0.02,
                "theta": -0.04,
                "vega": 0.12,
                "open_interest": 500,
                "volume": 80,
                "option_expiry_date_distance": 30,
            },
            {
                "symbol": "US.AAPL20260619C111000",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 111.0,
                "bid": 1.0,
                "ask": 1.0,
                "implied_volatility": 0.24,
                "delta": 0.30,
                "gamma": 0.02,
                "theta": -0.04,
                "vega": 0.12,
                "open_interest": 500,
                "volume": 80,
                "option_expiry_date_distance": 30,
            },
            {
                "symbol": "US.AAPL20260619P100000",
                "option_type": "PUT",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 4.5,
                "ask": 4.5,
                "implied_volatility": 0.25,
                "delta": -0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 30,
            },
        ]
    )

    result = run_buy_side_decision(
        chain,
        _request(target_price=105.0),
        max_recommendations=10,
    )

    spreads = [item for item in result.recommendations if item.strategy_type == "bull_call_spread"]
    assert [item.score for item in spreads] == [spreads[0].score] * len(spreads)
    assert [item.risk_reward for item in spreads] == [1.75, 1.5]


def test_atm_straddle_mid_reaches_final_recommendation_risk_attribution() -> None:
    chain = pd.DataFrame(
        [
            {
                "symbol": "US.AAPL20260619C100000",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 5.0,
                "ask": 5.0,
                "implied_volatility": 0.25,
                "delta": 0.55,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 30,
            },
            {
                "symbol": "US.AAPL20260619P100000",
                "option_type": "PUT",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 0.1,
                "ask": 0.1,
                "implied_volatility": 0.25,
                "delta": -0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 30,
            },
        ]
    )

    result = run_buy_side_decision(
        chain,
        _request(target_price=110.0),
        max_recommendations=10,
    )

    long_call = next(item for item in result.recommendations if item.strategy_type == "long_call")
    assert long_call.expected_move_pct == pytest.approx(0.051)
    assert long_call.risk_attribution["direction"] == pytest.approx((0.05 / 0.051) * 50)


def test_final_recommendation_exposes_theta_safety_and_greek_efficiency() -> None:
    result = run_buy_side_decision(_chain(), _request(), max_recommendations=10)

    assert result.recommendations
    assert result.recommendations[0].theta_safety_score is not None
    assert result.recommendations[0].greek_efficiency_score is not None


def test_final_recommendation_exposes_worst_scenario_approximation_reliability() -> None:
    result = run_buy_side_decision(
        _chain(),
        _request(
            scenario_spot_changes=[30.0],
            scenario_iv_changes=[0.0],
            scenario_days_passed=[0],
        ),
        max_recommendations=10,
    )

    assert result.recommendations
    assert all(item.scenario_approximation_reliability == "low" for item in result.recommendations)


def test_historical_volatility_reaches_the_final_iv_hv_explanation() -> None:
    result = run_buy_side_decision(
        _chain(),
        _request(historical_volatility=0.20),
        max_recommendations=10,
    )

    assert result.recommendations
    assert all(
        any("IV/HV ratio is 1.20" in reason for reason in item.key_reasons)
        for item in result.recommendations
    )


def test_leaps_under_90_dte_carry_a_roll_prompt() -> None:
    chain = pd.DataFrame(
        [
            {
                "symbol": "US.AAPL20260719C100000",
                "option_type": "CALL",
                "expiry": "2026-07-19",
                "strike": 100.0,
                "bid": 5.0,
                "ask": 5.4,
                "implied_volatility": 0.25,
                "delta": 0.80,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 60,
            },
            {
                "symbol": "US.AAPL20260719C110000",
                "option_type": "CALL",
                "expiry": "2026-07-19",
                "strike": 110.0,
                "bid": 1.3,
                "ask": 1.5,
                "implied_volatility": 0.24,
                "delta": 0.30,
                "gamma": 0.02,
                "theta": -0.04,
                "vega": 0.12,
                "open_interest": 500,
                "volume": 80,
                "option_expiry_date_distance": 60,
            },
            {
                "symbol": "US.AAPL20260719P100000",
                "option_type": "PUT",
                "expiry": "2026-07-19",
                "strike": 100.0,
                "bid": 4.5,
                "ask": 4.9,
                "implied_volatility": 0.25,
                "delta": -0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 60,
            },
        ]
    )

    result = run_buy_side_decision(
        chain,
        _request(
            view_type="long_term_aggressive_bullish",
            target_price=120.0,
            target_date="2027-12-17",
            preferred_dte_range=(1, 89),
            max_loss_budget=1000.0,
        ),
        max_recommendations=10,
    )

    assert result.recommendations
    assert all(item.strategy_type.startswith("leaps") for item in result.recommendations)
    assert all(
        any("under 90 days" in risk for risk in item.key_risks) for item in result.recommendations
    )


def test_market_regime_penalty_is_reported() -> None:
    panic = VixRegimeSnapshot(
        volatility_regime="Panic",
        w_vix=0.35,
        vix_density=0.9,
        term_ratio=1.1,
        vix_mean=40,
        vix_threshold=25,
    )

    result = run_buy_side_decision(
        _chain(),
        _request(view_type="short_term_speculative_bullish"),
        market_regime=panic,
        max_recommendations=8,
    )

    assert result.recommendations
    assert all(item.market_regime == "Panic" for item in result.recommendations)
    assert any(item.market_regime_penalty < 0 for item in result.recommendations)
    assert any("MARKET_REGIME_PANIC" in item.warnings for item in result.recommendations)


def test_user_scenario_ev_is_attached_when_input_is_provided() -> None:
    result = run_buy_side_decision(
        _chain(),
        _request(
            user_scenarios=[
                BuySideUserScenarioPnL(
                    label="bull",
                    probability=0.4,
                    spot_change_pct=10,
                    iv_change_vol_points=0,
                    days_passed=7,
                ),
                BuySideUserScenarioPnL(
                    label="base",
                    probability=0.4,
                    spot_change_pct=0,
                    iv_change_vol_points=-5,
                    days_passed=7,
                ),
                BuySideUserScenarioPnL(
                    label="bear",
                    probability=0.2,
                    spot_change_pct=-8,
                    iv_change_vol_points=-5,
                    days_passed=7,
                ),
            ]
        ),
        max_recommendations=3,
    )

    assert result.recommendations
    assert result.recommendations[0].scenario_ev is not None
    assert len(result.recommendations[0].scenario_ev.contributions) == 3
