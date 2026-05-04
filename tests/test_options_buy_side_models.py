from __future__ import annotations

import pytest
from pydantic import ValidationError

from quant_system.options.models import (
    BuySideScenarioInput,
    BuySideStrategyLeg,
    BuySideThesisInput,
)


def test_buy_side_strategy_leg_computes_quote_and_contract_fields() -> None:
    leg = BuySideStrategyLeg(
        symbol="US.AAPL260619C250000",
        option_type="CALL",
        side="long",
        expiry="2026-06-19",
        strike=250.0,
        spot=280.0,
        as_of_date="2026-05-20",
        bid=10.0,
        ask=10.5,
        implied_volatility=0.24,
        delta=0.55,
        gamma=0.02,
        theta=-0.04,
        vega=0.18,
        open_interest=1200,
        volume=300,
    )

    assert leg.mid_price == pytest.approx(10.25)
    assert leg.spread_abs == pytest.approx(0.5)
    assert leg.spread_pct == pytest.approx(0.5 / 10.25)
    assert leg.call_moneyness == pytest.approx(280.0 / 250.0)
    assert leg.contract_size == 100
    assert leg.dte == 30
    assert leg.is_tradable is True
    assert leg.warnings == []


def test_buy_side_strategy_leg_flags_missing_or_invalid_quotes() -> None:
    missing = BuySideStrategyLeg(
        symbol="US.AAPL260619C250000",
        option_type="CALL",
        side="long",
        expiry="2026-06-19",
        strike=250.0,
        spot=280.0,
    )
    crossed = BuySideStrategyLeg(
        symbol="US.AAPL260619C250000",
        option_type="CALL",
        side="long",
        expiry="2026-06-19",
        strike=250.0,
        spot=280.0,
        bid=11.0,
        ask=10.0,
    )

    assert "missing_quote" in missing.warnings
    assert missing.is_tradable is False
    assert "invalid_bid_ask" in crossed.warnings
    assert crossed.mid_price is None
    assert crossed.is_tradable is False


def test_buy_side_strategy_leg_rejects_negative_quote_values() -> None:
    with pytest.raises(ValidationError):
        BuySideStrategyLeg(
            symbol="US.AAPL260619C250000",
            option_type="CALL",
            side="long",
            expiry="2026-06-19",
            strike=250.0,
            spot=280.0,
            bid=-0.01,
            ask=1.0,
        )


def test_buy_side_strategy_leg_rejects_invalid_expiration() -> None:
    with pytest.raises(ValidationError):
        BuySideStrategyLeg(
            symbol="US.AAPL260619C250000",
            option_type="CALL",
            side="long",
            expiry="not-a-date",
            strike=250.0,
            spot=280.0,
            bid=1.0,
            ask=1.2,
        )


def test_buy_side_thesis_defaults_volatility_view_to_auto() -> None:
    thesis = BuySideThesisInput(
        ticker="AAPL",
        view_type="long_term_conservative_bullish",
        target_price=320.0,
        target_date="2026-12-18",
    )

    assert thesis.volatility_view == "auto"
    assert thesis.risk_preference == "balanced"
    assert thesis.event_risk == "none"


def test_buy_side_scenario_input_accepts_user_scenarios() -> None:
    scenarios = BuySideScenarioInput(
        spot=280.0,
        implied_volatility=0.24,
        days_to_expiry=120,
        user_scenarios=[
            {
                "label": "base case",
                "probability": 0.6,
                "spot_change_pct": 0.12,
                "iv_change_vol_points": -3.0,
            }
        ],
    )

    assert scenarios.user_scenarios[0].label == "base case"
    assert scenarios.user_scenarios[0].probability == pytest.approx(0.6)
