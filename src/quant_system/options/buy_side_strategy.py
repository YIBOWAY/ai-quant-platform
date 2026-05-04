from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from quant_system.options.buy_side_metrics import score_buy_side_contract
from quant_system.options.market_regime import (
    VixRegimeSnapshot,
    buyer_regime_penalty,
)
from quant_system.options.models import (
    BuySideAssistantResult,
    BuySideEventRisk,
    BuySideRiskPreference,
    BuySideStrategyCandidate,
    BuySideStrategyLeg,
    BuySideStrategyScore,
    BuySideStrategyType,
    BuySideThesisInput,
    BuySideViewType,
    BuySideVolatilityView,
)

StrategyWarning = Literal[
    "HIGH_IV_CRUSH_RISK",
    "HIGH_THETA_BURN",
    "POOR_LIQUIDITY",
    "BREAK_EVEN_ABOVE_TARGET",
    "LOW_REWARD_RISK",
    "CAPPED_UPSIDE",
    "LOTTERY_OPTION",
    "EVENT_RISK",
    "MISSING_DATA",
    "MARKET_REGIME_ELEVATED",
    "MARKET_REGIME_PANIC",
]


class BuySideStrategyRequest(BaseModel):
    ticker: str
    spot_price: float = Field(gt=0)
    view_type: BuySideViewType
    target_price: float = Field(gt=0)
    target_date: str
    max_loss_budget: float | None = Field(default=None, gt=0)
    risk_preference: BuySideRiskPreference = "balanced"
    allow_capped_upside: bool = True
    avoid_high_iv: bool = False
    volatility_view: BuySideVolatilityView = "auto"
    event_risk: BuySideEventRisk = "none"
    expected_iv_change_vol_points: float | None = None
    preferred_dte_range: tuple[int, int] | None = None
    iv_rank: float | None = Field(default=None, ge=0, le=100)
    historical_volatility: float | None = Field(default=None, ge=0)
    as_of_date: str | None = None
    strategy_types: tuple[BuySideStrategyType, ...] | None = None

    @field_validator("target_date", "as_of_date")
    @classmethod
    def _validate_dates(cls, value: str | None) -> str | None:
        if value is not None:
            pd.Timestamp(value)
        return value


def generate_buy_side_candidates(
    option_chain: pd.DataFrame,
    request: BuySideStrategyRequest,
    *,
    market_regime: VixRegimeSnapshot | None = None,
    max_candidates: int = 20,
) -> BuySideAssistantResult:
    """Generate ranked bullish buy-side option candidates from a local chain."""

    if option_chain.empty:
        return _empty_result(request, ["empty option chain"])
    calls = _prepare_calls(option_chain, request)
    if calls.empty:
        return _empty_result(request, ["no usable call options"])

    strategy_types = (
        list(request.strategy_types)
        if request.strategy_types is not None
        else _strategy_types_for_view(request.view_type)
    )
    candidates: list[BuySideStrategyCandidate] = []
    for strategy_type in strategy_types:
        if strategy_type in {"long_call", "leaps_call"}:
            candidates.extend(_long_call_candidates(calls, request, strategy_type, market_regime))
        else:
            candidates.extend(_spread_candidates(calls, request, strategy_type, market_regime))

    ranked = sorted(
        candidates,
        key=lambda item: (
            item.score.total_score,
            item.score.buyer_friendliness_score or 0.0,
            -(item.net_debit or math.inf),
        ),
        reverse=True,
    )
    thesis = BuySideThesisInput(
        ticker=request.ticker,
        view_type=request.view_type,
        target_price=request.target_price,
        target_date=request.target_date,
        volatility_view=request.volatility_view,
        risk_preference=request.risk_preference,
        event_risk=request.event_risk,
    )
    return BuySideAssistantResult(
        ticker=request.ticker.upper(),
        thesis=thesis,
        candidates=ranked[:max_candidates],
        assumptions=[
            "Quantitative decision support only; no order placement is available.",
            "Strategy generation uses supplied option-chain rows only and "
            "does not fetch live data.",
            "Theta and vega use the unit assumptions documented by buy_side_metrics.",
        ],
    )


