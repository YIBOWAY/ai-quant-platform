from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from quant_system.options.models import BuySideStrategyLeg

BuySideMetricsWarning = Literal[
    "WIDE_SPREAD",
    "LOW_OPEN_INTEREST",
    "LOW_VOLUME",
    "HIGH_THETA_BURN",
    "HIGH_IV_RANK",
    "HIGH_IV_CRUSH_RISK",
    "BREAK_EVEN_TOO_FAR",
    "LOW_DELTA_LOTTERY_CALL",
    "STALE_QUOTE",
    "MISSING_GREEKS",
    "TARGET_BELOW_IMPLIED_MOVE",
    "MISSING_VOLATILITY_DATA",
    "GREEK_UNIT_ASSUMPTION",
]

THETA_UNIT_ASSUMPTION = "theta is treated as option price change per contract per day"
VEGA_UNIT_ASSUMPTION = "vega is treated as option price change per 1 volatility point"
EPSILON = 1e-9


class BuySideMetricThresholds(BaseModel):
    excellent_spread_pct: float = 0.05
    acceptable_spread_pct: float = 0.10
    warning_spread_pct: float = 0.15
    theta_burn_7d_warning_pct: float = 0.15
    high_iv_rank: float = 70.0
    low_open_interest: float = 100.0
    low_volume: float = 20.0
    stale_quote_minutes: float = 30.0
    low_delta_lottery_call: float = 0.20


