from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from quant_system.options.buy_side_metrics import score_buy_side_contract
from quant_system.options.buy_side_scenarios import (
    BuySideScenarioLabInput,
    BuySideScenarioLabSummary,
    BuySideUserScenarioPnL,
    run_buy_side_scenario_lab,
)
from quant_system.options.buy_side_strategy import (
    BuySideStrategyRequest,
    generate_buy_side_candidates,
)
from quant_system.options.market_regime import VixRegimeSnapshot
from quant_system.options.models import (
    BuySideEventRisk,
    BuySideRiskPreference,
    BuySideScenarioEV,
    BuySideStrategyCandidate,
    BuySideStrategyLeg,
    BuySideStrategyType,
    BuySideViewType,
    BuySideVolatilityView,
)

PrimaryRiskSource = Literal["direction", "time", "volatility", "liquidity"]

ALL_BUY_SIDE_STRATEGIES: tuple[BuySideStrategyType, ...] = (
    "long_call",
    "bull_call_spread",
    "leaps_call",
    "leaps_call_spread",
)
NAKED_LONG_STRATEGIES = {"long_call", "leaps_call"}
SPREAD_STRATEGIES = {"bull_call_spread", "leaps_call_spread"}
ADVICE_BANNED_TERMS = ("buy this", "best trade", "safe", "guaranteed", "risk-free")


class BuySideDecisionRequest(BaseModel):
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
    user_scenarios: list[BuySideUserScenarioPnL] = Field(default_factory=list)
    scenario_spot_changes: list[float] = Field(
        default_factory=lambda: [-10.0, 0.0, 10.0]
    )
    scenario_iv_changes: list[float] = Field(default_factory=lambda: [-5.0, 0.0, 5.0])
    scenario_days_passed: list[int] = Field(default_factory=lambda: [0, 7])

    @field_validator("target_date", "as_of_date")
    @classmethod
    def _validate_dates(cls, value: str | None) -> str | None:
        if value is not None:
            pd.Timestamp(value)
        return value


class BuySideAssistantRequest(BaseModel):
    """Public API request contract for the buy-side assistant."""

    ticker: str
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
    spot_price: float | None = Field(default=None, gt=0)
    user_scenarios: list[BuySideUserScenarioPnL] = Field(default_factory=list)
    scenario_spot_changes: list[float] = Field(
        default_factory=lambda: [-10.0, 0.0, 10.0]
    )
    scenario_iv_changes: list[float] = Field(default_factory=lambda: [-5.0, 0.0, 5.0])
    scenario_days_passed: list[int] = Field(default_factory=lambda: [0, 7])
    provider: str = "futu"
    max_recommendations: int = Field(default=10, ge=1, le=50)

    @field_validator("target_date", "as_of_date")
    @classmethod
    def _validate_dates(cls, value: str | None) -> str | None:
        if value is not None:
            pd.Timestamp(value)
        return value

    def to_decision_request(self, *, spot_price: float) -> BuySideDecisionRequest:
        return BuySideDecisionRequest(
            ticker=self.ticker,
            spot_price=spot_price,
            view_type=self.view_type,
            target_price=self.target_price,
            target_date=self.target_date,
            max_loss_budget=self.max_loss_budget,
            risk_preference=self.risk_preference,
            allow_capped_upside=self.allow_capped_upside,
            avoid_high_iv=self.avoid_high_iv,
            volatility_view=self.volatility_view,
            event_risk=self.event_risk,
            expected_iv_change_vol_points=self.expected_iv_change_vol_points,
            preferred_dte_range=self.preferred_dte_range,
            iv_rank=self.iv_rank,
            historical_volatility=self.historical_volatility,
            as_of_date=self.as_of_date,
            user_scenarios=self.user_scenarios,
            scenario_spot_changes=self.scenario_spot_changes,
            scenario_iv_changes=self.scenario_iv_changes,
            scenario_days_passed=self.scenario_days_passed,
        )


