from __future__ import annotations

import pandas as pd

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
            (95.0, 0.72, 8.5, -0.05, 0.18, 900),
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