def _empty_result(
    request: BuySideStrategyRequest,
    assumptions: list[str],
) -> BuySideAssistantResult:
    return BuySideAssistantResult(
        ticker=request.ticker.upper(),
        thesis=BuySideThesisInput(
            ticker=request.ticker,
            view_type=request.view_type,
            target_price=request.target_price,
            target_date=request.target_date,
            volatility_view=request.volatility_view,
            risk_preference=request.risk_preference,
            event_risk=request.event_risk,
        ),
        candidates=[],
        assumptions=assumptions,
    )


def _prepare_calls(option_chain: pd.DataFrame, request: BuySideStrategyRequest) -> pd.DataFrame:
    frame = option_chain.copy()
    frame["option_type"] = frame.get("option_type", "").astype(str).str.upper()
    frame = frame.loc[frame["option_type"] == "CALL"].copy()
    if frame.empty:
        return frame
    frame["expiry"] = frame["expiry"].astype(str)
    frame["_dte"] = frame.get("option_expiry_date_distance")
    if frame["_dte"].isna().all():
        frame["_dte"] = frame["expiry"].map(
            lambda value: _days_to_expiry(value, request.as_of_date)
        )
    frame["_dte"] = pd.to_numeric(frame["_dte"], errors="coerce")
    frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce")
    frame["delta"] = pd.to_numeric(frame.get("delta"), errors="coerce")
    frame["_mid"] = frame.apply(lambda row: _mid(row.get("bid"), row.get("ask")), axis=1)
    return frame.dropna(
        subset=["symbol", "expiry", "strike", "_dte", "_mid"]
    ).reset_index(drop=True)


def _strategy_types_for_view(view_type: BuySideViewType) -> list[BuySideStrategyType]:
    if view_type == "long_term_aggressive_bullish":
        return ["leaps_call", "leaps_call_spread"]
    if view_type == "long_term_conservative_bullish":
        return ["leaps_call_spread", "leaps_call"]
    if view_type == "short_term_speculative_bullish":
        return ["long_call", "bull_call_spread"]
    if view_type == "short_term_conservative_bullish":
        return ["bull_call_spread", "long_call"]
    return ["bull_call_spread", "long_call"]


def _dte_range(
    strategy_type: BuySideStrategyType,
    request: BuySideStrategyRequest,
) -> tuple[int, int]:
    if request.preferred_dte_range is not None:
        return request.preferred_dte_range
    if strategy_type in {"leaps_call", "leaps_call_spread"}:
        return 360, 3000
    if request.view_type == "short_term_speculative_bullish":
        return 7, 45
    if request.view_type == "short_term_conservative_bullish":
        return 21, 90
    return 180, 3000


def _delta_range(
    strategy_type: BuySideStrategyType,
    request: BuySideStrategyRequest,
) -> tuple[float, float]:
    if strategy_type in {"leaps_call", "leaps_call_spread"}:
        return 0.65, 0.85
    if request.view_type == "short_term_speculative_bullish":
        return 0.30, 0.60
    return 0.45, 0.70


def _long_call_candidates(
    calls: pd.DataFrame,
    request: BuySideStrategyRequest,
    strategy_type: BuySideStrategyType,
    market_regime: VixRegimeSnapshot | None,
) -> list[BuySideStrategyCandidate]:
    min_dte, max_dte = _dte_range(strategy_type, request)
    min_delta, max_delta = _delta_range(strategy_type, request)
    delta_abs = calls["delta"].abs()
    frame = calls.loc[
        (calls["_dte"] >= min_dte)
        & (calls["_dte"] <= max_dte)
        & (delta_abs.isna() | ((delta_abs >= min_delta) & (delta_abs <= max_delta)))
    ].copy()
    candidates = []
    for row in frame.to_dict(orient="records"):
        leg = _leg(row, request, side="long")
        if (
            request.max_loss_budget is not None
            and (leg.mid_price or math.inf) * leg.contract_size > request.max_loss_budget
        ):
            continue
        metrics = score_buy_side_contract(
            leg,
            user_target_move_pct=request.target_price / request.spot_price - 1,
            iv_rank=request.iv_rank,
            historical_volatility=request.historical_volatility,
            iv_crush_vol_points=request.expected_iv_change_vol_points or -5.0,
            event_risk=request.event_risk != "none",
            now=None,
        )
        candidates.append(
            _candidate_from_single_leg(
                request=request,
                strategy_type=strategy_type,
                leg=leg,
                metrics=metrics,
                market_regime=market_regime,
            )
        )
    return candidates


