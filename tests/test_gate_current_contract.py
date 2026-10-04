"""Current-contract gate wiring over explicit artificial bound curve inputs."""
import copy

from quant_system.research.gate_v2.verdict import (
    envelope_digest,
    evaluate_gate_v2,
    verify_verdict_integrity_v2,
    verify_verdict_v2,
)
from quant_system.research.trials import universe_digest
from tests.test_gate_v2_family_contract import contract, example


def test_current_contract_roundtrips_and_requires_peer_calendar():
    pairs = [example(i) for i in range(12)]
    lookup = {row.trial_id: payload for row, payload in pairs}
    row, candidate = pairs[0]
    result = evaluate_gate_v2(
        curve_rows=candidate["curve"], initial_cash=candidate["evaluation_initial_cash"],
        universe_digest=universe_digest(["AAA", "BBB"]),
        benchmark_symbol="SPY", trials_rows=[row for row, _ in pairs],
        curve_resolver=lambda trial: lookup[trial.trial_id],
        compatibility_contract=contract(),
        hung_sleeves=[{"sleeve_id": "artificial-peer", "returns": [0.001] * 240,
                       "dates": None}],
    )
    assert result["family"]["rule_version"] == "compatible_evaluation_family/v2"
    assert result["concentration"]["raw_status"] == "not_evaluated"
    assert result["concentration"]["raw_passed"] is False
    assert verify_verdict_v2(result, trusted_trials=[row for row, _ in pairs],
                             curve_resolver=lambda trial: lookup[trial.trial_id])
    changed = copy.deepcopy(result)
    changed["concentration"]["raw_status"] = "not_applicable"
    changed["envelope_digest"] = envelope_digest(changed)
    assert not verify_verdict_integrity_v2(changed)
