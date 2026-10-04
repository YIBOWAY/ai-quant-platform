import math
from datetime import date, timedelta

import pytest

from quant_system.options.seller_score import (
    RECOMMENDATION_SCORE_MODEL,
    evaluate_seller_recommendation,
    historical_volatility_from_ratio,
    is_us_market_session,
    latest_us_market_session,
    score_seller_contract,
)


def _physical_payout(
    *,
    strategy_type: str,
    strike: float,
    spot: float,
    sigma: float,
    mu: float,
    dte: int,
) -> float:
    # Independent reimplementation of the closed-form lognormal expected payout.
    time_years = dte / 365
    vol_sqrt_t = sigma * math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (mu + sigma * sigma / 2) * time_years) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    grown = spot * math.exp(mu * time_years)
    if strategy_type == "sell_put":
        return strike * cdf(-d2) - grown * cdf(-d1)
    return grown * cdf(d1) - strike * cdf(d2)


def test_seller_score_uses_five_legs_and_renormalizes_without_iv_rank():
    breakdown = score_seller_contract(
        annualized_yield=0.30,  # 30% APR → 50 yield score
        spread_pct=0.02,
        open_interest=600,
        volume=100,
        delta=-0.25,
        hv_iv_ratio=0.60,
        iv_rank=None,
        market_regime_penalty=0.0,
    )
    assert breakdown.iv_rank_score is None
    assert "iv_rank" not in breakdown.weights_used
    assert breakdown.yield_score == 50.0
    assert breakdown.liquidity_score == 100.0
    assert abs(breakdown.composite - (
        50.0 * 0.30 + 100.0 * 0.25 + 75.0 * 0.20 + 50.0 * 0.15
    ) / 0.90) < 1e-6


def test_seller_score_applies_regime_penalty():
    raw = score_seller_contract(
        annualized_yield=0.60,
        spread_pct=0.02,
        open_interest=600,
        volume=100,
        delta=-0.20,
        hv_iv_ratio=0.50,
        iv_rank=80,
        market_regime_penalty=0.0,
    )
    penalized = score_seller_contract(
        annualized_yield=0.60,
        spread_pct=0.02,
        open_interest=600,
        volume=100,
        delta=-0.20,
        hv_iv_ratio=0.50,
        iv_rank=80,
        market_regime_penalty=-15.0,
    )
    assert penalized.composite == max(0.0, raw.composite - 15.0)


def test_sell_put_recommendation_uses_extrinsic_ev_and_liquidity() -> None:
    result = evaluate_seller_recommendation(
        strategy_type="sell_put",
        strike=95.0,
        underlying_price=100.0,
        mid=3.0,
        spread_pct=0.02,
        open_interest=500.0,
        delta=-0.20,
        days_to_expiry=30,
        implied_volatility=0.30,
        iv_rank=55.0,
        risk_free_rate=0.04,
        run_date="2026-05-01",
        expiry="2026-05-31",
        earnings_date="2026-06-15",
        is_etf=False,
        ex_dividend_date=None,
        dividend_per_share=None,
        quote_as_of="2026-05-01T20:00:00Z",
    )

    payout = _physical_payout(
        strategy_type="sell_put",
        strike=95.0,
        spot=100.0,
        sigma=0.30,
        mu=0.04 + 0.04,
        dte=30,
    )
    expected_value = 3.0 - payout
    annualized_ev = expected_value / 95.0 * 365 / 30
    expected_excess = annualized_ev - 0.04

    assert result.hard_gate_passed is True
    assert result.rejection_reasons == ()
    assert result.extrinsic_value == pytest.approx(3.0)
    assert result.gross_annualized_yield == pytest.approx(3 / 95 * 365 / 30)
    assert result.pop == pytest.approx(0.80)
    assert result.otm_pct == pytest.approx(0.05)
    assert result.breakeven == pytest.approx(92.0)
    assert result.take_profit_50_price == pytest.approx(1.5)
    assert result.manage_at_21_dte == "2026-05-10"
    assert result.expected_value == pytest.approx(expected_value)
    assert result.excess_annualized_ev == pytest.approx(expected_excess)
    assert result.liquidity_factor == pytest.approx(1.0)
    # Ordering score is annualized physical EV x liquidity, without the
    # risk-free subtraction used by the display-only excess metric.
    assert result.recommendation_score == pytest.approx(annualized_ev)
    assert result.recommendation_score != pytest.approx(expected_excess)
    assert result.recommendation_score_model == RECOMMENDATION_SCORE_MODEL
    assert result.quote_as_of == "2026-05-01T20:00:00Z"


