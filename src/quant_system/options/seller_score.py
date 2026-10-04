from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

_LEG_WEIGHTS = {
    "yield": 0.30,
    "liquidity": 0.25,
    "delta_safety": 0.20,
    "iv_edge": 0.15,
    "iv_rank": 0.10,
}

RECOMMENDATION_SCORE_MODEL = "seller_ev_liquidity_v1"
# Physical-measure drift above the risk-free rate used by the seller EV model.
DEFAULT_EQUITY_RISK_PREMIUM = 0.04
_NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class SellerRecommendationEvaluation:
    hard_gate_passed: bool
    rejection_reasons: tuple[str, ...]
    extrinsic_value: float | None = None
    gross_annualized_yield: float | None = None
    pop: float | None = None
    otm_pct: float | None = None
    ex_dividend_date: str | None = None
    ex_dividend_in_window: bool = False
    dividend_per_share: float | None = None
    breakeven: float | None = None
    take_profit_50_price: float | None = None
    manage_at_21_dte: str | None = None
    expected_value: float | None = None
    excess_annualized_ev: float | None = None
    liquidity_factor: float | None = None
    recommendation_score: float | None = None
    recommendation_score_model: str = RECOMMENDATION_SCORE_MODEL
    quote_as_of: str | None = None


@dataclass(frozen=True)
class RecommendationQuoteResolution:
    scan_date: date
    expected_session: date
    quote_at_utc: datetime | None
    quote_session: date | None
    canonical_as_of: str | None
    reason: str | None


class SellerScoreBreakdown(BaseModel):
    yield_score: float | None = Field(default=None, ge=0, le=100)
    liquidity_score: float | None = Field(default=None, ge=0, le=100)
    delta_safety_score: float | None = Field(default=None, ge=0, le=100)
    iv_edge_score: float | None = Field(default=None, ge=0, le=100)
    iv_rank_score: float | None = Field(default=None, ge=0, le=100)
    composite: float = Field(ge=0, le=100)
    weights_used: dict[str, float]


def score_seller_contract(
    *,
    annualized_yield: float | None,
    spread_pct: float | None,
    open_interest: float | None,
    volume: float | None,
    delta: float | None,
    hv_iv_ratio: float | None,
    iv_rank: float | None,
    market_regime_penalty: float = 0.0,
) -> SellerScoreBreakdown:
    yield_score = _clip((annualized_yield / 0.60) * 100.0) if annualized_yield is not None else None
    liquidity_score = (_spread_leg(spread_pct) + _open_interest_leg(open_interest)) / 2.0
    delta_safety_score = _clip((1.0 - min(abs(delta), 1.0)) * 100.0) if delta is not None else None
    iv_edge_score = _clip((1.2 - hv_iv_ratio) / 1.2 * 100.0) if hv_iv_ratio is not None else None
    iv_rank_score = _clip(iv_rank) if iv_rank is not None else None
    legs = {
        "yield": yield_score,
        "liquidity": liquidity_score,
        "delta_safety": delta_safety_score,
        "iv_edge": iv_edge_score,
        "iv_rank": iv_rank_score,
    }
    weights_used = {name: weight for name, weight in _LEG_WEIGHTS.items() if legs[name] is not None}
    # Python 3.11 and 3.12 use different float summation algorithms. Persisted
    # scores are reread by both runtimes, so keep this calculation explicit.
    total_weight = math.fsum(weights_used.values())
    raw = (
        math.fsum(legs[name] * weight for name, weight in weights_used.items()) / total_weight
        if total_weight > 0
        else 0.0
    )
    return SellerScoreBreakdown(
        yield_score=yield_score,
        liquidity_score=liquidity_score,
        delta_safety_score=delta_safety_score,
        iv_edge_score=iv_edge_score,
        iv_rank_score=iv_rank_score,
        composite=_clip(raw + market_regime_penalty),
        weights_used=weights_used,
    )


