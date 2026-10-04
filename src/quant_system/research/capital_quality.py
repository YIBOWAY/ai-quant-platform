"""Shared minimum evidence for new paper capital, never an identity authority.

Callers verify original receipts, current family, peers and qualifications before
consuming this pure report. The grade, quality eligibility and committed capital
are distinct. Already-funded idempotent recovery does not call this function.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping

from quant_system.research.gate_v2.correlation_v2 import _concentration_curve
from quant_system.research.gate_v2.dsr_v2 import evaluate_dsr_v2
from quant_system.research.gate_v2.family import FAMILY_RULE_VERSION, _compatibility_contract
from quant_system.research.gate_v2.health_v2 import health_checks_v2


def _finite(value):
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def _contract(value):
    try:
        contract = _compatibility_contract(value)
    except (OverflowError, TypeError, ValueError):
        return None
    definition, benchmark = contract["return_definition"], contract["benchmark"]
    cost = contract["cost_definition"]
    # The D34 producer records one combined Qlib rate, not a proven split into
    # commission and slippage. Accept its own explicit net-total contract while
    # retaining a separate compatible family and no execution-equivalence claim.
    supported_cost = cost == {
        "model": "proportional_bps", "commission_bps": 1.0,
        "slippage_bps": 5.0, "cash_interest": 0.0,
    } or definition == "net_total_return" and cost == {
        "model": "qlib_combined_bps", "one_way_bps": 6.0,
        "min_cost": 0.0, "cash_interest": 0.0,
    }
    if (
        contract["frequency"] != "daily"
        or definition not in {"net_total_return", "arithmetic_net_active"}
        or definition == "net_total_return" and benchmark != {"symbol": None, "method": "none"}
        or definition == "arithmetic_net_active" and (
            not benchmark["symbol"] or benchmark["method"] != "net_buy_and_hold"
        )
        or not supported_cost
    ):
        return None
    return contract


def _members_valid(family, config):
    members, excluded = family.get("members"), family.get("excluded")
    if not isinstance(members, list) or not isinstance(excluded, list):
        return False
    if any(
        not isinstance(row, Mapping)
        or not isinstance(row.get("trial_id"), str) or not row["trial_id"].strip()
        or type(row.get("n_periods")) is not int
        or row["n_periods"] < config["dsr_family_min_periods"]
        or not _finite(row.get("recomputed_sharpe"))
        for row in members
    ):
        return False
    count = len(members)
    expected_shortfall = len(excluded) / (count + len(excluded)) if count or excluded else 0.0
    state = (
        "incomplete_evidence" if excluded else "empty" if not count
        else "insufficient_members" if count < config["dsr_small_family_min_members"]
        else "small_family" if count < config["dsr_family_min_entries"] else "complete"
    )
    return (
        len({row["trial_id"] for row in members}) == count
        and type(family.get("n_trials")) is int and family["n_trials"] == count
        and type(family.get("n_applicable_trials")) is int
        and family["n_applicable_trials"] == count + len(excluded)
        and _finite(family.get("coverage_shortfall"))
        and family["coverage_shortfall"] == expected_shortfall
        and family.get("evidence_state") == state
        and isinstance(family.get("family_digest"), str)
        and re.fullmatch(r"[0-9a-f]{64}", family["family_digest"]) is not None
    )


def _correlation_measured(concentration, config):
    """Check the structured result's internal shape, never authenticate its peers."""
    rows = concentration.get("raw_by_sleeve")
    diagnostics = concentration.get("raw_peer_diagnostics")
    missing = concentration.get("raw_unavailable_sleeves")
    if not all(isinstance(value, list) for value in (rows, diagnostics, missing)) or missing:
        return False
    if concentration.get("raw_limit") != config["correlation_max"]:
        return False
    status = concentration.get("raw_status")
    if status == "not_applicable":
        return (
            concentration.get("raw_reason") == "no_peers"
            and not rows and not diagnostics and concentration.get("raw_max") is None
            and not concentration.get("applicable", False)
            and concentration.get("n_hung_sleeves", 0) == 0
        )
    if status != "evaluated" or concentration.get("dates_required") is not True or not rows:
        return False
    if len(rows) != len(diagnostics) or any(
        not isinstance(row, Mapping) or not _finite(row.get("correlation"))
        or not isinstance(row.get("sleeve_id"), str) or not row["sleeve_id"]
        for row in rows
    ):
        return False
    if len({row["sleeve_id"] for row in rows}) != len(rows):
        return False
    for row, detail in zip(rows, diagnostics, strict=True):
        if (
            not isinstance(detail, Mapping) or detail.get("sleeve_id") != row["sleeve_id"]
            or detail.get("status") != "evaluated" or detail.get("reason") is not None
            or detail.get("correlation") != row["correlation"]
            or detail.get("alignment") != "calendar_dates"
            or type(detail.get("shared_observations")) is not int
            or detail["shared_observations"] < 20
        ):
            return False
    maximum = max(row["correlation"] for row in rows)
    return (
        concentration.get("raw_max") == maximum
        and concentration.get("raw_passed") is (maximum <= config["correlation_max"])
    )


