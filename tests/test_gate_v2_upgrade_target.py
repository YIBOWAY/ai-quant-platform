"""An explicit frozen replacement target is not a second concurrent sleeve."""

from __future__ import annotations

import numpy as np
import pytest

from quant_system.research.gate_v2 import evaluate_gate_v2
from quant_system.research.gate_v2.verdict import verify_verdict_integrity_v2
from tests.gate_v2_fixtures import curve_rows, digest_of_universe


def test_explicit_matching_upgrade_excludes_only_the_replaced_sleeve():
    rng = np.random.default_rng(512)
    baseline = rng.normal(0, 0.01, 180).tolist()
    augmented = [v + 0.001 for v in baseline]
    curve = curve_rows(equity_returns=augmented, benchmark_returns=[0.0] * 180)
    result = evaluate_gate_v2(
        curve_rows=curve,
        initial_cash=100_000.0,
        universe_digest=digest_of_universe(),
        increment_objective={"baseline": baseline, "augmented": augmented},
        hung_sleeves=[
            {
                "sleeve_id": "old",
                "definition_digest": "a" * 64,
                "returns": baseline,
                "dates": [r["date"] for r in curve],
            }
        ],
        upgrade_target={"sleeve_id": "old", "definition_digest": "a" * 64},
    )
    assert result["concentration"]["applicable"] is False
    assert result["inputs"]["upgrade_target"]["sleeve_id"] == "old"
    assert verify_verdict_integrity_v2(result)


@pytest.mark.parametrize(
    "mutation",
    ["wrong_digest", "wrong_window", "wrong_baseline", "wrong_augmented", "missing_target"],
)
def test_upgrade_target_cannot_exclude_unbound_or_incomparable_sleeves(mutation):
    rng = np.random.default_rng(52)
    baseline = rng.normal(0, 0.01, 180).tolist()
    augmented = [v + 0.001 for v in baseline]
    curve = curve_rows(equity_returns=augmented, benchmark_returns=[0.0] * 180)
    old = {
        "sleeve_id": "old",
        "definition_digest": "a" * 64,
        "returns": baseline,
        "dates": [r["date"] for r in curve],
    }
    target = {"sleeve_id": "old", "definition_digest": "a" * 64}
    increment = {"baseline": baseline[:], "augmented": augmented[:]}
    if mutation == "wrong_digest":
        target["definition_digest"] = "b" * 64
    elif mutation == "wrong_window":
        old["dates"] = list(reversed(old["dates"]))
    elif mutation == "wrong_baseline":
        increment["baseline"][0] += 0.01
    elif mutation == "wrong_augmented":
        increment["augmented"][0] += 0.01
    else:
        target["sleeve_id"] = "absent"
    with pytest.raises(ValueError, match="gate_v2_upgrade_"):
        evaluate_gate_v2(
            curve_rows=curve,
            initial_cash=100_000.0,
            universe_digest=digest_of_universe(),
            hung_sleeves=[old],
            increment_objective=increment,
            upgrade_target=target,
        )


def test_upgrade_does_not_exempt_other_concurrent_sleeves():
    rng = np.random.default_rng(52)
    baseline = rng.normal(0, 0.01, 180).tolist()
    augmented = [v + 0.001 for v in baseline]
    curve = curve_rows(equity_returns=augmented, benchmark_returns=[0.0] * 180)
    dates = [r["date"] for r in curve]
    old = {"sleeve_id": "old", "definition_digest": "a" * 64, "returns": baseline, "dates": dates}
    other = {**old, "sleeve_id": "other", "definition_digest": "b" * 64}
    result = evaluate_gate_v2(
        curve_rows=curve,
        initial_cash=100_000.0,
        universe_digest=digest_of_universe(),
        hung_sleeves=[old, other],
        increment_objective={"baseline": baseline, "augmented": augmented},
        upgrade_target={"sleeve_id": "old", "definition_digest": "a" * 64},
    )
    assert result["concentration"]["passed"] is False
    assert result["concentration"]["raw_by_sleeve"][0]["sleeve_id"] == "other"
    assert verify_verdict_integrity_v2(result)