def evaluate_seller_recommendation(
    *,
    strategy_type: Literal["sell_put", "covered_call"],
    strike: float,
    underlying_price: float,
    mid: float | None,
    spread_pct: float | None,
    open_interest: float | None,
    delta: float | None,
    days_to_expiry: int | None,
    implied_volatility: float | None,
    iv_rank: float | None,
    risk_free_rate: float | None,
    run_date: str,
    expiry: str,
    earnings_date: str | None,
    is_etf: bool,
    ex_dividend_date: str | None,
    dividend_per_share: float | None,
    quote_as_of: str | None,
    observed_at: str | None = None,
    historical_volatility: float | None = None,
    equity_risk_premium: float = DEFAULT_EQUITY_RISK_PREMIUM,
) -> SellerRecommendationEvaluation:
    expiry_date = date.fromisoformat(expiry)
    active_run_date = latest_us_market_session(date.fromisoformat(run_date))
    derived_days_to_expiry = (expiry_date - active_run_date).days
    intrinsic_value = (
        max(strike - underlying_price, 0.0)
        if strategy_type == "sell_put"
        else max(underlying_price - strike, 0.0)
    )
    candidate_extrinsic_value = float(mid) - intrinsic_value if mid is not None else None
    active_ex_dividend_date = (
        date.fromisoformat(ex_dividend_date) if ex_dividend_date is not None else None
    )
    ex_dividend_in_window = bool(
        active_ex_dividend_date is not None
        and active_run_date <= active_ex_dividend_date <= expiry_date
    )
    reasons: list[str] = []
    if mid is None:
        reasons.append("mid_missing")
    elif mid < 0.05:
        reasons.append("mid_below_minimum")
    if spread_pct is None:
        reasons.append("spread_missing")
    elif not math.isfinite(spread_pct) or spread_pct < 0:
        reasons.append("spread_invalid")
    elif spread_pct > 0.05:
        reasons.append("spread_above_maximum")
    if open_interest is None:
        reasons.append("open_interest_missing")
    elif not math.isfinite(open_interest):
        reasons.append("open_interest_invalid")
    elif open_interest < 100:
        reasons.append("open_interest_below_minimum")
    if delta is None:
        reasons.append("delta_missing")
    elif not 0.15 <= abs(delta) <= 0.35:
        reasons.append("delta_outside_range")
    if days_to_expiry is None:
        reasons.append("dte_missing")
    elif days_to_expiry != derived_days_to_expiry:
        reasons.append("dte_inconsistent")
    if not 5 <= derived_days_to_expiry <= 60:
        reasons.append("dte_outside_range")
    if implied_volatility is None:
        reasons.append("implied_volatility_missing")
    elif not math.isfinite(implied_volatility) or implied_volatility <= 0:
        reasons.append("implied_volatility_invalid")
    if iv_rank is not None and (
        not math.isfinite(iv_rank) or not 0 <= iv_rank <= 100
    ):
        reasons.append("iv_rank_invalid")
    if risk_free_rate is None:
        reasons.append("risk_free_rate_missing")
    elif not math.isfinite(risk_free_rate) or risk_free_rate < 0:
        reasons.append("risk_free_rate_invalid")
    quote_resolution = resolve_recommendation_quote(
        run_date=run_date,
        quote_as_of=quote_as_of,
        observed_at=observed_at,
    )
    if quote_resolution.reason is not None:
        reasons.append(quote_resolution.reason)
    canonical_quote_as_of = quote_resolution.canonical_as_of or quote_as_of
    if not is_etf:
        if earnings_date is None:
            reasons.append("earnings_data_missing")
        elif date.fromisoformat(earnings_date) <= expiry_date:
            reasons.append("earnings_within_dte")
    if strategy_type == "covered_call":
        # (None, 0.0) is the dividend source's explicit no-dividend assertion
        # and passes; (None, None) stays honest missing evidence.
        no_dividend_asserted = ex_dividend_date is None and dividend_per_share == 0.0
        if not no_dividend_asserted:
            if ex_dividend_date is None or dividend_per_share is None:
                reasons.append("ex_dividend_data_missing")
            elif not math.isfinite(dividend_per_share) or dividend_per_share < 0:
                reasons.append("dividend_per_share_invalid")
            elif active_ex_dividend_date < active_run_date:
                # The previous distribution cannot establish the next ex-date.
                reasons.append("ex_dividend_date_past")
            elif (
                ex_dividend_in_window
                and candidate_extrinsic_value is not None
                and candidate_extrinsic_value <= dividend_per_share
            ):
                reasons.append("covered_call_extrinsic_not_above_dividend")
    if not math.isfinite(strike) or strike <= 0:
        reasons.append("strike_invalid")
    if not math.isfinite(underlying_price) or underlying_price <= 0:
        reasons.append("underlying_price_invalid")
    if candidate_extrinsic_value is not None and (
        not math.isfinite(candidate_extrinsic_value) or candidate_extrinsic_value < 0
    ):
        reasons.append("extrinsic_value_invalid")
    if reasons:
        return SellerRecommendationEvaluation(
            hard_gate_passed=False,
            rejection_reasons=tuple(reasons),
            extrinsic_value=candidate_extrinsic_value,
            ex_dividend_date=ex_dividend_date,
            ex_dividend_in_window=ex_dividend_in_window,
            dividend_per_share=dividend_per_share,
            quote_as_of=canonical_quote_as_of,
        )

    assert mid is not None
    assert delta is not None
    assert days_to_expiry is not None
    assert implied_volatility is not None
    assert risk_free_rate is not None
    active_mid = float(mid)
    active_delta = float(delta)
    active_dte = derived_days_to_expiry
    active_iv = float(implied_volatility)
    active_rate = float(risk_free_rate)
    assert candidate_extrinsic_value is not None
    extrinsic_value = candidate_extrinsic_value
    # EV = extrinsic premium minus the physical expected payout. The payout is
    # the closed-form lognormal conditional expectation with volatility
    # sigma = min(IV, HV) when HV is available (IV otherwise) and drift
    # mu = risk_free_rate + equity_risk_premium.
    physical_volatility = active_iv
    if (
        historical_volatility is not None
        and math.isfinite(historical_volatility)
        and historical_volatility > 0
    ):
        physical_volatility = min(active_iv, float(historical_volatility))
    expected_payout = _expected_lognormal_payout(
        strategy_type=strategy_type,
        strike=strike,
        underlying_price=underlying_price,
        volatility=physical_volatility,
        drift=active_rate + equity_risk_premium,
        time_years=active_dte / 365,
    )
    expected_value = extrinsic_value - expected_payout
    gross_annualized_yield = extrinsic_value / strike * 365 / active_dte
    annualized_ev = expected_value / strike * 365 / active_dte
    excess_annualized_ev = annualized_ev - active_rate
    liquidity_factor = (
        _spread_leg(spread_pct) + _open_interest_leg(open_interest)
    ) / 200.0
    recommendation_score = annualized_ev * liquidity_factor
    otm_pct = (
        (underlying_price - strike) / underlying_price
        if strategy_type == "sell_put"
        else (strike - underlying_price) / underlying_price
    )
    breakeven = (
        strike - active_mid
        if strategy_type == "sell_put"
        else underlying_price - active_mid
    )
    if not math.isfinite(expected_value) or expected_value <= 0:
        return SellerRecommendationEvaluation(
            hard_gate_passed=False,
            rejection_reasons=("non_positive_excess_ev",),
            extrinsic_value=extrinsic_value,
            gross_annualized_yield=gross_annualized_yield,
            pop=1.0 - abs(active_delta),
            otm_pct=otm_pct,
            ex_dividend_date=ex_dividend_date,
            ex_dividend_in_window=ex_dividend_in_window,
            dividend_per_share=dividend_per_share,
            breakeven=breakeven,
            take_profit_50_price=active_mid / 2.0,
            manage_at_21_dte=max(
                active_run_date,
                expiry_date - timedelta(days=21),
            ).isoformat(),
            expected_value=expected_value,
            excess_annualized_ev=excess_annualized_ev,
            liquidity_factor=liquidity_factor,
            quote_as_of=canonical_quote_as_of,
        )
    return SellerRecommendationEvaluation(
        hard_gate_passed=True,
        rejection_reasons=(),
        extrinsic_value=extrinsic_value,
        gross_annualized_yield=gross_annualized_yield,
        pop=1.0 - abs(active_delta),
        otm_pct=otm_pct,
        ex_dividend_date=ex_dividend_date,
        ex_dividend_in_window=ex_dividend_in_window,
        dividend_per_share=dividend_per_share,
        breakeven=breakeven,
        take_profit_50_price=active_mid / 2.0,
        manage_at_21_dte=max(
            active_run_date,
            expiry_date - timedelta(days=21),
        ).isoformat(),
        expected_value=expected_value,
        excess_annualized_ev=excess_annualized_ev,
        liquidity_factor=liquidity_factor,
        recommendation_score=recommendation_score,
        quote_as_of=canonical_quote_as_of,
    )