class BuySideRecommendation(BaseModel):
    strategy_type: BuySideStrategyType
    score: float = Field(ge=0, le=100)
    rank: int = Field(ge=1)
    one_line_summary: str
    key_reasons: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)
    max_loss: float | None = None
    max_profit: float | None = None
    net_debit: float | None = None
    legs: list[BuySideStrategyLeg] = Field(default_factory=list)
    break_even: float | None = None
    required_move_pct: float | None = None
    theta_burn_7d_pct: float | None = None
    estimated_iv_crush_loss_pct: float | None = None
    liquidity_score: float | None = None
    risk_reward: float | None = None
    expected_move_pct: float | None = None
    target_vs_expected_move_ratio: float | None = None
    buyer_friendliness_score: float | None = None
    iv_crash_risk_score: float | None = None
    risk_attribution: dict[str, float]
    primary_risk_source: PrimaryRiskSource
    market_regime: Literal["Normal", "Elevated", "Panic", "Unknown"] | None = None
    market_regime_penalty: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    scenario_summary: BuySideScenarioLabSummary | None = None
    scenario_ev: BuySideScenarioEV | None = None
    demotion_badge: str | None = None
    demotion_reason: str | None = None


class BuySideDecisionResult(BaseModel):
    ticker: str
    thesis: BuySideDecisionRequest
    recommendations: list[BuySideRecommendation] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class BuySideAssistantResponse(BuySideDecisionResult):
    """Public API response contract for the buy-side assistant."""


def run_buy_side_decision(
    option_chain: pd.DataFrame,
    request: BuySideDecisionRequest,
    *,
    market_regime: VixRegimeSnapshot | None = None,
    max_recommendations: int = 10,
) -> BuySideDecisionResult:
    """Rank buy-side structures from supplied option-chain rows."""

    strategy_request = BuySideStrategyRequest(
        ticker=request.ticker,
        spot_price=request.spot_price,
        view_type=request.view_type,
        target_price=request.target_price,
        target_date=request.target_date,
        max_loss_budget=request.max_loss_budget,
        risk_preference=request.risk_preference,
        allow_capped_upside=request.allow_capped_upside,
        avoid_high_iv=request.avoid_high_iv,
        volatility_view=request.volatility_view,
        event_risk=request.event_risk,
        expected_iv_change_vol_points=request.expected_iv_change_vol_points,
        preferred_dte_range=request.preferred_dte_range,
        iv_rank=request.iv_rank,
        historical_volatility=request.historical_volatility,
        as_of_date=request.as_of_date,
        strategy_types=ALL_BUY_SIDE_STRATEGIES,
    )
    generated = generate_buy_side_candidates(
        option_chain,
        strategy_request,
        market_regime=market_regime,
        max_candidates=max(max_recommendations * 4, 40),
    )
    recommendations = [
        _recommendation_from_candidate(candidate, request)
        for candidate in generated.candidates
    ]
    ranked = sorted(
        recommendations,
        key=lambda item: (
            item.score,
            item.buyer_friendliness_score or 0.0,
            -(item.max_loss or math.inf),
            item.strategy_type,
            item.break_even or math.inf,
        ),
        reverse=True,
    )
    for index, item in enumerate(ranked, start=1):
        item.rank = index
    return BuySideDecisionResult(
        ticker=request.ticker.upper().strip(),
        thesis=request,
        recommendations=ranked[:max_recommendations],
        assumptions=[
            "Quantitative decision support only; no order placement is available.",
            "Decision rules select and demote structures deterministically.",
            "Composite scores rank candidates within each strategy type.",
            "Scenario output uses Greek approximation, not exact option pricing.",
        ],
    )


