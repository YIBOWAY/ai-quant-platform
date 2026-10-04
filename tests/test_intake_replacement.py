"""Explicit target parsing preserves legacy proposal identities and old recipes."""

import copy
import sys
import types

import pytest

from quant_system.research import external_intake as intake
from tests import test_external_intake as fixtures
from tests.test_definition_paper_bridge import definition


@pytest.fixture
def settings(tmp_path, monkeypatch):
    return fixtures.settings.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def target(monkeypatch):
    old = definition()
    value = {
        "replacement_target": {
            "candidate_id": "old-frozen-candidate",
            "sleeve_id": "sleeve-old",
            "definition_digest": old.content_digest,
            "config_id": "config-old",
            "config_version": 7,
        },
        "definition": old.model_dump(mode="json"),
        "source_sha256": "a" * 64,
        "source_path": "sealed",
    }
    module = types.ModuleType("quant_system.execution.strategy_replacement")
    module.inspect_replacement_target = lambda *a, **k: copy.deepcopy(value)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return value


def replacement_proposal(**updates):
    return fixtures.proposal(
        upgrade_target={"candidate_id": "old-frozen-candidate"},
        increment_objective={
            "metric": "sharpe",
            "minimum_improvement": 0.01,
            "max_regressions": {},
        },
        **updates,
    )


def test_missing_target_field_preserves_legacy_canonical_proposal(settings):
    fixtures.policy(settings)
    payload = fixtures.proposal()
    expected = intake.Proposal.model_validate(payload).model_dump(mode="json")
    for key in ("strategy_spec", "increment_objective", "upgrade_target", "hypothesis_card"):
        expected.pop(key)
    saved = intake.submit(settings, payload)
    job = intake._load_job(settings, saved["job_id"])
    assert job["proposal"] == expected and job["payload_sha256"] == intake._sha(expected)
    assert "upgrade_target" not in job["proposal"]


def test_explicit_target_freezes_actual_five_fields_and_exact_baseline(settings, target):
    fixtures.policy(settings)
    saved = intake.submit(settings, replacement_proposal())
    job = intake._load_job(settings, saved["job_id"])
    assert job["admission_protocol"]["intent"] == {
        "kind": "replacement",
        "target": target["replacement_target"],
    }
    baseline, augmented = job["plans"]
    old = target["definition"]
    assert baseline["definition_digest"] == old["content_digest"]
    assert {**baseline["payload"], "history_start": baseline["history_start"]} == old
    assert baseline["activation_eligible"] is False
    assert augmented["activation_eligible"] is True
    assert augmented["payload"]["factors"][:-1] == old["factors"]


@pytest.mark.parametrize("change", ["target_version", "execution", "baseline"])
def test_replacement_rejects_drift_before_any_job(settings, target, change):
    fixtures.policy(settings)
    payload = replacement_proposal()
    if change == "target_version":
        payload["upgrade_target"]["expected_config_version"] = 6
    elif change == "execution":
        payload["strategy_spec"] = {"rebalance": "monthly"}
    else:
        payload["baseline_factor_ids"] = ["momentum"]
    with pytest.raises(ValueError, match="intake_replacement_"):
        intake.submit(settings, payload)
    assert list((intake.root(settings) / "jobs").glob("*.json")) == []