def historical_volatility_from_ratio(
    hv_iv_ratio: float | None,
    implied_volatility: float | None,
) -> float | None:
    """Recover HV carried as hv_iv_ratio x IV; None when either input is absent."""
    if hv_iv_ratio is None or implied_volatility is None:
        return None
    if not (math.isfinite(hv_iv_ratio) and math.isfinite(implied_volatility)):
        return None
    if hv_iv_ratio <= 0 or implied_volatility <= 0:
        return None
    return hv_iv_ratio * implied_volatility


def _expected_lognormal_payout(
    *,
    strategy_type: Literal["sell_put", "covered_call"],
    strike: float,
    underlying_price: float,
    volatility: float,
    drift: float,
    time_years: float,
) -> float:
    # E[max(K - S_T, 0)] / E[max(S_T - K, 0)] with S_T lognormal and
    # E[S_T] = S * exp(drift * T), via the closed-form conditional means.
    vol_sqrt_t = volatility * math.sqrt(time_years)
    d1 = (
        math.log(underlying_price / strike)
        + (drift + 0.5 * volatility * volatility) * time_years
    ) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    grown_price = underlying_price * math.exp(drift * time_years)
    if strategy_type == "sell_put":
        return strike * _norm_cdf(-d2) - grown_price * _norm_cdf(-d1)
    return grown_price * _norm_cdf(d1) - strike * _norm_cdf(d2)