def _recommendation_from_candidate(
    candidate: BuySideStrategyCandidate,
    request: BuySideDecisionRequest,
) -> BuySideRecommendation:
    metrics = score_buy_side_contract(
        _primary_long_leg(candidate),
        user_target_move_pct=request.target_price / request.spot_price - 1,
        iv_rank=request.iv_rank,
        historical_volatility=request.historical_volatility,
        iv_crush_vol_points=request.expected_iv_change_vol_points or -5.0,
        event_risk=request.event_risk != "none",
        now=None,
    )
    decision = _decision_tree(candidate, request)
    adjusted_score = _clip(candidate.score.total_score + decision["score_adjustment"])
    if decision["demoted"]:
        adjusted_score = _clip(adjusted_score - 18.0)
    scenario = run_buy_side_scenario_lab(
        BuySideScenarioLabInput(
            current_spot=request.spot_price,
            current_date=request.as_of_date or pd.Timestamp.today().date().isoformat(),
            legs=candidate.legs,
            spot_change_pct=request.scenario_spot_changes,
            iv_change_vol_points=request.scenario_iv_changes,
            days_passed=request.scenario_days_passed,
            user_scenarios=request.user_scenarios,
        )
    )
    risk_attribution = _risk_attribution(candidate, metrics)
    primary_risk = max(risk_attribution, key=risk_attribution.get)
    required_move_pct = (
        candidate.breakeven / request.spot_price - 1
        if candidate.breakeven is not None
        else metrics.required_move_pct
    )
    risk_reward = (
        candidate.max_gain / candidate.max_loss
        if candidate.max_gain is not None
        and candidate.max_loss is not None
        and candidate.max_loss > 0
        else None
    )
    warnings = list(dict.fromkeys([*candidate.warnings, *decision["warnings"]]))
    summary = _summary(candidate, decision)
    reasons = _key_reasons(candidate, metrics, decision)
    risks = _key_risks(candidate, metrics, decision, primary_risk)
    _assert_safe_language(summary, reasons, risks)
    return BuySideRecommendation(
        strategy_type=candidate.strategy_type,
        score=adjusted_score,
        rank=1,
        one_line_summary=summary,
        key_reasons=reasons,
        key_risks=risks,
        max_loss=candidate.max_loss,
        max_profit=candidate.max_gain,
        net_debit=candidate.net_debit,
        legs=candidate.legs,
        break_even=candidate.breakeven,
        required_move_pct=required_move_pct,
        theta_burn_7d_pct=metrics.theta_burn_7d_pct,
        estimated_iv_crush_loss_pct=metrics.estimated_iv_crush_loss_pct,
        liquidity_score=metrics.liquidity_score,
        risk_reward=risk_reward,
        expected_move_pct=candidate.expected_move_pct or metrics.expected_move_pct,
        target_vs_expected_move_ratio=(
            candidate.target_vs_expected_move_ratio
            or metrics.target_vs_expected_move_ratio
        ),
        buyer_friendliness_score=(
            candidate.score.buyer_friendliness_score
            or metrics.buyer_friendliness_score
        ),
        iv_crash_risk_score=(
            candidate.score.iv_crash_risk_score or metrics.iv_crash_risk_score
        ),
        risk_attribution=risk_attribution,
        primary_risk_source=primary_risk,  # type: ignore[arg-type]
        market_regime=candidate.market_regime,
        market_regime_penalty=candidate.market_regime_penalty,
        warnings=warnings,
        scenario_summary=scenario.summary,
        scenario_ev=scenario.scenario_ev,
        demotion_badge="demoted_by_decision_tree" if decision["demoted"] else None,
        demotion_reason=decision["demotion_reason"],
    )