class BuySideContractMetrics(BaseModel):
    symbol: str
    mid_price: float | None = None
    bid_ask_spread_abs: float | None = None
    bid_ask_spread_pct: float | None = None
    intrinsic_value: float | None = None
    extrinsic_value: float | None = None
    break_even_price: float | None = None
    required_move_pct: float | None = None
    spread_pct: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    quote_staleness_minutes: float | None = None
    liquidity_score: float | None = None
    daily_theta_cost: float | None = None
    theta_pct_of_premium: float | None = None
    theta_burn_7d: float | None = None
    theta_burn_7d_pct: float | None = None
    days_to_lose_30pct: float | None = None
    vega_pct_of_premium: float | None = None
    estimated_iv_crush_loss: float | None = None
    estimated_iv_crush_loss_pct: float | None = None
    delta_per_dollar: float | None = None
    gamma_per_dollar: float | None = None
    gamma_theta_ratio: float | None = None
    vega_risk_score: float | None = Field(default=None, ge=0, le=100)
    iv_rank: float | None = Field(default=None, ge=0, le=100)
    iv_percentile: float | None = Field(default=None, ge=0, le=100)
    iv_hv_ratio: float | None = None
    expected_move_pct: float | None = None
    target_vs_expected_move_ratio: float | None = None
    historical_probability_of_breakeven: float | None = None
    buyer_friendliness_score: float | None = Field(default=None, ge=0, le=100)
    iv_crash_risk_score: float | None = Field(default=None, ge=0, le=100)
    breakeven_difficulty_score: float | None = Field(default=None, ge=0, le=100)
    theta_pain_score: float | None = Field(default=None, ge=0, le=100)
    leverage_efficiency: float | None = Field(default=None, ge=0)
    cost_of_convexity: float | None = Field(default=None, ge=0)
    theta_safety_score: float | None = Field(default=None, ge=0, le=100)
    volatility_valuation_score: float | None = Field(default=None, ge=0, le=100)
    greek_efficiency_score: float | None = Field(default=None, ge=0, le=100)
    break_even_quality_score: float | None = Field(default=None, ge=0, le=100)
    contract_quality_score: float | None = Field(default=None, ge=0, le=100)
    warnings: list[BuySideMetricsWarning] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def score_buy_side_contract(
    leg: BuySideStrategyLeg,
    *,
    atm_call_mid: float | None = None,
    atm_put_mid: float | None = None,
    user_target_move_pct: float | None = None,
    iv_rank: float | None = None,
    iv_low_1y: float | None = None,
    iv_high_1y: float | None = None,
    historical_iv_series: Sequence[float] | None = None,
    historical_volatility: float | None = None,
    forward_return_distribution: Sequence[float] | None = None,
    iv_crush_vol_points: float = -5.0,
    event_risk: bool = False,
    now: str | pd.Timestamp | None = None,
    thresholds: BuySideMetricThresholds | None = None,
) -> BuySideContractMetrics:
    """Score one read-only bullish option contract without external data calls."""

    limits = thresholds or BuySideMetricThresholds()
    mid_price = leg.mid_price
    spread_abs = leg.spread_abs
    spread_pct = leg.spread_pct
    intrinsic_value = _intrinsic_value_call(spot=leg.spot, strike=leg.strike)
    extrinsic_value = (
        max(mid_price - intrinsic_value, 0.0) if mid_price is not None else None
    )
    break_even = leg.strike + mid_price if mid_price is not None else None
    required_move_pct = (
        break_even / leg.spot - 1 if break_even is not None and leg.spot > 0 else None
    )
    quote_staleness = _quote_staleness_minutes(leg.update_time, now=now)
    expected_move_pct = _expected_move_pct(
        spot=leg.spot,
        atm_call_mid=atm_call_mid,
        atm_put_mid=atm_put_mid,
    )
    target_ratio = _target_vs_expected_move_ratio(
        user_target_move_pct=user_target_move_pct,
        expected_move_pct=expected_move_pct,
    )
    daily_theta_cost = abs(leg.theta) if leg.theta is not None else None
    theta_pct = _safe_div(daily_theta_cost, mid_price)
    theta_burn_7d = daily_theta_cost * 7 if daily_theta_cost is not None else None
    theta_burn_7d_pct = _safe_div(theta_burn_7d, mid_price)
    days_to_lose_30pct = (
        (mid_price * 0.3 / daily_theta_cost)
        if mid_price is not None and daily_theta_cost and daily_theta_cost > 0
        else None
    )
    vega_pct = _safe_div(abs(leg.vega) if leg.vega is not None else None, mid_price)
    iv_crush_loss = (
        abs(leg.vega) * abs(iv_crush_vol_points)
        if leg.vega is not None and mid_price is not None
        else None
    )
    iv_crush_loss_pct = _safe_div(iv_crush_loss, mid_price)
    delta_per_dollar = (
        leg.delta * leg.spot / mid_price
        if leg.delta is not None and mid_price is not None and mid_price > 0
        else None
    )
    gamma_per_dollar = (
        leg.gamma * leg.spot / mid_price
        if leg.gamma is not None and mid_price is not None and mid_price > 0
        else None
    )
    gamma_theta_ratio = (
        leg.gamma / daily_theta_cost
        if leg.gamma is not None and daily_theta_cost and daily_theta_cost > 0
        else None
    )
    resolved_iv_rank = _resolve_iv_rank(
        current_iv=leg.implied_volatility,
        explicit_iv_rank=iv_rank,
        iv_low_1y=iv_low_1y,
        iv_high_1y=iv_high_1y,
    )
    iv_percentile = _iv_percentile(
        current_iv=leg.implied_volatility,
        series=historical_iv_series,
    )
    iv_hv_ratio = _safe_div(leg.implied_volatility, historical_volatility)
    historical_probability = _historical_probability_of_breakeven(
        required_move_pct=required_move_pct,
        forward_returns=forward_return_distribution,
    )
    liquidity_score = _liquidity_score(
        spread_pct=spread_pct,
        volume=leg.volume,
        open_interest=leg.open_interest,
        quote_staleness_minutes=quote_staleness,
        thresholds=limits,
    )
    theta_safety_score = _theta_safety_score(theta_burn_7d_pct)
    volatility_score = _volatility_valuation_score(
        iv_rank=resolved_iv_rank,
        iv_hv_ratio=iv_hv_ratio,
    )
    greek_score = _greek_efficiency_score(
        delta_per_dollar=delta_per_dollar,
        gamma_per_dollar=gamma_per_dollar,
    )
    break_even_quality = _break_even_quality_score(
        required_move_pct=required_move_pct,
        expected_move_pct=expected_move_pct,
    )
    leverage_efficiency = delta_per_dollar if delta_per_dollar is not None else None
    cost_of_convexity = (
        extrinsic_value / max(abs(leg.gamma), EPSILON)
        if extrinsic_value is not None and leg.gamma is not None
        else None
    )
    vega_risk_score = _clip((vega_pct or 0.0) * 100)
    iv_crash_risk_score = _iv_crash_risk_score(
        vega_pct=vega_pct,
        iv_rank=resolved_iv_rank,
        event_risk=event_risk,
    )
    breakeven_difficulty_score = _breakeven_difficulty_score(
        required_move_pct=required_move_pct,
        expected_move_pct=expected_move_pct,
        historical_probability=historical_probability,
    )
    theta_pain_score = _theta_pain_score(theta_pct)
    buyer_friendliness_score = _weighted_score(
        [
            (volatility_score, 0.30),
            (break_even_quality, 0.30),
            (theta_safety_score, 0.20),
            (liquidity_score, 0.20),
        ]
    )
    contract_quality_score = _weighted_score(
        [
            (liquidity_score, 0.25),
            (theta_safety_score, 0.25),
            (volatility_score, 0.25),
            (greek_score, 0.15),
            (break_even_quality, 0.10),
        ]
    )
    warnings = _warnings(
        leg=leg,
        spread_pct=spread_pct,
        theta_burn_7d_pct=theta_burn_7d_pct,
        iv_rank=resolved_iv_rank,
        iv_crash_risk_score=iv_crash_risk_score,
        required_move_pct=required_move_pct,
        quote_staleness_minutes=quote_staleness,
        target_vs_expected_move_ratio=target_ratio,
        volatility_score=volatility_score,
        thresholds=limits,
    )
    return BuySideContractMetrics(
        symbol=leg.symbol,
        mid_price=mid_price,
        bid_ask_spread_abs=spread_abs,
        bid_ask_spread_pct=spread_pct,
        intrinsic_value=intrinsic_value,
        extrinsic_value=extrinsic_value,
        break_even_price=break_even,
        required_move_pct=required_move_pct,
        spread_pct=spread_pct,
        volume=leg.volume,
        open_interest=leg.open_interest,
        quote_staleness_minutes=quote_staleness,
        liquidity_score=liquidity_score,
        daily_theta_cost=daily_theta_cost,
        theta_pct_of_premium=theta_pct,
        theta_burn_7d=theta_burn_7d,
        theta_burn_7d_pct=theta_burn_7d_pct,
        days_to_lose_30pct=days_to_lose_30pct,
        vega_pct_of_premium=vega_pct,
        estimated_iv_crush_loss=iv_crush_loss,
        estimated_iv_crush_loss_pct=iv_crush_loss_pct,
        delta_per_dollar=delta_per_dollar,
        gamma_per_dollar=gamma_per_dollar,
        gamma_theta_ratio=gamma_theta_ratio,
        vega_risk_score=vega_risk_score,
        iv_rank=resolved_iv_rank,
        iv_percentile=iv_percentile,
        iv_hv_ratio=iv_hv_ratio,
        expected_move_pct=expected_move_pct,
        target_vs_expected_move_ratio=target_ratio,
        historical_probability_of_breakeven=historical_probability,
        buyer_friendliness_score=buyer_friendliness_score,
        iv_crash_risk_score=iv_crash_risk_score,
        breakeven_difficulty_score=breakeven_difficulty_score,
        theta_pain_score=theta_pain_score,
        leverage_efficiency=leverage_efficiency,
        cost_of_convexity=cost_of_convexity,
        theta_safety_score=theta_safety_score,
        volatility_valuation_score=volatility_score,
        greek_efficiency_score=greek_score,
        break_even_quality_score=break_even_quality,
        contract_quality_score=contract_quality_score,
        warnings=warnings,
        assumptions=[THETA_UNIT_ASSUMPTION, VEGA_UNIT_ASSUMPTION],
    )


