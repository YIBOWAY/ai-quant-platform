"""Necessary-condition proof, not 500 replacement-account experiments."""

from quant_system.research.admission_consumer_checks import replacement_dsr_necessary_condition
from quant_system.research.gate_v2.verdict import evaluate_gate_v2
from tests.gate_v2_fixtures import family_from_payloads, platform_result, resolver_for


def test_failed_dsr_always_t0_even_when_pair_and_concentration_are_favorable():
    result = replacement_dsr_necessary_condition()
    assert result["status"] == "passed" and result["branches"] == 16


def test_replacement_does_not_change_candidate_dsr_inputs_or_result():
    payload = platform_result(
        equity_returns=[0.001, -0.003] * 130, benchmark_returns=[0.0002] * 260
    )
    family_payloads = [
        platform_result(equity_returns=[0.001 * (i % 3 - 1)] * 260, benchmark_returns=[0.0] * 260)
        for i in range(12)
    ]
    rows = family_from_payloads(family_payloads)
    ordinary = evaluate_gate_v2(
        curve_rows=payload["curve"],
        initial_cash=100000,
        universe_digest=rows[0].universe_digest,
        trials_rows=rows,
        curve_resolver=resolver_for(family_payloads),
    )
    dates = ordinary["inputs"]["dates"]
    returns = ordinary["inputs"]["equity_returns"]
    baseline = [value - 0.0001 for value in returns]
    # Pure math fixture; never registered as a real sleeve or a funding qualification.
    paired = evaluate_gate_v2(
        curve_rows=payload["curve"],
        initial_cash=100000,
        universe_digest=rows[0].universe_digest,
        trials_rows=rows,
        curve_resolver=resolver_for(family_payloads),
        hung_sleeves=[
            {
                "sleeve_id": "math-reference-only",
                "definition_digest": "a" * 64,
                "dates": dates,
                "returns": baseline,
            }
        ],
        upgrade_target={"sleeve_id": "math-reference-only", "definition_digest": "a" * 64},
        increment_objective={"baseline": baseline, "augmented": returns},
    )
    assert paired["dsr"] == ordinary["dsr"]
    for key in ("active_returns", "equity_returns", "returns_digest", "dates_digest"):
        assert paired["inputs"][key] == ordinary["inputs"][key]
    assert paired["tier_recommendation"]["tier"] == "T0"