def _decision_tree(
    candidate: BuySideStrategyCandidate,
    request: BuySideDecisionRequest,
) -> dict[str, object]:
    strategy = candidate.strategy_type
    dte = candidate.legs[0].dte
    iv_rank = request.iv_rank
    score_adjustment = 0.0
    demoted = False
    prefer_reasons: list[str] = []
    demote_reasons: list[str] = []
    warnings: list[str] = []

    def prefer(amount: float, reason: str) -> None:
        nonlocal score_adjustment
        score_adjustment += amount
        prefer_reasons.append(reason)

    def demote(reason: str, amount: float = -10.0) -> None:
        nonlocal score_adjustment, demoted
        score_adjustment += amount
        demoted = True
        demote_reasons.append(reason)

    high_iv = iv_rank is not None and iv_rank > 60
    very_high_iv = iv_rank is not None and iv_rank > 70

    if dte < 14:
        if high_iv or request.volatility_view == "expect_iv_crush":
            if strategy == "bull_call_spread":
                prefer(14.0, "near-term high-IV setup favors a call spread")
            elif strategy == "long_call":
                demote("near-term IV crush risk demotes naked long calls")
                warnings.append("HIGH_IV_CRUSH_RISK")
        elif request.risk_preference == "aggressive" and strategy == "long_call":
            prefer(10.0, "aggressive near-term thesis can fit an ATM or slightly OTM long call")
    elif dte <= 60:
        if (
            iv_rank is not None
            and iv_rank < 40
            and request.volatility_view in {"auto", "prefer_low_iv", "expect_iv_expansion"}
            and request.view_type == "short_term_speculative_bullish"
        ):
            if strategy == "long_call":
                prefer(14.0, "low-IV short-term speculative thesis favors direct convexity")
        else:
            if strategy == "bull_call_spread":
                prefer(12.0, "short-term setup favors defined-risk spread structure")
            elif strategy == "long_call" and very_high_iv:
                demote("high IV rank demotes naked short-term long calls")
                warnings.append("HIGH_IV_CRUSH_RISK")
    elif dte > 180:
        if (
            request.view_type == "long_term_aggressive_bullish"
            and iv_rank is not None
            and iv_rank < 40
        ):
            if strategy == "leaps_call":
                prefer(18.0, "low-IV long-term aggressive thesis favors high-delta LEAPS")
        elif request.view_type == "long_term_conservative_bullish" or high_iv:
            if strategy == "leaps_call_spread":
                prefer(18.0, "long-term conservative or high-IV setup favors LEAPS call spread")
            elif strategy == "leaps_call" and high_iv:
                demote("high IV rank demotes naked LEAPS premium")

    if request.view_type == "long_term_aggressive_bullish":
        if strategy == "leaps_call" and not high_iv:
            prefer(12.0, "long-term aggressive thesis favors stock-replacement style exposure")
        elif strategy == "leaps_call_spread" and high_iv:
            prefer(10.0, "higher IV makes the spread structure more suitable")
        elif strategy in {"long_call", "bull_call_spread"}:
            demote("shorter-dated structure is less aligned with long-term thesis", -12.0)
    elif request.view_type == "long_term_conservative_bullish":
        if strategy == "leaps_call_spread":
            prefer(16.0, "long-term conservative thesis favors lower net premium and defined risk")
        elif strategy in {"long_call", "bull_call_spread"}:
            demote(
                "shorter-dated structure is less aligned with "
                "long-term conservative thesis",
                -12.0,
            )
    elif request.view_type == "short_term_speculative_bullish":
        if strategy == "long_call" and not high_iv and request.volatility_view != "expect_iv_crush":
            prefer(12.0, "fast bullish thesis can fit direct gamma exposure")
        elif strategy == "bull_call_spread" and (high_iv or request.event_risk != "none"):
            prefer(14.0, "high-IV or event setup favors a spread over naked premium")
        elif strategy in {"leaps_call", "leaps_call_spread"}:
            demote("LEAPS duration is less aligned with short-term speculative thesis", -12.0)
    elif request.view_type == "short_term_conservative_bullish":
        if strategy == "bull_call_spread":
            prefer(16.0, "short-term conservative thesis favors defined-risk spread")
        elif strategy == "long_call" and high_iv:
            demote("high-IV setup makes naked long call less aligned")
        elif strategy in {"leaps_call", "leaps_call_spread"}:
            demote("LEAPS duration is less aligned with short-term conservative thesis", -12.0)
    elif request.view_type == "event_driven_bullish":
        if request.event_risk != "none":
            warnings.append("EVENT_RISK")
        if high_iv and strategy in SPREAD_STRATEGIES:
            prefer(14.0, "event-driven high-IV setup favors vega-offsetting spread")
        elif high_iv and strategy in NAKED_LONG_STRATEGIES:
            demote("event-driven high-IV setup increases IV crush risk for naked long premium")
            warnings.append("HIGH_IV_CRUSH_RISK")

    if request.volatility_view == "expect_iv_crush" and strategy in NAKED_LONG_STRATEGIES:
        demote("explicit IV-crush view demotes naked long premium", -12.0)
        warnings.append("HIGH_IV_CRUSH_RISK")
    elif request.volatility_view == "expect_iv_crush" and strategy in SPREAD_STRATEGIES:
        prefer(10.0, "spread offsets part of long-vega exposure")
    elif request.volatility_view == "expect_iv_expansion" and strategy in NAKED_LONG_STRATEGIES:
        prefer(8.0, "IV-expansion view is more compatible with naked long premium")

    if candidate.market_regime == "Panic":
        warnings.append("MARKET_REGIME_PANIC")
    elif candidate.market_regime == "Elevated":
        warnings.append("MARKET_REGIME_ELEVATED")

    return {
        "score_adjustment": score_adjustment,
        "demoted": demoted,
        "demotion_reason": "; ".join(demote_reasons) if demoted else None,
        "preference_reason": "; ".join(prefer_reasons) if prefer_reasons else None,
        "warnings": warnings,
    }


