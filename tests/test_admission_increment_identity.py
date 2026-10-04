"""Artificial paired receipts: measured rejection is not an unknown input.

The existing sealed producer fixture substitutes only qualification authority;
the paired file bindings, real gate and funding refusal remain under test.
"""

import copy
import json

import pytest

from quant_system.research import admission_activation as activation
from quant_system.research import admission_qualifier as qualifier
from quant_system.research import admission_v2 as admission
from quant_system.research.external_intake import _sha
from quant_system.research.intake_evaluation import digest
from quant_system.research.strategy_definition import StrategyDefinition
from quant_system.research.validation_receipts import receipt_bindings
from tests import test_admission_v2 as core
from tests.gate_v2_fixtures import platform_result


@pytest.fixture(autouse=True)
def sealed_producer(monkeypatch):
    yield from core.sealed_producer.__wrapped__(monkeypatch)


@pytest.fixture
def rejected_pair(tmp_path):
    args = core.context.__wrapped__(tmp_path)
    candidate_path = args["validation_path"]
    candidate_definition = json.loads(
        (candidate_path.parent.parent.parent / "definition.json").read_text()
    )
    baseline_definition = StrategyDefinition(
        **{
            **candidate_definition,
            "title": "sealed baseline",
            "factors": [{"factor_id": "momentum", "lookback": 30, "direction": "higher_is_better"}],
            "content_digest": "",
        }
    )
    baseline_path = (
        tmp_path
        / "strategy_library"
        / ("strategy-" + baseline_definition.content_digest[:24])
        / "validations/validation-baseline/validation.json"
    )
    core.write(
        baseline_path.parent.parent.parent / "definition.json",
        baseline_definition.model_dump(mode="json"),
    )
    baseline_path.parent.mkdir(parents=True)
    (baseline_path.parent / "prices.parquet").write_bytes(
        (candidate_path.parent / "prices.parquet").read_bytes()
    )
    proposal = {
        "baseline_factor_ids": ["momentum"],
        "increment_objective": {
            "metric": "sharpe",
            "minimum_improvement": 100.0,
            "max_regressions": {},
        },
    }
    protocol = admission.freeze_protocol(
        args["protocol"]["job_id"], _sha(proposal), mode="authoritative"
    )
    definitions = [
        ("baseline", baseline_definition.model_dump(mode="json")),
        ("augmented", candidate_definition),
    ]
    plans = [
        {
            "variant": variant,
            "definition_digest": definition["content_digest"],
            "strategy_id": "strategy-" + definition["content_digest"][:24],
            "payload": {k: v for k, v in definition.items() if k != "history_start"},
            "history_start": definition["history_start"],
            "activation_eligible": variant == "augmented",
            "origin": {"admission_protocol_digest": protocol["protocol_digest"]},
        }
        for variant, definition in definitions
    ]
    evaluation = {**args["evaluation"], "plans_sha256": _sha(plans)}
    evaluation.pop("evaluation_id")
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    results = []
    original_validation = json.loads(candidate_path.read_text())
    for (variant, definition), path in zip(
        definitions, (baseline_path, candidate_path), strict=True
    ):
        result = json.loads((candidate_path.parent / "platform-result.json").read_text())
        if variant == "baseline":
            result.update(
                platform_result(
                    equity_returns=[0.001 + (0.004 if i % 2 else -0.004) for i in range(260)],
                    benchmark_returns=[0.0001] * 260,
                    initial_cash=10000,
                )
            )
        result["definition_digest"] = definition["content_digest"]
        core.write(path.parent / "platform-result.json", result)
        for filename in ("qlib-replay.json", "signal-analysis.json"):
            evidence = json.loads((candidate_path.parent / filename).read_text())
            evidence["definition_digest"] = definition["content_digest"]
            evidence["source"][
                "platform_result_sha256" if filename == "qlib-replay.json" else "result_sha256"
            ] = admission.file_sha(path.parent / "platform-result.json")
            core.write(path.parent / filename, evidence)
        validation = {
            **copy.deepcopy(original_validation),
            "definition_digest": definition["content_digest"],
            "evaluation": evaluation,
            "start": result["curve"][0]["date"],
            "end": result["curve"][-1]["date"],
            "run_id": path.parent.name,
            "platform_metrics": {"sharpe": 1.0 if variant == "baseline" else 2.0},
            "receipts": receipt_bindings(path.parent),
        }
        core.write(path, validation)
        results.append(
            {
                "variant": variant,
                "definition_digest": definition["content_digest"],
                "status": "validation_failed",
                "phase": "done",
                "validation": validation,
                "validation_sha256": admission.file_sha(path),
                "admission_v2": {"path": str(path.parent / "admission-placeholder.json")},
            }
        )
    job = {
        "job_id": protocol["job_id"],
        "proposal": proposal,
        "payload_sha256": _sha(proposal),
        "plans": plans,
        "plans_sha256": _sha(plans),
        "evaluation": evaluation,
        "admission_protocol": protocol,
        "results": results,
        "status": "failed",
    }
    core.write(tmp_path / "research_intake/jobs" / (job["job_id"] + ".json"), job)
    args.update(
        protocol=protocol,
        evaluation=evaluation,
        expected_validation_sha=admission.file_sha(candidate_path),
    )
    return args, job