def _norm_cdf(value: float) -> float:
    return 0.5 * math.erfc(-value / math.sqrt(2.0))


def _spread_leg(spread_pct: float | None) -> float:
    if spread_pct is None:
        return 0.0
    if spread_pct <= 0.03:
        return 100.0
    if spread_pct <= 0.08:
        return 40.0
    return 10.0


def _open_interest_leg(open_interest: float | None) -> float:
    if open_interest is None:
        return 0.0
    if open_interest >= 500:
        return 100.0
    if open_interest >= 100:
        return 70.0
    if open_interest >= 50:
        return 30.0
    return 10.0


def _clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return min(max(value, lower), upper)


def recommendation_quote_session(
    *,
    run_date: str,
    quote_as_of: str | None,
    observed_at: str | None = None,
) -> tuple[str | None, date | None]:
    resolved = resolve_recommendation_quote(
        run_date=run_date,
        quote_as_of=quote_as_of,
        observed_at=observed_at,
    )
    return resolved.reason, resolved.quote_session


def resolve_recommendation_quote(
    *,
    run_date: str,
    quote_as_of: str | None,
    observed_at: str | None = None,
) -> RecommendationQuoteResolution:
    scan_date = date.fromisoformat(run_date)
    expected_session = latest_us_market_session(scan_date)
    if quote_as_of is None or not quote_as_of.strip():
        return RecommendationQuoteResolution(
            scan_date=scan_date,
            expected_session=expected_session,
            quote_at_utc=None,
            quote_session=None,
            canonical_as_of=None,
            reason="quote_as_of_missing",
        )
    try:
        parsed = datetime.fromisoformat(quote_as_of.replace("Z", "+00:00"))
    except ValueError:
        return RecommendationQuoteResolution(
            scan_date=scan_date,
            expected_session=expected_session,
            quote_at_utc=None,
            quote_session=None,
            canonical_as_of=None,
            reason="quote_as_of_invalid",
        )
    local = (
        parsed.replace(tzinfo=_NEW_YORK)
        if parsed.tzinfo is None
        else parsed.astimezone(_NEW_YORK)
    )
    quote_session = local.date()
    quote_at_utc = local.astimezone(UTC)
    canonical_as_of = quote_at_utc.isoformat().replace("+00:00", "Z")
    if observed_at is not None:
        try:
            observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            return RecommendationQuoteResolution(
                scan_date=scan_date,
                expected_session=expected_session,
                quote_at_utc=quote_at_utc,
                quote_session=quote_session,
                canonical_as_of=canonical_as_of,
                reason="quote_observed_at_invalid",
            )
        observed_utc = (
            observed.replace(tzinfo=UTC)
            if observed.tzinfo is None
            else observed.astimezone(UTC)
        )
        if quote_at_utc > observed_utc:
            return RecommendationQuoteResolution(
                scan_date=scan_date,
                expected_session=expected_session,
                quote_at_utc=quote_at_utc,
                quote_session=quote_session,
                canonical_as_of=canonical_as_of,
                reason="quote_future",
            )
    if not is_us_market_session(quote_session):
        reason = "quote_session_invalid"
    elif quote_session < expected_session:
        reason = "quote_stale"
    elif quote_session > expected_session:
        reason = "quote_future"
    else:
        reason = None
    return RecommendationQuoteResolution(
        scan_date=scan_date,
        expected_session=expected_session,
        quote_at_utc=quote_at_utc,
        quote_session=quote_session,
        canonical_as_of=canonical_as_of,
        reason=reason,
    )


def latest_us_market_session(active_date: date) -> date:
    candidate = active_date
    while not is_us_market_session(candidate):
        candidate -= timedelta(days=1)
    return candidate


def is_us_market_session(active_date: date) -> bool:
    return active_date.weekday() < 5 and not _is_regular_us_market_holiday(active_date)


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    active = date(year, month, 1)
    while active.weekday() != weekday:
        active += timedelta(days=1)
    return active + timedelta(days=7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    active = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    while active.weekday() != weekday:
        active -= timedelta(days=1)
    return active


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _observed_new_year(year: int) -> date:
    holiday = date(year, 1, 1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    # Unlike other fixed NYSE holidays, a Saturday New Year's Day does not
    # close the preceding Friday. The Saturday itself is already a non-session.
    return holiday


def _easter_date(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    month = (h + correction - 7 * m + 114) // 31
    day = ((h + correction - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _regular_us_market_holidays(year: int) -> set[date]:
    holidays = {
        _observed_new_year(year),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_date(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }
    if year >= 2022:
        holidays.add(_observed_fixed_holiday(year, 6, 19))
    return holidays


def _is_regular_us_market_holiday(active_date: date) -> bool:
    return any(
        active_date in _regular_us_market_holidays(year)
        for year in (active_date.year - 1, active_date.year, active_date.year + 1)
    )