def _primary_long_leg(candidate: BuySideStrategyCandidate):
    for leg in candidate.legs:
        if leg.side == "long":
            return leg
    return candidate.legs[0]


def _risk_attribution(candidate, metrics) -> dict[str, float]:
    values = {
        "direction": metrics.breakeven_difficulty_score
        if metrics.breakeven_difficulty_score is not None
        else candidate.risk_attribution.get("direction", 0.0),
        "time": metrics.theta_pain_score
        if metrics.theta_pain_score is not None
        else candidate.risk_attribution.get("time", 0.0),
        "volatility": metrics.iv_crash_risk_score
        if metrics.iv_crash_risk_score is not None
        else candidate.risk_attribution.get("volatility", 0.0),
        "liquidity": 100.0 - (metrics.liquidity_score or 0.0),
    }
    return {key: _clip(value) for key, value in values.items()}


def _summary(candidate, decision) -> str:
    label = _strategy_label(candidate.strategy_type)
    if decision["demoted"]:
        return f"{label} is visible but demoted because it is less suitable for the stated thesis."
    return f"{label} is more suitable for the stated thesis under the current assumptions."


def _key_reasons(candidate, metrics, decision) -> list[str]:
    reasons = []
    preference = decision.get("preference_reason")
    if preference:
        reasons.append(str(preference))
    if candidate.max_loss is not None:
        reasons.append(f"max loss is defined at approximately {candidate.max_loss:.2f}")
    if candidate.breakeven is not None:
        reasons.append(f"break-even is approximately {candidate.breakeven:.2f}")
    if metrics.liquidity_score is not None:
        reasons.append(f"liquidity score is {metrics.liquidity_score:.1f}/100")
    return reasons[:5]


def _key_risks(candidate, metrics, decision, primary_risk: str) -> list[str]:
    risks = [
        f"primary modeled risk source is {primary_risk}",
        "hidden costs include theta decay, IV premium, IV crush, and bid-ask spread",
    ]
    if metrics.theta_burn_7d_pct is not None:
        risks.append(f"7-day theta burn is about {metrics.theta_burn_7d_pct:.1%} of premium")
    if metrics.estimated_iv_crush_loss_pct is not None:
        risks.append(
            f"estimated IV crush loss is about {metrics.estimated_iv_crush_loss_pct:.1%} of premium"
        )
    if decision["demoted"]:
        risks.append(str(decision["demotion_reason"]))
    if candidate.max_gain is not None:
        risks.append("upside is capped by the short call leg")
    return risks[:6]


def _strategy_label(strategy: BuySideStrategyType) -> str:
    return {
        "long_call": "Long Call",
        "bull_call_spread": "Bull Call Spread",
        "leaps_call": "LEAPS Call",
        "leaps_call_spread": "LEAPS Call Spread",
    }[strategy]


def _assert_safe_language(summary: str, reasons: list[str], risks: list[str]) -> None:
    text = " ".join([summary, *reasons, *risks]).lower()
    if any(term in text for term in ADVICE_BANNED_TERMS):
        raise ValueError("recommendation explanation contains disallowed advice language")


def _clip(value: float) -> float:
    return min(max(float(value), 0.0), 100.0)
