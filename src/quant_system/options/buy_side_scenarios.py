from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from quant_system.options.models import (
    BuySideScenarioContribution,
    BuySideScenarioEV,
    BuySideStrategyLeg,
)

PricingMethod = Literal["greek_approximation"]
ApproximationReliability = Literal["high", "medium", "low"]
ScenarioWarning = Literal[
    "GREEK_UNIT_ASSUMPTION",
    "MISSING_GREEKS",
    "LOW_APPROXIMATION_RELIABILITY",
    "INVALID_USER_SCENARIO_PROBABILITIES",
    "SUBJECTIVE_EV_NOT_MARKET_PROBABILITY",
]

THETA_UNIT_ASSUMPTION = "theta is treated as option price change per contract per day"
VEGA_UNIT_ASSUMPTION = "vega is treated as option price change per 1 volatility point"


class BuySideUserScenarioPnL(BaseModel):
    label: str
    probability: float = Field(ge=0, le=1)
    spot_change_pct: float
    iv_change_vol_points: float
    days_passed: int = Field(ge=0)


class BuySideScenarioLabInput(BaseModel):
    current_spot: float = Field(gt=0)
    current_date: str
    legs: list[BuySideStrategyLeg] = Field(min_length=1)
    spot_change_pct: list[float]
    iv_change_vol_points: list[float]
    days_passed: list[int] | int = 0
    pricing_method: PricingMethod = "greek_approximation"
    user_scenarios: list[BuySideUserScenarioPnL] = Field(default_factory=list)


class BuySideScenarioPnLResult(BaseModel):
    spot_change_pct: float
    iv_change_vol_points: float
    days_passed: int
    estimated_value: float
    estimated_pnl: float
    approximation_reliability: ApproximationReliability
    warnings: list[ScenarioWarning] = Field(default_factory=list)


class BuySideScenarioMatrixCell(BaseModel):
    spot_change_pct: float
    iv_change_vol_points: float
    days_passed: int
    estimated_pnl: float
    approximation_reliability: ApproximationReliability


class BuySideScenarioLabSummary(BaseModel):
    best_case_pnl: float | None = None
    worst_case_pnl: float | None = None
    flat_spot_iv_crush_pnl: float | None = None
    spot_up_iv_down_pnl: float | None = None
    theta_only_pnl: float | None = None
    probability_not_calculated: bool = True


class BuySideScenarioLabResult(BaseModel):
    pricing_method: PricingMethod
    results: list[BuySideScenarioPnLResult]
    matrix: list[BuySideScenarioMatrixCell]
    summary: BuySideScenarioLabSummary
    scenario_ev: BuySideScenarioEV | None = None
    warnings: list[ScenarioWarning] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


def run_buy_side_scenario_lab(
    scenario_input: BuySideScenarioLabInput,
) -> BuySideScenarioLabResult:
    """Run Greek approximation scenarios for a supplied buy-side strategy."""

    days_values = (
        scenario_input.days_passed
        if isinstance(scenario_input.days_passed, list)
        else [scenario_input.days_passed]
    )
    results = [
        _run_single_scenario(
            legs=scenario_input.legs,
            current_spot=scenario_input.current_spot,
            spot_change_pct=spot_change,
            iv_change_vol_points=iv_change,
            days_passed=days,
        )
        for days in days_values
        for spot_change in scenario_input.spot_change_pct
        for iv_change in scenario_input.iv_change_vol_points
    ]
    warnings = _collect_warnings(results)
    scenario_ev = _scenario_ev(scenario_input)
    if scenario_ev is None and scenario_input.user_scenarios:
        warnings.append("INVALID_USER_SCENARIO_PROBABILITIES")
    elif scenario_ev is not None:
        warnings.append("SUBJECTIVE_EV_NOT_MARKET_PROBABILITY")
    return BuySideScenarioLabResult(
        pricing_method=scenario_input.pricing_method,
        results=results,
        matrix=[
            BuySideScenarioMatrixCell(
                spot_change_pct=item.spot_change_pct,
                iv_change_vol_points=item.iv_change_vol_points,
                days_passed=item.days_passed,
                estimated_pnl=item.estimated_pnl,
                approximation_reliability=item.approximation_reliability,
            )
            for item in results
        ],
        summary=_summary(results),
        scenario_ev=scenario_ev,
        warnings=list(dict.fromkeys(warnings)),
        assumptions=[
            THETA_UNIT_ASSUMPTION,
            VEGA_UNIT_ASSUMPTION,
            "Greek approximation only; no exact option pricing or probability of profit.",
            "Reliability falls for spot changes above +/-15% or time passed above 30 days.",
            "Vanna, charm, and vomma are ignored.",
        ],
    )


