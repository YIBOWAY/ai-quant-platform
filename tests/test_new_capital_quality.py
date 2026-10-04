"""Artificial fixed inputs; no provider, identity adapter or quality core is mocked."""
from __future__ import annotations

import copy
import math
from datetime import date, timedelta

import pytest

from quant_system.research.capital_quality import evaluate_new_capital_quality
from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.correlation_v2 import concentration_v2
from quant_system.research.gate_v2.family import FAMILY_RULE_VERSION
from quant_system.research.gate_v2.verdict import GATE_V2_CONFIG
from quant_system.research.trials import cost_sensitivity_verdict, performance_from_daily_returns


def artificial_inputs(n_members=12, n=252, *, active=False):
    """Synthetic family/curves, explicitly not a disk-verified family qualification."""
    total = [0.002 + 0.001 * math.sin(i) for i in range(n)]
    selected = [value - 0.0001 for value in total] if active else list(total)
    days = [(date(2020, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
    contract = {
        "schema": "research_family_compatibility/v1",
        "return_definition": "arithmetic_net_active" if active else "net_total_return",
        "benchmark": ({"symbol": "SPY", "method": "net_buy_and_hold"} if active
                      else {"symbol": None, "method": "none"}),
        "frequency": "daily",
        "cost_definition": {"model": "proportional_bps", "commission_bps": 1.0,
                            "slippage_bps": 5.0, "cash_interest": 0.0},
        "market_data_contract": {"provider": "artificial_fixture", "price_adjustment": "none",
                                 "currency": "USD", "bar": "1d"},
    }
    members = []
    for member in range(n_members):
        values = [0.00001 * member + 0.005 * math.sin(0.71 * i + member) for i in range(n)]
        perf = performance_from_daily_returns(values)
        members.append({"trial_id": f"synthetic-{member}", "n_periods": n,
                        "recomputed_sharpe": perf["sharpe_period"]})
    family = {
        "rule_version": FAMILY_RULE_VERSION,
        "compatibility_contract": contract,
        "members": members,
        "n_trials": len(members),
        "n_applicable_trials": len(members),
        "excluded": [],
        "out_of_scope": [],
        "trusted": bool(members),
        "coverage_shortfall": 0.0,
        "evidence_state": ("empty" if not members else "insufficient_members" if n_members < 3
                           else "small_family" if n_members < 10 else "complete"),
    }
    family["family_digest"] = _hash(family)
    perf = performance_from_daily_returns(total)
    cost = cost_sensitivity_verdict(
        annual_return=(1 + perf["total_return"]) ** (252 / n) - 1,
        annual_turnover=1.0, cost_bps=6.0,
    )
    cost.update(method="extra_linear_cost_penalty_on_net_return", exact_replay=False,
                extra_cost_multiplier=2.0)
    return dict(selected_returns=selected, total_returns=total, dates=days,
                return_contract=contract, family=family,
                concentration=concentration_v2(active={"equity_returns": total, "dates": days},
                                             require_dates=True),
                cost=cost, config=GATE_V2_CONFIG)


@pytest.mark.parametrize("n_members,expected_tier", [(0, "T0"), (1, "T0"), (2, "T0"),
                                                   (3, "T1"), (9, "T1"), (10, "T2")])
def test_family_size_and_existing_grade_are_distinct_from_psr(n_members, expected_tier):
    report = evaluate_new_capital_quality(**artificial_inputs(n_members))
    assert report["tier"] == expected_tier
    assert report["eligible"] is (n_members >= 10)
    if 3 <= n_members < 10:
        assert report["dsr"]["passed"] is True
        assert report["dsr"]["threshold_sr"] == 0.0
        assert "unfunded_tier" in report["reasons"]
    assert report["funding_authority"] is False


def test_small_family_can_pass_psr_but_does_not_authorize_new_capital():
    report = evaluate_new_capital_quality(**artificial_inputs(3))
    assert report["dsr"]["passed"] is True
    assert report["tier"] == "T1"
    assert report["eligible"] is False
    assert report["return_definition"] == "net_total_return"


@pytest.mark.parametrize("active", [False, True])
def test_complete_proven_quality_can_be_eligible_under_each_explicit_return_object(active):
    inputs = artificial_inputs(active=active)
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is True
    assert report["tier"] == "T2"
    assert report["return_contract"] == inputs["return_contract"]
    assert report["funding_authority"] is False


@pytest.mark.parametrize("bad_contract", [None, {}, {"return_definition": "net_total_return"}])
def test_missing_contract_is_a_named_refusal_not_an_exception(bad_contract):
    inputs = artificial_inputs()
    inputs["return_contract"] = bad_contract
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "return_contract_invalid" in report["reasons"]


@pytest.mark.parametrize("active", [False, True])
def test_return_object_cannot_claim_the_other_benchmark_semantics(active):
    inputs = artificial_inputs(active=active)
    inputs["return_contract"]["benchmark"] = (
        {"symbol": None, "method": "none"} if active
        else {"symbol": "SPY", "method": "net_buy_and_hold"}
    )
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "return_contract_invalid" in report["reasons"]


def test_total_return_object_cannot_hide_different_selected_returns():
    inputs = artificial_inputs()
    inputs["selected_returns"][0] += 0.01
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "net_total_selected_returns_mismatch" in report["reasons"]


def test_legacy_no_contract_family_is_historical_only():
    inputs = artificial_inputs()
    inputs["family"]["rule_version"] = None
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "current_family_rule_required" in report["reasons"]


def test_any_in_family_missing_evidence_blocks_money_even_with_old_budget_trusted():
    inputs = artificial_inputs()
    inputs["family"].update(excluded=[{"trial_id": "missing", "reason": "curve_missing"}],
                            n_applicable_trials=13, coverage_shortfall=1 / 13,
                            evidence_state="incomplete_evidence")
    report = evaluate_new_capital_quality(**inputs)
    assert report["grade"]["grade"] == "D2_supported"
    assert report["eligible"] is False
    assert "family_evidence_incomplete" in report["reasons"]


@pytest.mark.parametrize("defect", ["count", "duplicate", "nan", "short", "non_integer", "state",
                                    "coverage"])
def test_malformed_member_census_cannot_become_eligible(defect):
    inputs = artificial_inputs()
    family = inputs["family"]
    if defect == "count":
        family["n_trials"] = 100
    elif defect == "duplicate":
        family["members"][1]["trial_id"] = family["members"][0]["trial_id"]
    elif defect == "nan":
        family["members"][0]["recomputed_sharpe"] = float("nan")
    elif defect == "short":
        family["members"][0]["n_periods"] = 19
    elif defect == "non_integer":
        family["members"][0]["n_periods"] = 252.1
    elif defect == "state":
        family["evidence_state"] = None
    else:
        family["coverage_shortfall"] = 0.2
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "family_members_invalid" in report["reasons"]


@pytest.mark.parametrize(
    "defect", ["missing_dates", "duplicate_dates", "length", "nan", "infinite"],
)
def test_bad_curve_blocks_before_statistics_can_drop_observations(defect):
    inputs = artificial_inputs()
    if defect == "missing_dates":
        inputs["dates"] = None
    elif defect == "duplicate_dates":
        inputs["dates"][-1] = inputs["dates"][0]
    elif defect == "length":
        inputs["total_returns"].pop()
    else:
        inputs["selected_returns"][0] = float("nan") if defect == "nan" else float("inf")
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert any(reason.startswith(("decision_", "total_")) for reason in report["reasons"])


@pytest.mark.parametrize("bad_cost", [None, {}, {"passed": True},
                                      {"passed": True, "method": "unknown"}])
def test_cost_self_assertion_is_not_the_supported_cost_object(bad_cost):
    inputs = artificial_inputs()
    inputs["cost"] = bad_cost
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "cost_evidence_invalid" in report["reasons"]


@pytest.mark.parametrize("field,value", [("cost_bps", 0), ("multiplier", 1),
                                         ("net_return_at_2x", float("nan")),
                                         ("cost_drag_annual_1x", -0.1),
                                         ("net_return_at_2x", -0.1),
                                         ("exact_replay", True)])
def test_cost_method_numbers_and_pass_flag_must_agree(field, value):
    inputs = artificial_inputs()
    inputs["cost"][field] = value
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "cost_evidence_invalid" in report["reasons"]


def test_unknown_peer_is_not_no_peer():
    inputs = artificial_inputs()
    inputs["concentration"] = concentration_v2(
        active={"equity_returns": inputs["total_returns"], "dates": inputs["dates"]},
        hung_sleeves=[{"sleeve_id": "existing", "returns": inputs["total_returns"], "dates": None}],
        require_dates=True,
    )
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "correlation_unmeasured_blocked" in report["reasons"]


def test_forged_no_peer_header_does_not_hide_unavailable_sleeve():
    inputs = artificial_inputs()
    inputs["concentration"].update(raw_unavailable_sleeves=["actual-peer"])
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "correlation_unmeasured_blocked" in report["reasons"]


def test_quality_computation_is_same_for_identical_inputs_and_does_not_mutate_them():
    d34_adapter = artificial_inputs()
    intake_adapter = copy.deepcopy(d34_adapter)
    before = copy.deepcopy(d34_adapter)
    assert evaluate_new_capital_quality(**d34_adapter) == evaluate_new_capital_quality(
        **intake_adapter,
    )
    assert d34_adapter == before


def test_unrelated_family_rows_do_not_change_this_quality_decision():
    inputs = artificial_inputs()
    original = evaluate_new_capital_quality(**inputs)
    inputs["family"]["out_of_scope"] = [
        {"trial_id": "other-pool", "reason": "universe_mismatch"},
    ]
    assert evaluate_new_capital_quality(**inputs) == original


def test_short_candidate_and_unhealthy_total_returns_never_receive_t2():
    short = evaluate_new_capital_quality(**artificial_inputs(n=60))
    assert short["eligible"] is False
    assert short["dsr"]["reason"] == "candidate_window_too_short"
    inputs = artificial_inputs(active=True)
    inputs["total_returns"] = [-0.01 + 0.001 * math.sin(i) for i in range(252)]
    report = evaluate_new_capital_quality(**inputs)
    assert report["eligible"] is False
    assert "health_failed" in report["reasons"]


def _combined_qlib_inputs(*, active=False, **changes):
    inputs = artificial_inputs(active=active)
    inputs["return_contract"]["cost_definition"] = {
        "model": "qlib_combined_bps", "one_way_bps": 6.0,
        "min_cost": 0.0, "cash_interest": 0.0, **changes,
    }
    inputs["family"]["family_digest"] = _hash({
        key: value for key, value in inputs["family"].items() if key != "family_digest"
    })
    return inputs


def test_combined_d34_net_total_contract_can_meet_the_same_minimum_quality():
    proportional = artificial_inputs()
    combined = _combined_qlib_inputs()
    first = evaluate_new_capital_quality(**proportional)
    second = evaluate_new_capital_quality(**combined)
    assert first["eligible"] is second["eligible"] is True
    assert first["tier"] == second["tier"] == "T2"
    assert first["dsr"]["value"] == second["dsr"]["value"]
    assert first["grade"] == second["grade"]
    assert first["health"] == second["health"]
    # Same minimum quality is not proof that execution/cost models are equivalent
    # and does not merge the two evidence families.
    assert first["return_contract"] != second["return_contract"]
    assert first["family_digest"] != second["family_digest"]
    assert second["return_contract"]["cost_definition"]["model"] == "qlib_combined_bps"
    assert second["funding_authority"] is False


@pytest.mark.parametrize("changes", [{"one_way_bps": 7.0}, {"min_cost": 1.0},
                                     {"cash_interest": 0.01}])
def test_combined_cost_contract_outside_six_bps_zero_minimum_scope_is_refused(changes):
    report = evaluate_new_capital_quality(**_combined_qlib_inputs(**changes))
    assert report["eligible"] is False
    assert "return_contract_invalid" in report["reasons"]


def test_combined_cost_contract_does_not_expand_active_return_qualification():
    report = evaluate_new_capital_quality(**_combined_qlib_inputs(active=True))
    assert report["eligible"] is False
    assert "return_contract_invalid" in report["reasons"]
