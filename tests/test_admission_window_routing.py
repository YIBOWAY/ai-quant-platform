"""Sealed routing tests: real submission/plans, no market or funding execution."""

from types import SimpleNamespace

import pytest

from quant_system.research import admission_activation as activation
from quant_system.research import admission_v2 as admission
from quant_system.research import external_intake as intake
from tests.test_external_intake import policy, proposal


@pytest.fixture
def owner(tmp_path):
    return SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))


def test_unmatched_installed_stage_keeps_new_research_parallel(owner, monkeypatch):
    policy(owner, admission_mode="authoritative", auto_enable=False)
    seen = []

    def choose_binding(settings, *, plans=None):
        assert settings is owner
        if plans is None:
            return {
                "schema": activation.SCHEMA,
                "state_digest": "a" * 64,
                "stage_sha256": "b" * 64,
                "code_digest": admission.code_identity()["digest"],
                "supported_scope": activation._scope(),
            }
        assert plans and all(p["origin"]["end"] for p in plans)
        seen.append(plans)
        return None  # a valid installed stage, but outside its frozen window

    monkeypatch.setattr(activation, "protocol_binding", choose_binding)
    result = intake.submit(owner, proposal())
    job = intake._load_job(owner, result["job_id"])
    assert len(seen) == 1
    assert job["status"] == "queued"
    assert job["admission_protocol"]["mode"] == "parallel"
    assert "activation" not in job["admission_protocol"]
    assert job["policy_snapshot"]["admission_mode"] == "authoritative"
    assert intake.read_policy(owner).admission_mode == "authoritative"
    assert not (owner.data.data_dir / "api_runs").exists()


def test_matched_stage_selects_new_protocol_without_enabling_capital(owner, monkeypatch):
    policy(owner, auto_enable=False)
    binding = {
        "schema": activation.SCHEMA,
        "state_digest": "a" * 64,
        "stage_sha256": "b" * 64,
        "code_digest": admission.code_identity()["digest"],
        "supported_scope": activation._scope(),
    }
    received = []

    def choose_binding(settings, *, plans=None):
        assert plans and all("definition_digest" in p for p in plans)
        received.append(plans)
        return binding

    monkeypatch.setattr(activation, "protocol_binding", choose_binding)
    result = intake.submit(owner, proposal())
    job = intake._load_job(owner, result["job_id"])
    assert len(received) == 1
    assert job["admission_protocol"]["mode"] == "authoritative"
    assert job["admission_protocol"]["activation"] == binding
    assert admission.AUTHORITATIVE_ENABLED is False
    assert not (owner.data.data_dir / "api_runs").exists()


def test_invalid_installed_stage_does_not_silently_remove_its_binding(owner, monkeypatch):
    policy(owner, auto_enable=False)

    def invalid(*args, **kwargs):
        raise ValueError("activation_source_scope_or_recipe_changed")

    monkeypatch.setattr(activation, "protocol_binding", invalid)
    with pytest.raises(ValueError, match="activation_source_scope_or_recipe_changed"):
        intake.submit(owner, proposal())
    assert not list((intake.root(owner) / "jobs").glob("*.json"))