def _valid_recommendation_kwargs() -> dict:
    return {
        "strategy_type": "sell_put",
        "strike": 95.0,
        "underlying_price": 100.0,
        "mid": 3.0,
        "spread_pct": 0.02,
        "open_interest": 500.0,
        "delta": -0.20,
        "days_to_expiry": 30,
        "implied_volatility": 0.30,
        "iv_rank": 55.0,
        "risk_free_rate": 0.04,
        "run_date": "2026-05-01",
        "expiry": "2026-05-31",
        "earnings_date": "2026-06-15",
        "is_etf": False,
        "ex_dividend_date": None,
        "dividend_per_share": None,
        "quote_as_of": "2026-05-01T20:00:00Z",
    }


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"mid": None}, "mid_missing"),
        ({"mid": 0.049}, "mid_below_minimum"),
        ({"spread_pct": None}, "spread_missing"),
        ({"spread_pct": 0.051}, "spread_above_maximum"),
        ({"open_interest": None}, "open_interest_missing"),
        ({"open_interest": 99.0}, "open_interest_below_minimum"),
        ({"delta": None}, "delta_missing"),
        ({"delta": -0.149}, "delta_outside_range"),
        ({"delta": -0.351}, "delta_outside_range"),
        ({"days_to_expiry": None}, "dte_missing"),
        ({"days_to_expiry": 4, "expiry": "2026-05-05"}, "dte_outside_range"),
        ({"days_to_expiry": 61, "expiry": "2026-07-01"}, "dte_outside_range"),
        ({"implied_volatility": None}, "implied_volatility_missing"),
        ({"implied_volatility": 0.0}, "implied_volatility_invalid"),
        ({"implied_volatility": float("nan")}, "implied_volatility_invalid"),
        ({"iv_rank": float("nan")}, "iv_rank_invalid"),
        ({"risk_free_rate": None}, "risk_free_rate_missing"),
        ({"risk_free_rate": float("nan")}, "risk_free_rate_invalid"),
        ({"quote_as_of": None}, "quote_as_of_missing"),
        ({"spread_pct": -0.01}, "spread_invalid"),
        ({"open_interest": float("nan")}, "open_interest_invalid"),
        ({"earnings_date": None}, "earnings_data_missing"),
        ({"earnings_date": "2026-05-31"}, "earnings_within_dte"),
    ],
)
def test_recommendation_hard_gates_exclude_missing_or_out_of_range_inputs(
    override: dict,
    reason: str,
) -> None:
    kwargs = {**_valid_recommendation_kwargs(), **override}

    result = evaluate_seller_recommendation(**kwargs)

    assert result.hard_gate_passed is False
    assert reason in result.rejection_reasons
    assert result.recommendation_score is None


def test_recommendation_allows_warming_iv_rank_without_faking_a_value() -> None:
    result = evaluate_seller_recommendation(
        **{**_valid_recommendation_kwargs(), "iv_rank": None}
    )

    assert result.hard_gate_passed is True
    assert result.rejection_reasons == ()
    assert result.recommendation_score is not None


def test_covered_call_requires_real_ex_dividend_inputs() -> None:
    kwargs = {
        **_valid_recommendation_kwargs(),
        "strategy_type": "covered_call",
        "strike": 105.0,
        "delta": 0.20,
    }

    result = evaluate_seller_recommendation(**kwargs)

    assert result.hard_gate_passed is False
    assert result.rejection_reasons == ("ex_dividend_data_missing",)


def test_covered_call_past_ex_date_cannot_prove_next_dividend_is_outside_window() -> None:
    result = evaluate_seller_recommendation(**{
        **_valid_recommendation_kwargs(),
        "strategy_type": "covered_call",
        "strike": 105.0,
        "delta": 0.20,
        "ex_dividend_date": "2026-04-01",
        "dividend_per_share": 0.27,
    })
    assert result.hard_gate_passed is False
    assert result.rejection_reasons == ("ex_dividend_date_past",)


def test_covered_call_rejects_in_window_dividend_not_covered_by_extrinsic() -> None:
    kwargs = {
        **_valid_recommendation_kwargs(),
        "strategy_type": "covered_call",
        "strike": 105.0,
        "delta": 0.20,
        "ex_dividend_date": "2026-05-15",
        "dividend_per_share": 3.0,
    }

    result = evaluate_seller_recommendation(**kwargs)

    assert result.hard_gate_passed is False
    assert result.rejection_reasons == (
        "covered_call_extrinsic_not_above_dividend",
    )
    assert result.ex_dividend_in_window is True