def _spread_candidates(
    calls: pd.DataFrame,
    request: BuySideStrategyRequest,
    strategy_type: BuySideStrategyType,
    market_regime: VixRegimeSnapshot | None,
) -> list[BuySideStrategyCandidate]:
    if not request.allow_capped_upside:
        return []
    min_dte, max_dte = _dte_range(strategy_type, request)
    frame = calls.loc[(calls["_dte"] >= min_dte) & (calls["_dte"] <= max_dte)].copy()
    candidates = []
    for expiry, group in frame.groupby("expiry"):
        del expiry
        longs = group.loc[(group["delta"].abs() >= 0.45) & (group["delta"].abs() <= 0.70)]
        shorts = group.loc[(group["delta"].abs() >= 0.20) & (group["delta"].abs() <= 0.40)]
        for long_row in longs.to_dict(orient="records"):
            for short_row in shorts.to_dict(orient="records"):
                if short_row["strike"] <= long_row["strike"]:
                    continue
                long_leg = _leg(long_row, request, side="long")
                short_leg = _leg(short_row, request, side="short")
                net_debit = (long_leg.mid_price or 0.0) - (short_leg.mid_price or 0.0)
                width = short_leg.strike - long_leg.strike
                max_profit_per_share = width - net_debit
                if net_debit <= 0 or max_profit_per_share <= 0:
                    continue
                if net_debit >= width * 0.90:
                    continue
                max_loss = net_debit * long_leg.contract_size
                if request.max_loss_budget is not None and max_loss > request.max_loss_budget:
                    continue
                metrics = score_buy_side_contract(
                    long_leg,
                    user_target_move_pct=request.target_price / request.spot_price - 1,
                    iv_rank=request.iv_rank,
                    historical_volatility=request.historical_volatility,
                    iv_crush_vol_points=request.expected_iv_change_vol_points or -5.0,
                    event_risk=request.event_risk != "none",
                    now=None,
                )
                candidates.append(
                    _candidate_from_spread(
                        request=request,
                        strategy_type=strategy_type,
                        long_leg=long_leg,
                        short_leg=short_leg,
                        net_debit=net_debit,
                        max_profit_per_share=max_profit_per_share,
                        metrics=metrics,
                        market_regime=market_regime,
                    )
                )
    return candidates


def _leg(
    row: dict[str, object],
    request: BuySideStrategyRequest,
    *,
    side: str,
) -> BuySideStrategyLeg:
    leg_side = "short" if side == "short" else "long"
    return BuySideStrategyLeg(
        symbol=str(row["symbol"]),
        option_type="CALL",
        side=leg_side,
        expiry=str(row["expiry"]),
        strike=float(row["strike"]),
        spot=request.spot_price,
        as_of_date=request.as_of_date,
        bid=_safe_float(row.get("bid")),
        ask=_safe_float(row.get("ask")),
        last=_safe_float(row.get("last")),
        contract_size=int(_safe_float(row.get("contract_size")) or 100),
        implied_volatility=_safe_float(row.get("implied_volatility")),
        delta=_safe_float(row.get("delta")),
        gamma=_safe_float(row.get("gamma")),
        theta=_safe_float(row.get("theta")),
        vega=_safe_float(row.get("vega")),
        rho=_safe_float(row.get("rho")),
        volume=_safe_float(row.get("volume")),
        open_interest=_safe_float(row.get("open_interest")),
        update_time=_safe_str(row.get("update_time")),
    )


def _candidate_from_single_leg(
    *,
    request: BuySideStrategyRequest,
    strategy_type: BuySideStrategyType,
    leg: BuySideStrategyLeg,
    metrics,
    market_regime: VixRegimeSnapshot | None,
) -> BuySideStrategyCandidate:
    premium = leg.mid_price
    max_loss = premium * leg.contract_size if premium is not None else None
    breakeven = leg.strike + premium if premium is not None else None
    gross = _component_score(
        metrics=metrics,
        request=request,
        breakeven=breakeven,
        max_loss=max_loss,
        max_gain=None,
    )
    adjusted, penalty = _apply_regime(gross, strategy_type, market_regime)
    warnings = _candidate_warnings(
        metrics=metrics,
        request=request,
        breakeven=breakeven,
        reward_risk=None,
        capped=False,
        market_regime=market_regime,
    )
    return BuySideStrategyCandidate(
        strategy_type=strategy_type,
        ticker=request.ticker.upper(),
        legs=[leg],
        score=_score(metrics=metrics, total=adjusted),
        net_debit=premium,
        max_loss=max_loss,
        max_gain=None,
        breakeven=breakeven,
        expected_move_pct=metrics.expected_move_pct,
        target_vs_expected_move_ratio=metrics.target_vs_expected_move_ratio,
        risk_attribution=_risk_attribution(metrics),
        warnings=warnings,
        notes=["Quantitative decision support only; not a trade instruction."],
        market_regime=market_regime.volatility_regime if market_regime else None,
        market_regime_penalty=penalty,
    )