def _run_single_scenario(
    *,
    legs: list[BuySideStrategyLeg],
    current_spot: float,
    spot_change_pct: float,
    iv_change_vol_points: float,
    days_passed: int,
) -> BuySideScenarioPnLResult:
    strategy_value = 0.0
    strategy_pnl = 0.0
    warnings: list[ScenarioWarning] = ["GREEK_UNIT_ASSUMPTION"]
    reliability = _reliability(
        spot_change_pct=spot_change_pct,
        days_passed=days_passed,
    )
    if reliability == "low":
        warnings.append("LOW_APPROXIMATION_RELIABILITY")
    for leg in legs:
        estimated_value, pnl, leg_warnings = _estimate_leg(
            leg=leg,
            current_spot=current_spot,
            spot_change_pct=spot_change_pct,
            iv_change_vol_points=iv_change_vol_points,
            days_passed=days_passed,
        )
        signed_value = estimated_value if leg.side == "long" else -estimated_value
        strategy_value += signed_value * leg.contract_size
        strategy_pnl += pnl * leg.contract_size
        warnings.extend(leg_warnings)
    return BuySideScenarioPnLResult(
        spot_change_pct=spot_change_pct,
        iv_change_vol_points=iv_change_vol_points,
        days_passed=days_passed,
        estimated_value=max(strategy_value, 0.0) if len(legs) == 1 else strategy_value,
        estimated_pnl=strategy_pnl,
        approximation_reliability=reliability,
        warnings=list(dict.fromkeys(warnings)),
    )


def _estimate_leg(
    *,
    leg: BuySideStrategyLeg,
    current_spot: float,
    spot_change_pct: float,
    iv_change_vol_points: float,
    days_passed: int,
) -> tuple[float, float, list[ScenarioWarning]]:
    entry_value = leg.mid_price or 0.0
    warnings: list[ScenarioWarning] = []
    if leg.delta is None or leg.gamma is None or leg.theta is None or leg.vega is None:
        warnings.append("MISSING_GREEKS")
        new_value = entry_value
    else:
        spot_change_abs = current_spot * (spot_change_pct / 100)
        raw_value = (
            entry_value
            + leg.delta * spot_change_abs
            + 0.5 * leg.gamma * (spot_change_abs**2)
            + leg.vega * iv_change_vol_points
            + leg.theta * days_passed
        )
        new_value = max(raw_value, 0.0)
    pnl_per_share = (
        new_value - entry_value if leg.side == "long" else entry_value - new_value
    )
    return new_value, pnl_per_share, warnings


def _reliability(*, spot_change_pct: float, days_passed: int) -> ApproximationReliability:
    abs_move = abs(spot_change_pct)
    if abs_move > 15 or days_passed > 30:
        return "low"
    if abs_move > 10 or days_passed > 14:
        return "medium"
    return "high"


def _scenario_ev(scenario_input: BuySideScenarioLabInput) -> BuySideScenarioEV | None:
    scenarios = scenario_input.user_scenarios
    if not scenarios:
        return None
    probability_sum = sum(item.probability for item in scenarios)
    if not math.isclose(probability_sum, 1.0, abs_tol=1e-6):
        return None
    contributions = []
    expected_value = 0.0
    for item in scenarios:
        result = _run_single_scenario(
            legs=scenario_input.legs,
            current_spot=scenario_input.current_spot,
            spot_change_pct=item.spot_change_pct,
            iv_change_vol_points=item.iv_change_vol_points,
            days_passed=item.days_passed,
        )
        contribution = item.probability * result.estimated_pnl
        expected_value += contribution
        contributions.append(
            BuySideScenarioContribution(
                label=item.label,
                probability=item.probability,
                pnl=result.estimated_pnl,
                expected_value_contribution=contribution,
            )
        )
    return BuySideScenarioEV(
        expected_value=expected_value,
        contributions=contributions,
    )


def _summary(results: list[BuySideScenarioPnLResult]) -> BuySideScenarioLabSummary:
    if not results:
        return BuySideScenarioLabSummary()
    pnls = [item.estimated_pnl for item in results]
    return BuySideScenarioLabSummary(
        best_case_pnl=max(pnls),
        worst_case_pnl=min(pnls),
        flat_spot_iv_crush_pnl=_find_pnl(results, spot=0, iv=-5),
        spot_up_iv_down_pnl=_find_pnl(results, spot=10, iv=-5),
        theta_only_pnl=_find_pnl(results, spot=0, iv=0, prefer_positive_days=True),
        probability_not_calculated=True,
    )


def _find_pnl(
    results: list[BuySideScenarioPnLResult],
    *,
    spot: float,
    iv: float,
    prefer_positive_days: bool = False,
) -> float | None:
    matches = [
        item
        for item in results
        if item.spot_change_pct == spot
        and item.iv_change_vol_points == iv
        and (not prefer_positive_days or item.days_passed > 0)
    ]
    if not matches:
        return None
    return matches[0].estimated_pnl


def _collect_warnings(results: list[BuySideScenarioPnLResult]) -> list[ScenarioWarning]:
    warnings: list[ScenarioWarning] = []
    for item in results:
        warnings.extend(item.warnings)
    return list(dict.fromkeys(warnings))