def _intrinsic_value_call(*, spot: float, strike: float) -> float:
    return max(spot - strike, 0.0)


def _expected_move_pct(
    *,
    spot: float,
    atm_call_mid: float | None,
    atm_put_mid: float | None,
) -> float | None:
    if spot <= 0 or atm_call_mid is None or atm_put_mid is None:
        return None
    if atm_call_mid <= 0 or atm_put_mid <= 0:
        return None
    return (atm_call_mid + atm_put_mid) / spot


def _target_vs_expected_move_ratio(
    *,
    user_target_move_pct: float | None,
    expected_move_pct: float | None,
) -> float | None:
    if (
        user_target_move_pct is None
        or expected_move_pct is None
        or expected_move_pct <= 0
    ):
        return None
    return user_target_move_pct / expected_move_pct


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) <= EPSILON:
        return None
    return numerator / denominator


def _resolve_iv_rank(
    *,
    current_iv: float | None,
    explicit_iv_rank: float | None,
    iv_low_1y: float | None,
    iv_high_1y: float | None,
) -> float | None:
    if explicit_iv_rank is not None:
        return _clip(explicit_iv_rank)
    if current_iv is None or iv_low_1y is None or iv_high_1y is None:
        return None
    width = iv_high_1y - iv_low_1y
    if width <= 0:
        return None
    return _clip(((current_iv - iv_low_1y) / width) * 100)


