"""G1: the sensitivity sweep must respect structural DSR failure reasons.

A record whose DSR failed because the trial *family was too small* (not because
the value sat under the line) must stay failed at every scale. The regression
counterexample is reproduced verbatim: ``reason='family_too_small'`` with
``value=0.999`` and ``dsr_min_used=0.99`` — a naive rescale reads it as passing
at ``scale=0.9`` and flips ``D0_insufficient`` to ``D1_marginal``.
"""

from __future__ import annotations

import pytest

from quant_system.research import gate_v2 as g

_SCALES = (0.9, 1.1)

# A structural failure: the DSR value is *above* the fixed small-family line, so
# only the reason keeps the record failed.
_STRUCTURAL_VALUE = 0.999
_STRUCTURAL_MIN = 0.99


def _health() -> dict:
    return {
        "psr_total": {"value": 0.9, "min": 0.5, "passed": True, "reason": None},
        "max_drawdown": {"value": 0.05, "max": 0.30, "passed": True, "reason": None},
        "annual_volatility": {"value": 0.10, "max": 0.35, "passed": True, "reason": None},
        "passed": True,
        "reasons": [],
    }


def _record(*, reason: str | None, value: float, dsr_min: float, path: str) -> dict:
    return {
        "grade": {"grade": g.GRADE_INSUFFICIENT, "reasons": ["dsr_v2_failed"]},
        "dsr": {
            "passed": False,
            "value": value,
            "dsr_min_used": dsr_min,
            "reason": reason,
            "path": path,
            "n_periods": 200,
        },
        "health": _health(),
        "concentration": {
            "applicable": False,
            "raw_max": None,
            "raw_limit": 0.7,
            "raw_passed": True,
            "passed": True,
        },
        "upgrade": {"applicable": False, "upgrade_accepted": None, "accepted_evidence": None},
        "family": {"trusted": True},
        "config": dict(g.GATE_V2_CONFIG),
    }


def _structural_record(reason: str = "family_too_small") -> dict:
    return _record(
        reason=reason,
        value=_STRUCTURAL_VALUE,
        dsr_min=_STRUCTURAL_MIN,
        path="small_family_fixed",
    )


def _old_rule_grade(record: dict, scale: float) -> str:
    """The pre-fix recompute (ignores ``reason``), kept here as the counterexample."""
    dsr = dict(record["dsr"])
    dsr_min = dsr.get("dsr_min_used")
    dsr["passed"] = bool(
        dsr.get("value") is not None
        and dsr_min is not None
        and float(dsr["value"]) >= float(dsr_min) * float(scale)
    )
    health = _health()  # healthy at both scales
    return g.grade_v2(
        dsr=dsr,
        health=health,
        concentration=record["concentration"],
        upgrade=record["upgrade"],
        family=record["family"],
        config=record["config"],
    )["grade"]


def test_ignoring_reason_flips_a_structural_failure() -> None:
    """The exact defect: the old recompute lifts D0 to D1 at scale 0.9."""
    record = _structural_record()
    assert record["grade"]["grade"] == g.GRADE_INSUFFICIENT
    assert _old_rule_grade(record, 0.9) == g.GRADE_MARGINAL


def test_the_sweep_respects_the_structural_reason() -> None:
    """After the fix the same record never flips, and it reports the pinned reason."""
    report = g.evaluate_sensitivity_v2(_structural_record(), scales=_SCALES)
    assert [item["grade"] for item in report["results"]] == [
        g.GRADE_INSUFFICIENT,
        g.GRADE_INSUFFICIENT,
    ]
    assert [item["changed"] for item in report["results"]] == [False, False]
    assert [item["pinned_reason"] for item in report["results"]] == [
        "family_too_small",
        "family_too_small",
    ]
    assert report["flip_rate"] == 0.0
    assert report["load_bearing"] is False


@pytest.mark.parametrize(
    "reason",
    [
        "family_too_small",
        "family_member_short_window",
        "candidate_window_too_short",
        "dsr_input_invalid",
        "dsr_moments_invalid",
    ],
)
def test_every_structural_reason_is_pinned(reason: str) -> None:
    report = g.evaluate_sensitivity_v2(_structural_record(reason), scales=(0.5,))
    result = report["results"][0]
    assert result["grade"] == g.GRADE_INSUFFICIENT
    assert result["changed"] is False
    assert result["pinned_reason"] == reason


def test_a_numeric_failure_still_moves_with_the_threshold() -> None:
    """A value-under-the-line failure *is* sensitive; the pin is not a blanket freeze."""
    record = _record(reason=None, value=0.96, dsr_min=0.95, path="data_driven")
    report = g.evaluate_sensitivity_v2(record, scales=_SCALES)
    by_scale = {item["scale"]: item for item in report["results"]}
    assert by_scale[0.9]["grade"] == g.GRADE_SUPPORTED
    assert by_scale[0.9]["pinned_reason"] is None
    assert by_scale[1.1]["grade"] == g.GRADE_INSUFFICIENT
    assert report["flip_rate"] == 0.5
    assert report["load_bearing"] is True


def test_a_passing_record_still_moves_when_the_line_is_hardened() -> None:
    record = _record(reason=None, value=0.96, dsr_min=0.95, path="data_driven")
    record["dsr"]["passed"] = True
    record["grade"] = {"grade": g.GRADE_SUPPORTED, "reasons": ["dsr_health_family_supported"]}
    report = g.evaluate_sensitivity_v2(record, scales=_SCALES)
    by_scale = {item["scale"]: item for item in report["results"]}
    assert by_scale[1.1]["changed"] is True
    assert by_scale[1.1]["pinned_reason"] is None