def _candidate_from_spread(
    *,
    request: BuySideStrategyRequest,
    strategy_type: BuySideStrategyType,
    long_leg: BuySideStrategyLeg,
    short_leg: BuySideStrategyLeg,
    net_debit: float,
    max_profit_per_share: float,
    metrics,
    market_regime: VixRegimeSnapshot | None,
) -> BuySideStrategyCandidate:
    contract_size = long_leg.contract_size
    max_loss = net_debit * contract_size
    max_profit = max_profit_per_share * contract_size
    breakeven = long_leg.strike + net_debit
    reward_risk = max_profit / max_loss if max_loss > 0 else None
    gross = _component_score(
        metrics=metrics,
        request=request,
        breakeven=breakeven,
        max_loss=max_loss,
        max_gain=max_profit,
    )
    gross += _volatility_structure_bonus(request, naked=False)
    adjusted, penalty = _apply_regime(gross, strategy_type, market_regime)
    warnings = _candidate_warnings(
        metrics=metrics,
        request=request,
        breakeven=breakeven,
        reward_risk=reward_risk,
        capped=True,
        market_regime=market_regime,
    )
    return BuySideStrategyCandidate(
        strategy_type=strategy_type,
        ticker=request.ticker.upper(),
        legs=[long_leg, short_leg],
        score=_score(metrics=metrics, total=adjusted),
        net_debit=net_debit,
        max_loss=max_loss,
        max_gain=max_profit,
        breakeven=breakeven,
        expected_move_pct=metrics.expected_move_pct,
        target_vs_expected_move_ratio=metrics.target_vs_expected_move_ratio,
        risk_attribution=_risk_attribution(metrics),
        warnings=warnings,
        notes=["Capped-upside spread output is decision support only."],
        market_regime=market_regime.volatility_regime if market_regime else None,
        market_regime_penalty=penalty,
    )


def _component_score(*, metrics, request, breakeven, max_loss, max_gain) -> float:
    direction = _direction_fit_score(
        request=request,
        breakeven=breakeven,
        max_gain=max_gain,
        max_loss=max_loss,
    )
    volatility = metrics.volatility_valuation_score
    theta = metrics.theta_safety_score
    greek = metrics.greek_efficiency_score
    liquidity = metrics.liquidity_score
    risk_reward = _risk_reward_score(max_gain=max_gain, max_loss=max_loss)
    base = _weighted_average(
        [
            (direction, 0.25),
            (volatility, 0.20),
            (theta, 0.20),
            (greek, 0.15),
            (liquidity, 0.10),
            (risk_reward, 0.10),
        ]
    )
    base += _volatility_structure_bonus(request, naked=max_gain is None)
    return _clip(base)


def _direction_fit_score(*, request, breakeven, max_gain, max_loss) -> float:
    if breakeven is None:
        return 20.0
    if breakeven > request.target_price:
        return 15.0
    upside = max(request.target_price - breakeven, 0.0)
    if max_gain is not None and max_loss and max_loss > 0:
        target_payoff = min(upside * 100, max_gain)
        return _clip(40 + (target_payoff / max_loss) * 30)
    return _clip(45 + (upside / request.spot_price) * 300)


def _risk_reward_score(*, max_gain, max_loss) -> float:
    if max_gain is None:
        return 60.0
    if max_loss is None or max_loss <= 0:
        return 0.0
    ratio = max_gain / max_loss
    if ratio >= 2:
        return 100.0
    if ratio >= 1:
        return 75.0
    if ratio >= 0.5:
        return 45.0
    return 20.0


