"""A catalog entry or re-signed JSON must never manufacture local qualification."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.research import admission_qualifier as qualifier
from quant_system.research import admission_v2 as admission


def settings(tmp_path):
    return SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))


def test_arbitrary_all_passed_document_is_not_a_qualification(tmp_path):
    path = tmp_path / "self-reported.json"
    path.write_text(
        json.dumps(
            {
                "status": "passed",
                "checks": {name: True for name in admission._REQUIRED_QUALIFICATIONS["review"]},
            }
        )
    )
    result = qualifier.verify_registered_qualification(
        settings(tmp_path),
        kind="review",
        scope=admission.SCOPE,
        code_digest=admission.code_identity()["digest"],
        input_digest="a" * 64,
        descriptor={"path": str(path), "sha256": qualifier.file_sha(path)},
    )
    assert result["status"] == "not_evaluated"
    assert result["verified_checks"] == []
    assert not (tmp_path / "research_intake").exists()


def test_register_missing_review_keeps_unknown_and_recompute_rejects_resigned_pass(tmp_path):
    s = settings(tmp_path)
    issued = qualifier.register_qualification(
        s, kind="review", scope=admission.SCOPE, evidence={"root": str(tmp_path / "missing")}
    )
    assert issued["verification"]["status"] == "not_evaluated"
    descriptor = issued["descriptor"]
    from pathlib import Path

    from quant_system.research.evaluation_service import _hash

    document = json.loads(Path(descriptor["path"]).read_text())
    document["verification_result"] = {
        "checks": {name: {"status": "passed"} for name in qualifier.REQUIRED["review"]}
    }
    identity = _hash(document)
    path = Path(descriptor["path"]).with_name(identity + ".json")
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    observed = qualifier.verify_registered_qualification(
        s,
        kind="review",
        scope=admission.SCOPE,
        code_digest=admission.code_identity()["digest"],
        input_digest="a" * 64,
        descriptor={
            "path": str(path),
            "sha256": qualifier.file_sha(path),
            "registration_id": identity,
        },
    )
    assert observed["status"] == "not_evaluated"
    assert observed["reason"] == "qualification_recomputation_mismatch"


def test_review_recipe_cannot_select_an_uploaded_script_or_checks(tmp_path):
    issued = qualifier.register_qualification(
        settings(tmp_path),
        kind="review",
        scope=admission.SCOPE,
        evidence={
            "root": str(tmp_path),
            "script": "fake.py",
            "checks": {"independent_holdout": True},
        },
    )
    assert issued["verification"]["status"] == "not_evaluated"
    assert issued["verification"]["reason"] == "qualification_recipe_invalid"


@pytest.mark.parametrize(
    "field,value", [("kind", "data"), ("scope", "arbitrary_python"), ("code_digest", "0" * 64)]
)
def test_scope_kind_and_current_code_are_rechecked(tmp_path, field, value):
    s = settings(tmp_path)
    issued = qualifier.register_qualification(
        s, kind="review", scope=admission.SCOPE, evidence={"root": str(tmp_path)}
    )
    args = {
        "kind": "review",
        "scope": admission.SCOPE,
        "code_digest": admission.code_identity()["digest"],
        "input_digest": "a" * 64,
        "descriptor": issued["descriptor"],
    }
    args[field] = value
    assert qualifier.verify_registered_qualification(s, **args)["status"] == "not_evaluated"


def test_data_registration_binds_requested_input_and_rejects_outside_owner_root(tmp_path):
    s = settings(tmp_path)
    evidence = {
        "validation_path": "/arbitrary/validation.json",
        "dataset": "futu-study-20260909-24",
        "source_root": str(tmp_path),
    }
    issued = qualifier.register_qualification(
        s, kind="data", scope=admission.SCOPE, input_digest="a" * 64, evidence=evidence
    )
    assert issued["verification"]["status"] == "not_evaluated"
    assert issued["verification"]["reason"] == "qualification_validation_outside_owner_root"
    observed = qualifier.verify_registered_qualification(
        s,
        kind="data",
        scope=admission.SCOPE,
        code_digest=admission.code_identity()["digest"],
        input_digest="b" * 64,
        descriptor=issued["descriptor"],
    )
    assert observed["reason"] == "qualification_scope_or_identity_mismatch"


def test_corrupt_or_symlink_registration_cannot_be_promoted(tmp_path):
    s = settings(tmp_path)
    issued = qualifier.register_qualification(
        s, kind="review", scope=admission.SCOPE, evidence={"root": str(tmp_path)}
    )
    path = Path(issued["descriptor"]["path"])
    original = path.read_text()
    path.write_text("{}")
    args = {
        "kind": "review",
        "scope": admission.SCOPE,
        "code_digest": admission.code_identity()["digest"],
        "input_digest": "a" * 64,
        "descriptor": issued["descriptor"],
    }
    assert (
        qualifier.verify_registered_qualification(s, **args)["reason"]
        == "qualification_registration_changed"
    )
    path.unlink()
    redirected = tmp_path / "redirected.json"
    redirected.write_text(original)
    path.symlink_to(redirected)
    assert (
        qualifier.verify_registered_qualification(s, **args)["reason"]
        == "qualification_registration_outside_registry"
    )


def test_old_engine_records_without_new_owner_protocol_are_not_qualified(tmp_path):
    from tests.test_admission_v2 import context

    args = context.__wrapped__(tmp_path)
    facts = qualifier.inspect_data_binding(args["settings"], args["validation_path"])
    observed = admission.evaluate_validation(**args)
    assert facts["binding"] == observed["source_binding"]
    assert facts["input_digest"] == qualifier._hash(observed["source_binding"])
    job_path = tmp_path / "research_intake/jobs" / (args["protocol"]["job_id"] + ".json")
    job = json.loads(job_path.read_text())
    job.pop("admission_protocol")
    job_path.write_text(json.dumps(job))
    issued = qualifier.register_qualification(
        args["settings"],
        kind="data",
        scope=admission.SCOPE,
        input_digest=facts["input_digest"],
        evidence={
            "validation_path": str(args["validation_path"]),
            "dataset": "futu-study-20260909-24",
            "source_root": str(tmp_path),
        },
    )
    assert issued["verification"]["status"] == "not_evaluated"
    assert issued["verification"]["reason"] == "admission_v2_protocol_required"


@pytest.mark.parametrize("history_start", ["2015-01-01", "2016-01-01"])
def test_explicit_plan_history_start_is_preserved_without_mutating_plan(
    tmp_path, monkeypatch, history_start
):
    import copy

    from tests.test_admission_v2 import context

    args = context.__wrapped__(tmp_path)
    original_context = admission._job_context
    seen = []

    def frozen_context(*positional, **keywords):
        job, plan, job_digest = original_context(*positional, **keywords)
        plan = copy.deepcopy(plan)
        plan["payload"]["history_start"] = history_start
        seen.append(plan)
        return job, plan, job_digest

    monkeypatch.setattr(admission, "_job_context", frozen_context)
    if history_start == "2015-01-01":
        facts = qualifier.inspect_data_binding(args["settings"], args["validation_path"])
        assert facts["definition"]["history_start"] == history_start
    else:
        with pytest.raises(ValueError, match="strategy_content_digest_mismatch"):
            qualifier.inspect_data_binding(args["settings"], args["validation_path"])
    assert seen[0]["payload"]["history_start"] == history_start


def test_top_level_replacement_history_start_is_not_silently_defaulted(tmp_path, monkeypatch):
    import copy

    from tests.test_admission_v2 import context

    args = context.__wrapped__(tmp_path)
    original_context = admission._job_context

    def frozen_context(*positional, **keywords):
        job, plan, job_digest = original_context(*positional, **keywords)
        plan = copy.deepcopy(plan)
        plan["history_start"] = "2016-01-01"
        return job, plan, job_digest

    monkeypatch.setattr(admission, "_job_context", frozen_context)
    with pytest.raises(ValueError, match="strategy_content_digest_mismatch"):
        qualifier.inspect_data_binding(args["settings"], args["validation_path"])


@pytest.mark.parametrize(
    "field,value,allowed",
    [("title", "renamed proposal", True), ("top_n", 3, False), ("slippage_bps", 6, False)],
)
def test_qualification_reused_definition_ignores_only_display_title(
    tmp_path, monkeypatch, field, value, allowed
):
    import copy

    from tests.test_admission_v2 import context

    args = context.__wrapped__(tmp_path)
    original = admission._job_context

    def planned(*a, **k):
        job, plan, identity = original(*a, **k)
        plan = copy.deepcopy(plan)
        plan["payload"][field] = value
        return job, plan, identity

    monkeypatch.setattr(admission, "_job_context", planned)
    if allowed:
        facts = qualifier.inspect_data_binding(args["settings"], args["validation_path"])
        assert facts["definition"]["title"] != value
        assert facts["binding"]["source_sha256"] == args["source_sha256"]
    else:
        with pytest.raises(ValueError):
            qualifier.inspect_data_binding(args["settings"], args["validation_path"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("rebalance", "daily"),
        ("top_n", 2),
        ("execution_price", "close"),
        ("end", "2026-09-18"),
        ("whole_share_orders", True),
        ("target_gross_exposure", 0.5),
    ],
)
def test_24_stock_control_context_cannot_be_extended_to_another_recipe(field, value):
    context = dict(qualifier.CONTROL_CONTEXT)
    qualifier.require_supported_data_context("futu-study-20260909-24", context)
    context[field] = value
    with pytest.raises(ValueError, match="qualification_calibration_context_mismatch"):
        qualifier.require_supported_data_context("futu-study-20260909-24", context)


def test_current_dataset_has_its_own_actual_window_without_changing_old_context():
    current = {**qualifier.CONTROL_CONTEXT, "end": "2026-09-18"}
    qualifier.require_supported_data_context("futu24-current-20260920", current)
    with pytest.raises(ValueError, match="qualification_calibration_context_mismatch"):
        qualifier.require_supported_data_context(
            "futu24-current-20260920", qualifier.CONTROL_CONTEXT
        )
    qualifier.require_supported_data_context("futu-study-20260909-24", qualifier.CONTROL_CONTEXT)


@pytest.mark.parametrize(
    "error,retryable",
    [
        (FileNotFoundError("missing immutable input"), False),
        (OSError("temporary storage issue"), True),
        (TimeoutError("fixed tool timeout"), True),
        (ValueError("scope mismatch"), False),
    ],
)
def test_producer_failure_type_drives_retryability_not_caller_claims(
    tmp_path, monkeypatch, error, retryable
):
    calls = []

    def fixed_check(_evidence):
        calls.append(True)
        raise error

    monkeypatch.setattr(qualifier, "_review_checks", fixed_check)
    result = qualifier.register_qualification(
        settings(tmp_path), kind="review", scope=admission.SCOPE, evidence={"root": str(tmp_path)}
    )
    assert result["verification"]["status"] == "not_evaluated"
    assert result["verification"]["details"]["error_type"] == type(error).__name__
    assert result["verification"]["details"]["retryable"] is retryable
    assert len(calls) == 1