def _iv_percentile(
    *,
    current_iv: float | None,
    series: Sequence[float] | None,
) -> float | None:
    if current_iv is None or not series:
        return None
    clean = [value for value in series if not math.isnan(float(value))]
    if not clean:
        return None
    below_or_equal = sum(1 for value in clean if value <= current_iv)
    return _clip((below_or_equal / len(clean)) * 100)


def _historical_probability_of_breakeven(
    *,
    required_move_pct: float | None,
    forward_returns: Sequence[float] | None,
) -> float | None:
    if required_move_pct is None or not forward_returns:
        return None
    clean = [value for value in forward_returns if not math.isnan(float(value))]
    if not clean:
        return None
    hits = sum(1 for value in clean if value >= required_move_pct)
    return hits / len(clean)


def _liquidity_score(
    *,
    spread_pct: float | None,
    volume: float | None,
    open_interest: float | None,
    quote_staleness_minutes: float | None,
    thresholds: BuySideMetricThresholds,
) -> float | None:
    components = [
        _spread_score(spread_pct, thresholds=thresholds),
        _activity_score(volume, good=100.0, acceptable=thresholds.low_volume),
        _activity_score(
            open_interest,
            good=500.0,
            acceptable=thresholds.low_open_interest,
        ),
    ]
    if quote_staleness_minutes is not None:
        stale_score = (
            100.0
            if quote_staleness_minutes <= thresholds.stale_quote_minutes
            else 35.0
        )
        components.append(stale_score)
    return _average_score(components)


def _spread_score(
    spread_pct: float | None,
    *,
    thresholds: BuySideMetricThresholds,
) -> float | None:
    if spread_pct is None:
        return None
    if spread_pct < thresholds.excellent_spread_pct:
        return 100.0
    if spread_pct < thresholds.acceptable_spread_pct:
        return 80.0
    if spread_pct <= thresholds.warning_spread_pct:
        return 55.0
    return max(0.0, 55.0 - (spread_pct - thresholds.warning_spread_pct) * 200)


def _activity_score(value: float | None, *, good: float, acceptable: float) -> float | None:
    if value is None:
        return None
    if value >= good:
        return 100.0
    if value >= acceptable:
        return 70.0
    if value > 0:
        return 30.0
    return 0.0


def _theta_safety_score(theta_burn_7d_pct: float | None) -> float | None:
    if theta_burn_7d_pct is None:
        return None
    if theta_burn_7d_pct < 0.05:
        return 100.0
    if theta_burn_7d_pct <= 0.15:
        return 75.0
    if theta_burn_7d_pct <= 0.25:
        return 40.0
    return 15.0


def _volatility_valuation_score(
    *,
    iv_rank: float | None,
    iv_hv_ratio: float | None,
) -> float | None:
    if iv_rank is not None:
        return _clip(100.0 - iv_rank)
    if iv_hv_ratio is None:
        return None
    if iv_hv_ratio <= 1.0:
        return 85.0
    if iv_hv_ratio <= 1.25:
        return 65.0
    if iv_hv_ratio <= 1.50:
        return 40.0
    return 20.0


def _greek_efficiency_score(
    *,
    delta_per_dollar: float | None,
    gamma_per_dollar: float | None,
) -> float | None:
    return _weighted_score(
        [
            (_clip((delta_per_dollar or 0.0) * 8) if delta_per_dollar is not None else None, 0.65),
            (
                _clip((gamma_per_dollar or 0.0) * 100)
                if gamma_per_dollar is not None
                else None,
                0.35,
            ),
        ]
    )


def _break_even_quality_score(
    *,
    required_move_pct: float | None,
    expected_move_pct: float | None,
) -> float | None:
    if required_move_pct is None:
        return None
    if expected_move_pct is not None and expected_move_pct > 0:
        ratio = required_move_pct / expected_move_pct
        return _clip(100.0 - max(ratio - 0.5, 0.0) * 80)
    if required_move_pct <= 0.05:
        return 100.0
    if required_move_pct <= 0.10:
        return 75.0
    if required_move_pct <= 0.20:
        return 40.0
    return 15.0