def test_measured_increment_rejection_has_verifiable_identity(rejected_pair):
    args, _ = rejected_pair
    facts = qualifier.inspect_data_binding(args["settings"], args["validation_path"])
    assert facts["binding"]["increment_binding"]["objective"]["status"] == "failed"
    assert facts["binding"]["increment_binding"]["objective"]["comparable"] is True


def test_rejected_increment_still_computes_gate_but_never_grants_capital(
    rejected_pair, monkeypatch
):
    args, _ = rejected_pair
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    _, receipt = core.qualify(args)
    assert receipt["gate"]["tier_recommendation"]["tier"] == "T2"
    assert receipt["validated_tier"] == "T0" and receipt["status"] == "recorded"
    assert receipt["capital_authorized"] is False
    assert "admission_v2_declared_increment_not_passed" in receipt["reasons"]
    descriptor = admission.write_receipt(args["validation_path"].parent, receipt)
    with pytest.raises(ValueError, match="unfunded_tier"):
        admission.verify_for_new_capital(
            args["settings"],
            descriptor,
            definition_digest=args["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=args["source_sha256"],
            book=args["book"],
        )


def test_failed_increment_does_not_make_parallel_scope_unknown(rejected_pair, monkeypatch):
    args, job = rejected_pair
    scope = {
        "context": admission.qualification_input_context(
            qualifier.inspect_data_binding(args["settings"], args["validation_path"])["binding"]
        )
    }
    monkeypatch.setattr(activation, "_scope", lambda: scope)
    assert activation._classify_job(args["settings"], job)["classification"] == "in_scope"


def test_failed_objective_does_not_relax_paired_input_identity(rejected_pair):
    args, job = rejected_pair
    path = (
        args["settings"].data.data_dir
        / "strategy_library"
        / job["plans"][0]["strategy_id"]
        / "validations/validation-baseline/prices.parquet"
    )
    path.write_bytes(b"changed artificial input")
    with pytest.raises(ValueError, match="inputs_or_code_changed"):
        qualifier.inspect_data_binding(args["settings"], args["validation_path"])


@pytest.mark.parametrize("purpose", ["new_capital", "replacement"])
def test_resigned_t2_label_cannot_override_failed_declared_objective(
    rejected_pair, monkeypatch, purpose
):
    args, _ = rejected_pair
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    _, receipt = core.qualify(args)
    receipt.update(status="passed", validated_tier="T2")
    receipt["receipt_digest"] = admission._hash(
        {k: v for k, v in receipt.items() if k != "receipt_digest"}
    )
    descriptor = admission.write_receipt(args["validation_path"].parent, receipt)
    with pytest.raises(ValueError, match="declared_increment_not_passed"):
        admission._verify_current_decision(
            args["settings"],
            descriptor,
            definition_digest=args["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=args["source_sha256"],
            book=args["book"],
            require_authority=True,
            purpose=purpose,
        )