def test_covered_call_rejects_non_finite_dividend_evidence() -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "strategy_type": "covered_call",
            "strike": 105.0,
            "delta": 0.20,
            "ex_dividend_date": "2026-06-15",
            "dividend_per_share": float("nan"),
        }
    )

    assert result.hard_gate_passed is False
    assert "dividend_per_share_invalid" in result.rejection_reasons


def test_covered_call_accepts_source_asserted_zero_dividend() -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "strategy_type": "covered_call",
            "strike": 105.0,
            "delta": 0.20,
            "ex_dividend_date": None,
            "dividend_per_share": 0.0,
        }
    )

    assert result.hard_gate_passed is True
    assert result.rejection_reasons == ()
    assert result.ex_dividend_in_window is False
    payout = _physical_payout(
        strategy_type="covered_call",
        strike=105.0,
        spot=100.0,
        sigma=0.30,
        mu=0.04 + 0.04,
        dte=30,
    )
    assert result.expected_value == pytest.approx(3.0 - payout)


def test_covered_call_without_ex_date_but_positive_dividend_stays_excluded() -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "strategy_type": "covered_call",
            "strike": 105.0,
            "delta": 0.20,
            "ex_dividend_date": None,
            "dividend_per_share": 0.55,
        }
    )

    assert result.hard_gate_passed is False
    assert result.rejection_reasons == ("ex_dividend_data_missing",)


def test_recommendation_uses_min_of_iv_and_hv_when_hv_available() -> None:
    baseline = evaluate_seller_recommendation(**_valid_recommendation_kwargs())
    hv_above_iv = evaluate_seller_recommendation(
        **{**_valid_recommendation_kwargs(), "historical_volatility": 0.60}
    )
    hv_below_iv = evaluate_seller_recommendation(
        **{**_valid_recommendation_kwargs(), "historical_volatility": 0.15}
    )

    assert baseline.hard_gate_passed is True
    # HV above IV leaves sigma = IV unchanged.
    assert hv_above_iv.expected_value == pytest.approx(baseline.expected_value)
    # HV below IV shrinks sigma and therefore raises EV.
    payout = _physical_payout(
        strategy_type="sell_put",
        strike=95.0,
        spot=100.0,
        sigma=0.15,
        mu=0.04 + 0.04,
        dte=30,
    )
    assert hv_below_iv.expected_value == pytest.approx(3.0 - payout)
    assert hv_below_iv.expected_value > baseline.expected_value


@pytest.mark.parametrize("hv", [None, 0.0, -0.2, float("nan")])
def test_recommendation_falls_back_to_iv_when_hv_missing_or_invalid(
    hv: float | None,
) -> None:
    baseline = evaluate_seller_recommendation(**_valid_recommendation_kwargs())
    result = evaluate_seller_recommendation(
        **{**_valid_recommendation_kwargs(), "historical_volatility": hv}
    )

    assert result.hard_gate_passed is True
    assert result.expected_value == pytest.approx(baseline.expected_value)


def test_recommendation_zero_equity_risk_premium_uses_risk_free_drift() -> None:
    result = evaluate_seller_recommendation(
        **{**_valid_recommendation_kwargs(), "equity_risk_premium": 0.0}
    )

    payout = _physical_payout(
        strategy_type="sell_put",
        strike=95.0,
        spot=100.0,
        sigma=0.30,
        mu=0.04,
        dte=30,
    )
    assert result.hard_gate_passed is True
    assert result.expected_value == pytest.approx(3.0 - payout)


def test_historical_volatility_from_ratio_recovers_hv() -> None:
    assert historical_volatility_from_ratio(0.5, 0.32) == pytest.approx(0.16)
    assert historical_volatility_from_ratio(None, 0.32) is None
    assert historical_volatility_from_ratio(0.5, None) is None
    assert historical_volatility_from_ratio(float("nan"), 0.32) is None
    assert historical_volatility_from_ratio(0.0, 0.32) is None
    assert historical_volatility_from_ratio(0.5, 0.0) is None


def test_manage_at_21_dte_never_precedes_the_scan_date() -> None:
    kwargs = {
        **_valid_recommendation_kwargs(),
        "days_to_expiry": 5,
        "expiry": "2026-05-06",
    }

    result = evaluate_seller_recommendation(**kwargs)

    assert result.hard_gate_passed is True
    assert result.rejection_reasons == ()
    assert result.manage_at_21_dte == "2026-05-01"


@pytest.mark.parametrize(
    "mid",
    [1.0, float("nan")],
)
def test_recommendation_rejects_negative_or_non_finite_extrinsic(mid: float) -> None:
    kwargs = {
        **_valid_recommendation_kwargs(),
        "strike": 105.0,
        "mid": mid,
    }

    result = evaluate_seller_recommendation(**kwargs)

    assert result.hard_gate_passed is False
    assert "extrinsic_value_invalid" in result.rejection_reasons