def _volatility_structure_bonus(request: BuySideStrategyRequest, *, naked: bool) -> float:
    if request.volatility_view == "expect_iv_expansion":
        return 8.0 if naked else 0.0
    if request.volatility_view in {"prefer_low_iv", "expect_iv_crush"} or request.avoid_high_iv:
        if naked:
            return -18.0 if request.volatility_view == "expect_iv_crush" else -10.0
        return 14.0 if request.volatility_view == "expect_iv_crush" else 8.0
    if request.volatility_view == "auto" and request.event_risk != "none":
        return -12.0 if naked else 8.0
    return 0.0


def _apply_regime(score: float, strategy_type: BuySideStrategyType, market_regime):
    if market_regime is None:
        return _clip(score), 0.0
    penalty = buyer_regime_penalty(strategy_type, market_regime.volatility_regime)
    return _clip(score + penalty), penalty


def _score(*, metrics, total: float) -> BuySideStrategyScore:
    return BuySideStrategyScore(
        total_score=total,
        direction_score=None,
        timing_score=None,
        volatility_score=metrics.volatility_valuation_score,
        liquidity_score=metrics.liquidity_score,
        theta_pain_score=metrics.theta_pain_score,
        theta_safety_score=metrics.theta_safety_score,
        greek_efficiency_score=metrics.greek_efficiency_score,
        buyer_friendliness_score=metrics.buyer_friendliness_score,
        iv_crash_risk_score=metrics.iv_crash_risk_score,
        breakeven_difficulty_score=metrics.breakeven_difficulty_score,
        leverage_efficiency=metrics.leverage_efficiency,
        cost_of_convexity=metrics.cost_of_convexity,
    )


def _candidate_warnings(
    *,
    metrics,
    request,
    breakeven,
    reward_risk,
    capped,
    market_regime,
) -> list[str]:
    warnings: list[str] = []
    if "HIGH_IV_CRUSH_RISK" in metrics.warnings:
        warnings.append("HIGH_IV_CRUSH_RISK")
    if "HIGH_THETA_BURN" in metrics.warnings:
        warnings.append("HIGH_THETA_BURN")
    if metrics.liquidity_score is None or metrics.liquidity_score < 60:
        warnings.append("POOR_LIQUIDITY")
    if breakeven is None or breakeven > request.target_price:
        warnings.append("BREAK_EVEN_ABOVE_TARGET")
    if reward_risk is not None and reward_risk < 1:
        warnings.append("LOW_REWARD_RISK")
    if capped:
        warnings.append("CAPPED_UPSIDE")
    if metrics.delta_per_dollar is not None and metrics.delta_per_dollar < 3:
        warnings.append("LOTTERY_OPTION")
    if request.event_risk != "none":
        warnings.append("EVENT_RISK")
    if "MISSING_GREEKS" in metrics.warnings:
        warnings.append("MISSING_DATA")
    if market_regime is not None:
        if market_regime.volatility_regime == "Panic":
            warnings.append("MARKET_REGIME_PANIC")
        elif market_regime.volatility_regime == "Elevated":
            warnings.append("MARKET_REGIME_ELEVATED")
    return list(dict.fromkeys(warnings))


def _risk_attribution(metrics) -> dict[str, float]:
    return {
        "direction": metrics.breakeven_difficulty_score or 0.0,
        "time": metrics.theta_pain_score or 0.0,
        "volatility": metrics.iv_crash_risk_score or 0.0,
        "liquidity": 100.0 - (metrics.liquidity_score or 0.0),
    }


def _days_to_expiry(expiry: str, as_of_date: str | None) -> int:
    start = pd.Timestamp(as_of_date).normalize() if as_of_date else pd.Timestamp.today().normalize()
    end = pd.Timestamp(expiry).normalize()
    return max(int((end - start).days), 0)


def _mid(bid, ask):
    bid_value = _safe_float(bid)
    ask_value = _safe_float(ask)
    if bid_value is None or ask_value is None or ask_value < bid_value:
        return None
    return (bid_value + ask_value) / 2


def _safe_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) else parsed


def _safe_str(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)


def _weighted_average(items: list[tuple[float | None, float]]) -> float:
    available = [(score, weight) for score, weight in items if score is not None]
    if not available:
        return 0.0
    total_weight = sum(weight for _score, weight in available)
    return sum(score * weight for score, weight in available) / total_weight


def _clip(value: float) -> float:
    return min(max(value, 0.0), 100.0)