def _cost_valid(cost, contract):
    """Current supported legacy linear stress, explicitly not an exact replay.

    The caller binds these numbers to original performance/turnover evidence.
    A future qualified replay needs its own explicit supported method adapter.
    """
    if not isinstance(cost, Mapping) or contract is None:
        return False
    numeric = ("net_return_at_2x", "cost_drag_annual_1x", "multiplier", "cost_bps",
               "extra_cost_multiplier")
    if not all(_finite(cost.get(key)) for key in numeric):
        return False
    definition = contract["cost_definition"]
    base_bps = (
        definition["one_way_bps"] if definition["model"] == "qlib_combined_bps"
        else definition["commission_bps"] + definition["slippage_bps"]
    )
    return (
        cost.get("method") == "extra_linear_cost_penalty_on_net_return"
        and cost.get("exact_replay") is False
        and cost["multiplier"] == cost["extra_cost_multiplier"] == 2.0
        and cost["cost_bps"] == base_bps
        and cost["cost_drag_annual_1x"] >= 0
        and cost.get("passed") is (cost["net_return_at_2x"] > 0)
    )


def evaluate_new_capital_quality(
    *, selected_returns, total_returns, return_contract, family,
    concentration, cost, config, dates=None,
) -> dict:
    """Recompute DSR, health and grade under the explicit selected return object.

    The historical helper parameter ``active_returns`` holds the selected series;
    the output names its real definition. Net total return never gains a made-up
    zero benchmark. This function does not mint provenance or fund a candidate.
    """
    from quant_system.research.gate_v2.verdict import grade_v2, tier_for_grade

    selected, days, selected_error = _concentration_curve(
        selected_returns, dates, require_dates=True,
    )
    total, _, total_error = _concentration_curve(total_returns, dates, require_dates=True)
    family = family if isinstance(family, Mapping) else {}
    concentration = concentration if isinstance(concentration, Mapping) else {}
    contract = _contract(return_contract)
    reasons = []
    if selected_error:
        reasons.append("decision_" + selected_error)
    if total_error:
        reasons.append("total_" + total_error)
    if len(selected) != len(total):
        reasons.append("decision_total_length_mismatch")
    if contract is None:
        reasons.append("return_contract_invalid")
    elif contract["return_definition"] == "net_total_return" and selected != total:
        reasons.append("net_total_selected_returns_mismatch")
    if family.get("rule_version") != FAMILY_RULE_VERSION:
        reasons.append("current_family_rule_required")
    if contract is None or family.get("compatibility_contract") != contract:
        reasons.append("family_return_contract_mismatch")
    members_valid = _members_valid(family, config)
    if not members_valid:
        reasons.append("family_members_invalid")
    # Keep the historical coverage-budget grade, but require every applicable
    # member's evidence for fresh money. Unrelated out_of_scope rows stay separate.
    if family.get("excluded") or family.get("evidence_state") in {
        "incomplete_evidence", "empty", "insufficient_members",
    }:
        reasons.append("family_evidence_incomplete")
    if family.get("trusted") is not True:
        reasons.append("family_evidence_untrusted")
    if not _correlation_measured(concentration, config):
        reasons.append("correlation_unmeasured_blocked")
    if concentration.get("raw_passed") is not True:
        reasons.append("concentration_raw_failed")
    if not _cost_valid(cost, contract):
        reasons.append("cost_evidence_invalid")
    if not isinstance(cost, Mapping) or cost.get("passed") is not True:
        reasons.append("cost_sensitivity_failed")
    active = {"active_returns": selected, "equity_returns": total,
              "n_periods": len(selected)}
    # Invalid member rows are not silently filtered into a smaller passing family.
    # Their statistics are unavailable and the eligibility reason stays explicit.
    statistical_family = family if members_valid else {**family, "members": []}
    dsr = evaluate_dsr_v2(
        active=active, family=statistical_family, dsr_min=config["dsr_v2_min"], config=config,
    )
    health = health_checks_v2(active=active, config=config)
    grade = grade_v2(
        dsr=dsr, health=health, concentration=concentration,
        upgrade={"applicable": False}, family=family, config=config,
    )
    tier = tier_for_grade(grade["grade"])
    if tier != "T2":
        reasons.append("unfunded_tier")
    if dsr.get("passed") is not True:
        reasons.append("dsr_failed")
    if health.get("passed") is not True:
        reasons.append("health_failed")
    members = family.get("members")
    return {
        "schema": "new_paper_capital_minimum_quality/v1",
        "eligible": not reasons, "reasons": sorted(set(reasons)),
        "grade": grade, "tier": tier, "dsr": dsr, "health": health,
        "return_definition": contract["return_definition"] if contract else None,
        "return_contract": contract, "family_digest": family.get("family_digest"),
        "n_family_members": len(members) if isinstance(members, list) else 0,
        "n_observations": len(selected), "dates_valid": days is not None and not selected_error,
        "concentration": dict(concentration), "cost": cost,
        "funding_authority": False,
    }