def _iv_crash_risk_score(
    *,
    vega_pct: float | None,
    iv_rank: float | None,
    event_risk: bool,
) -> float | None:
    if vega_pct is None:
        return None
    rank_factor = 0.5 + 0.5 * ((iv_rank if iv_rank is not None else 50.0) / 100)
    event_multiplier = 1.5 if event_risk else 1.0
    return _clip((vega_pct * 100) * rank_factor * event_multiplier)


def _breakeven_difficulty_score(
    *,
    required_move_pct: float | None,
    expected_move_pct: float | None,
    historical_probability: float | None,
) -> float | None:
    if historical_probability is not None:
        return _clip((1.0 - historical_probability) * 100)
    if required_move_pct is None:
        return None
    if expected_move_pct is not None and expected_move_pct > 0:
        return _clip((required_move_pct / expected_move_pct) * 50)
    return _clip(required_move_pct * 500)


def _theta_pain_score(theta_pct: float | None) -> float | None:
    if theta_pct is None:
        return None
    if theta_pct < 0.01:
        return 10.0
    if theta_pct < 0.03:
        return 35.0
    if theta_pct < 0.05:
        return 65.0
    return 90.0


def _warnings(
    *,
    leg: BuySideStrategyLeg,
    spread_pct: float | None,
    theta_burn_7d_pct: float | None,
    iv_rank: float | None,
    iv_crash_risk_score: float | None,
    required_move_pct: float | None,
    quote_staleness_minutes: float | None,
    target_vs_expected_move_ratio: float | None,
    volatility_score: float | None,
    thresholds: BuySideMetricThresholds,
) -> list[BuySideMetricsWarning]:
    warnings: list[BuySideMetricsWarning] = ["GREEK_UNIT_ASSUMPTION"]
    if any(warning in leg.warnings for warning in ("missing_quote", "invalid_bid_ask")):
        warnings.append("WIDE_SPREAD")
    if spread_pct is None or spread_pct > thresholds.warning_spread_pct:
        warnings.append("WIDE_SPREAD")
    if leg.open_interest is None or leg.open_interest < thresholds.low_open_interest:
        warnings.append("LOW_OPEN_INTEREST")
    if leg.volume is None or leg.volume < thresholds.low_volume:
        warnings.append("LOW_VOLUME")
    if theta_burn_7d_pct is not None and theta_burn_7d_pct > thresholds.theta_burn_7d_warning_pct:
        warnings.append("HIGH_THETA_BURN")
    if iv_rank is not None and iv_rank > thresholds.high_iv_rank:
        warnings.append("HIGH_IV_RANK")
    if iv_crash_risk_score is not None and iv_crash_risk_score > 50:
        warnings.append("HIGH_IV_CRUSH_RISK")
    if required_move_pct is not None and required_move_pct > 0.20:
        warnings.append("BREAK_EVEN_TOO_FAR")
    if leg.delta is None or leg.gamma is None or leg.theta is None or leg.vega is None:
        warnings.append("MISSING_GREEKS")
    elif leg.delta < thresholds.low_delta_lottery_call:
        warnings.append("LOW_DELTA_LOTTERY_CALL")
    if (
        quote_staleness_minutes is not None
        and quote_staleness_minutes > thresholds.stale_quote_minutes
    ):
        warnings.append("STALE_QUOTE")
    if target_vs_expected_move_ratio is not None and target_vs_expected_move_ratio < 1:
        warnings.append("TARGET_BELOW_IMPLIED_MOVE")
    if volatility_score is None:
        warnings.append("MISSING_VOLATILITY_DATA")
    return list(dict.fromkeys(warnings))


def _quote_staleness_minutes(
    update_time: str | None,
    *,
    now: str | pd.Timestamp | None,
) -> float | None:
    if update_time is None or now is None:
        return None
    quote_ts = _coerce_timestamp(update_time)
    now_ts = _coerce_timestamp(now)
    if quote_ts is None or now_ts is None:
        return None
    return max((now_ts - quote_ts).total_seconds() / 60, 0.0)


def _coerce_timestamp(value: str | pd.Timestamp) -> pd.Timestamp | None:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _weighted_score(items: list[tuple[float | None, float]]) -> float | None:
    available = [(score, weight) for score, weight in items if score is not None]
    if not available:
        return None
    total_weight = sum(weight for _score, weight in available)
    if total_weight <= 0:
        return None
    return _clip(sum(score * weight for score, weight in available) / total_weight)


def _average_score(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    if not clean:
        return None
    return _clip(sum(clean) / len(clean))


def _clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return min(max(value, lower), upper)
