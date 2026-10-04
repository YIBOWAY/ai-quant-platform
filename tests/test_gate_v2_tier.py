"""Tier rules: the decision table, the capital map, and the no-consumer invariant."""

from __future__ import annotations

import inspect

import pytest

from quant_system.execution import assistant_remote
from quant_system.research import gate_v2 as g
from quant_system.research import strategy_library


def _dsr(*, passed: bool, n_periods: int = 200, path: str = "data_driven") -> dict:
    return {
        "passed": passed,
        "n_periods": n_periods,
        "path": path,
        "value": 0.99,
        "dsr_min_used": 0.95,
    }


def _health(*, passed: bool, reasons=()) -> dict:
    return {"passed": passed, "reasons": list(reasons)}


def _concentration(*, applicable: bool = False, raw_passed: bool | None = None) -> dict:
    return {"applicable": applicable, "raw_passed": raw_passed}


def _upgrade(*, applicable: bool = False, accepted: bool | None = None, evidence=None) -> dict:
    return {"applicable": applicable, "upgrade_accepted": accepted, "accepted_evidence": evidence}


def _family(*, trusted: bool = True) -> dict:
    return {"trusted": trusted}


def _grade(dsr, health, concentration, upgrade, family) -> str:
    return g.grade_v2(
        dsr=dsr,
        health=health,
        concentration=concentration,
        upgrade=upgrade,
        family=family,
        config=g.GATE_V2_CONFIG,
    )["grade"]


@pytest.mark.parametrize(
    "dsr_passed,health_passed,expected",
    [
        (False, True, g.GRADE_INSUFFICIENT),
        (True, False, g.GRADE_INSUFFICIENT),
        (False, False, g.GRADE_INSUFFICIENT),
        (True, True, g.GRADE_SUPPORTED),
    ],
)
def test_grade_decision_table(dsr_passed: bool, health_passed: bool, expected: str) -> None:
    grade = _grade(
        _dsr(passed=dsr_passed),
        _health(passed=health_passed),
        _concentration(),
        _upgrade(),
        _family(),
    )
    assert grade == expected


def test_short_candidate_window_caps_at_d0() -> None:
    grade = _grade(
        _dsr(passed=True, n_periods=100),
        _health(passed=True),
        _concentration(),
        _upgrade(),
        _family(),
    )
    assert grade == g.GRADE_INSUFFICIENT


def test_raw_concentration_failure_caps_at_d0() -> None:
    grade = _grade(
        _dsr(passed=True),
        _health(passed=True),
        _concentration(applicable=True, raw_passed=False),
        _upgrade(),
        _family(),
    )
    assert grade == g.GRADE_INSUFFICIENT


def test_untrusted_family_makes_d1() -> None:
    grade = _grade(
        _dsr(passed=True),
        _health(passed=True),
        _concentration(),
        _upgrade(),
        _family(trusted=False),
    )
    assert grade == g.GRADE_MARGINAL


def test_small_family_path_makes_d1() -> None:
    grade = _grade(
        _dsr(passed=True, path="small_family_fixed"),
        _health(passed=True),
        _concentration(),
        _upgrade(),
        _family(),
    )
    assert grade == g.GRADE_MARGINAL


def test_rejected_upgrade_caps_at_d0_and_accepted_supports() -> None:
    rejected = _grade(
        _dsr(passed=True),
        _health(passed=True),
        _concentration(applicable=False),
        _upgrade(applicable=True, accepted=False),
        _family(),
    )
    accepted = _grade(
        _dsr(passed=True),
        _health(passed=True),
        _concentration(applicable=False),
        _upgrade(applicable=True, accepted=True, evidence="primary"),
        _family(),
    )
    assert rejected == g.GRADE_INSUFFICIENT
    assert accepted == g.GRADE_SUPPORTED


@pytest.mark.parametrize(
    "grade,tier,capital",
    [
        (g.GRADE_INSUFFICIENT, "T0", 0.0),
        (g.GRADE_MARGINAL, "T1", 0.0),
        (g.GRADE_SUPPORTED, "T2", 10_000.0),
    ],
)
def test_tier_mapping_and_capital(grade: str, tier: str, capital: float) -> None:
    assert g.tier_for_grade(grade) == tier
    assert g.TIER_CAPITAL_USD[tier] == capital


def test_t2_capital_is_the_existing_hang_literal() -> None:
    assert g.TIER_CAPITAL_USD["T2"] == assistant_remote._HANG_ALLOCATION_CASH == 10_000.0


def test_activation_paths_are_insensitive_to_tier() -> None:
    for function in (strategy_library.enable_strategy, assistant_remote.hang_candidate):
        source = inspect.getsource(function)
        assert "tier" not in source
        assert "TIER_CAPITAL" not in source
        assert "gate_v2" not in source


def test_no_level_information_falls_back_to_the_unfunded_tier() -> None:
    """G3: the safe default is the unallocated tier, never the 10_000 tier."""
    assert g.DEFAULT_TIER == "T0"
    assert g.tier_for_grade(g.DEFAULT_TIER) == "T0"
    assert g.tier_for_grade("not-a-grade") == "T0"
    assert g.TIER_CAPITAL_USD[g.DEFAULT_TIER] == 0.0


# --- G2: secondary evidence cannot upgrade ---------------------------------


@pytest.mark.parametrize(
    "augmented_offset,expected_evidence",
    [(0.0015, "primary"), (None, None)],
)
def test_the_upgrade_producer_emits_only_primary_or_none(
    augmented_offset: float | None, expected_evidence: str | None
) -> None:
    """The only producer's evidence vocabulary is exactly {None, 'primary'}."""
    from tests.gate_v2_fixtures import noise_returns

    baseline = noise_returns(200, seed=7, vol=0.01)
    if augmented_offset is None:
        augmented = noise_returns(200, seed=11, vol=0.01)
    else:
        augmented = [value + augmented_offset for value in baseline]
    verdict = g.paired_increment_verdict(baseline=baseline, augmented=augmented, seed=1234)
    assert verdict["accepted_evidence"] == expected_evidence
    assert verdict["accepted_evidence"] in (None, "primary")
    assert verdict["upgrade_accepted"] is (expected_evidence == "primary")


def test_secondary_only_evidence_lands_at_d0_not_d1() -> None:
    """A favourable secondary statistic that misses the primary interval is D0.

    Both the producible shape (accepted ``False``) and the unproducible
    ``accepted=True`` + ``secondary_only`` shape fail closed.
    """
    producible = _grade(
        _dsr(passed=True),
        _health(passed=True),
        _concentration(),
        {
            "applicable": True,
            "upgrade_accepted": False,
            "accepted_evidence": "secondary_only",
            "secondary": 0.97,
        },
        _family(),
    )
    unproducible = _grade(
        _dsr(passed=True),
        _health(passed=True),
        _concentration(),
        {
            "applicable": True,
            "upgrade_accepted": True,
            "accepted_evidence": "secondary_only",
            "secondary": 0.97,
        },
        _family(),
    )
    assert producible == g.GRADE_INSUFFICIENT
    assert unproducible == g.GRADE_INSUFFICIENT


def test_the_grade_has_no_secondary_evidence_marginal_reason() -> None:
    """The dead ``upgrade_secondary_only`` branch is gone, not merely unreachable."""
    source = inspect.getsource(g.grade_v2)
    assert "secondary_only" not in source
    assert "upgrade_secondary_only" not in source