@pytest.mark.parametrize(
    ("delta", "days_to_expiry"),
    [(-0.15, 5), (-0.35, 60)],
)
def test_recommendation_hard_gate_boundaries_are_inclusive(
    delta: float,
    days_to_expiry: int,
) -> None:
    kwargs = {
        **_valid_recommendation_kwargs(),
        "mid": 0.05,
        "spread_pct": 0.05,
        "open_interest": 100.0,
        "delta": delta,
        "days_to_expiry": days_to_expiry,
        "expiry": (date(2026, 5, 1) + timedelta(days=days_to_expiry)).isoformat(),
        "earnings_date": "2026-08-01",
        "iv_rank": 0.0,
        "implied_volatility": 0.001,
        "risk_free_rate": 0.0,
    }

    result = evaluate_seller_recommendation(**kwargs)

    assert result.hard_gate_passed is True


@pytest.mark.parametrize(
    ("quote_as_of", "reason"),
    [
        ("2026-07-02 09:30:00", "quote_stale"),
        ("2026-08-24 09:30:00", "quote_future"),
    ],
)
def test_recommendation_rejects_quote_outside_expected_market_session(
    quote_as_of: str,
    reason: str,
) -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "run_date": "2026-08-21",
            "expiry": "2026-09-18",
            "days_to_expiry": 28,
            "earnings_date": "2026-10-15",
            "quote_as_of": quote_as_of,
        }
    )

    assert result.hard_gate_passed is False
    assert reason in result.rejection_reasons
    assert result.recommendation_score is None


def test_recommendation_rejects_same_session_quote_after_observed_at() -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "run_date": "2026-08-21",
            "expiry": "2026-09-18",
            "days_to_expiry": 28,
            "earnings_date": "2026-10-15",
            "quote_as_of": "2026-08-21 16:00:00",
            "observed_at": "2026-08-21T19:00:00Z",
        }
    )

    assert result.hard_gate_passed is False
    assert "quote_future" in result.rejection_reasons
    assert result.recommendation_score is None


def test_weekend_scan_uses_friday_session_for_event_and_management_dates() -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "strategy_type": "covered_call",
            "strike": 105.0,
            "delta": 0.20,
            "run_date": "2026-08-22",
            "expiry": "2026-08-28",
            "days_to_expiry": 7,
            "earnings_date": "2026-10-15",
            "ex_dividend_date": "2026-08-21",
            "dividend_per_share": 0.50,
            "quote_as_of": "2026-08-21 15:59:00",
            "observed_at": "2026-08-22T12:00:00Z",
        }
    )

    assert result.hard_gate_passed is True
    assert result.ex_dividend_in_window is True
    assert result.manage_at_21_dte == "2026-08-21"


def test_recommendation_rejects_provider_dte_inconsistent_with_market_session() -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "run_date": "2026-08-22",
            "expiry": "2026-08-28",
            "days_to_expiry": 6,
            "earnings_date": "2026-10-15",
            "quote_as_of": "2026-08-21 15:59:00",
            "observed_at": "2026-08-22T12:00:00Z",
        }
    )

    assert result.hard_gate_passed is False
    assert "dte_inconsistent" in result.rejection_reasons


def test_non_positive_excess_ev_is_not_a_recommendation() -> None:
    result = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "mid": 1.0,
        }
    )

    assert result.hard_gate_passed is False
    assert result.rejection_reasons == ("non_positive_excess_ev",)
    assert result.recommendation_score is None


def test_positive_ev_ranking_rewards_more_liquid_contracts() -> None:
    liquid = evaluate_seller_recommendation(**_valid_recommendation_kwargs())
    threshold_liquidity = evaluate_seller_recommendation(
        **{
            **_valid_recommendation_kwargs(),
            "spread_pct": 0.05,
            "open_interest": 100.0,
        }
    )

    assert liquid.hard_gate_passed is True
    assert threshold_liquidity.hard_gate_passed is True
    assert liquid.excess_annualized_ev == pytest.approx(
        threshold_liquidity.excess_annualized_ev
    )
    assert liquid.liquidity_factor > threshold_liquidity.liquidity_factor
    assert liquid.recommendation_score > threshold_liquidity.recommendation_score


@pytest.mark.parametrize("active_date", [date(2021, 12, 31), date(2027, 12, 31)])
def test_new_year_on_saturday_does_not_close_previous_friday(
    active_date: date,
) -> None:
    assert is_us_market_session(active_date) is True
    assert latest_us_market_session(active_date) == active_date
