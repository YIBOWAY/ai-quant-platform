from __future__ import annotations

import copy
import json
import sys
import types
from types import SimpleNamespace

import pytest

from quant_system.research import admission_v2 as admission
from quant_system.research.evaluation_service import _hash
from quant_system.research.validation_receipts import receipt_bindings
from tests.gate_v2_fixtures import DEFAULT_UNIVERSE, family_from_payloads, platform_result


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture(autouse=True)
def sealed_producer(monkeypatch):
    """Explicitly mock the trusted local program, never claim test JSON is evidence."""
    from quant_system.research import admission_activation
    from quant_system.research.admission_qualifier import inspect_data_binding

    # Authority itself needs the source switch and an installed activation state
    # together; only the state is sealed here, never the switch.
    monkeypatch.setattr(admission_activation, "configured", lambda _settings: True)
    module = types.ModuleType("quant_system.research.admission_qualifier")
    module.inspect_data_binding = inspect_data_binding
    module.registrations = {}
    module.contexts = {}

    def verify(settings, *, kind, scope, code_digest, input_digest, descriptor):
        expected = {"scope": scope, "code_digest": code_digest, "input_digest": input_digest}
        registered = module.registrations.get((kind, descriptor.get("sha256")))
        if registered != expected or admission.file_sha(descriptor["path"]) != descriptor["sha256"]:
            return {"status": "not_evaluated", "reason": "qualification_scope_or_identity_mismatch"}
        return {
            "status": "passed",
            "reason": None,
            "verified_checks": sorted(admission._REQUIRED_QUALIFICATIONS[kind]),
            "registration_digest": _hash({"sealed_test_only": kind, **expected}),
            "issuer_id": "sealed-test-local-producer",
            "details": {
                "supported_context": module.contexts[kind, descriptor["sha256"]],
                "supported_operations": ["new_independent", "replacement"],
            },
        }

    module.verify_registered_qualification = verify
    monkeypatch.setitem(sys.modules, module.__name__, module)
    yield module


@pytest.fixture
def context(tmp_path):
    from quant_system.research.strategy_definition import StrategyDefinition

    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    definition = StrategyDefinition(
        kind="factor_blend",
        title="sealed",
        symbols=list(DEFAULT_UNIVERSE),
        history_start="2015-01-01",
        top_n=2,
        factors=[{"factor_id": "momentum", "lookback": 20, "direction": "higher_is_better"}],
    )
    definition_digest = definition.content_digest
    directory = (
        tmp_path
        / "strategy_library"
        / ("strategy-" + definition_digest[:24])
        / "validations"
        / "validation-new"
    )
    directory.mkdir(parents=True)
    write(directory.parent.parent / "definition.json", definition.model_dump(mode="json"))
    (directory / "prices.parquet").write_bytes(
        b"sealed synthetic prices, never a real provider claim"
    )
    candidate = platform_result(
        equity_returns=[0.003 + (0.004 if i % 2 else -0.004) for i in range(260)],
        benchmark_returns=[0.0001] * 260,
        initial_cash=10000,
    )
    candidate.update(
        frequency="daily", definition=definition.model_dump(mode="json"),
        source="futu",
        price_adjustment="qfq",
        definition_digest=definition_digest,
        profile={"id": "fixture", "symbols": list(DEFAULT_UNIVERSE), "benchmark_symbol": "SPY"},
        costs={"commission_bps": 1, "slippage_bps": 5},
    )
    write(directory / "platform-result.json", candidate)
    prices_sha = admission.file_sha(directory / "prices.parquet")
    sources = receipt_bindings.__globals__["_SOURCES"]
    from pathlib import Path

    import quant_system.research.validation_receipts as receipt_module

    source_hashes = {
        name: admission.file_sha(Path(receipt_module.__file__).parent / name) for name in sources
    }
    write(
        directory / "qlib-replay.json",
        {
            "definition_digest": definition_digest,
            "status": "available",
            "source": {
                "prices_sha256": prices_sha,
                "platform_result_sha256": admission.file_sha(directory / "platform-result.json"),
                "replay_source_sha256": source_hashes["definition_qlib_replay.py"],
            },
        },
    )
    write(
        directory / "signal-analysis.json",
        {
            "definition_digest": definition_digest,
            "status": "available",
            "source": {
                "prices_sha256": prices_sha,
                "result_sha256": admission.file_sha(directory / "platform-result.json"),
                "validation_source_sha256": source_hashes["strategy_signal_validation.py"],
                "fit_metrics_source_sha256": source_hashes["qlib_evaluation.py"],
            },
        },
    )
    from quant_system.research.external_intake import _sha
    from quant_system.research.intake_evaluation import digest as evaluation_digest

    job_id = "intake-" + "a" * 24
    proposal = {"baseline_factor_ids": []}
    protocol = admission.freeze_protocol(job_id, _sha(proposal))
    plans = [
        {
            "variant": "formula",
            "definition_digest": definition_digest,
            "strategy_id": "strategy-" + definition_digest[:24],
            "payload": definition.model_dump(mode="json", exclude={"history_start"}),
            "activation_eligible": True,
            "origin": {"admission_protocol_digest": protocol["protocol_digest"]},
        }
    ]
    frozen_prices = tmp_path / "research_intake/evaluations" / job_id / "prices.parquet"
    frozen_prices.parent.mkdir(parents=True)
    frozen_prices.write_bytes((directory / "prices.parquet").read_bytes())
    evaluation = {
        "prices_sha256": prices_sha,
        "prices_path": str(frozen_prices),
        "plans_sha256": _sha(plans),
        "job_id": job_id,
    }
    evaluation["evaluation_id"] = "evaluation-" + evaluation_digest(evaluation)
    write(
        tmp_path / "research_intake/jobs" / (job_id + ".json"),
        {
            "job_id": job_id,
            "proposal": proposal,
            "payload_sha256": _sha(proposal),
            "plans": plans,
            "plans_sha256": _sha(plans),
            "evaluation": evaluation,
            "admission_protocol": protocol,
        },
    )
    from quant_system.execution.assistant_remote import _certify_cost_sensitivity
    from quant_system.research.gate_v2.active_returns import recompute_active_returns
    from quant_system.research.trials import performance_from_daily_returns

    returns = recompute_active_returns(candidate["curve"], initial_cash=10000)["equity_returns"]
    cost = _certify_cost_sensitivity(
        {"performance": {**performance_from_daily_returns(returns), "turnover_period": 1.0}},
        cost_bps=6,
    )
    validation = {
        "status": "passed",
        "definition_digest": definition_digest,
        "comparison": {"accepted": True},
        "signal_analysis": {"status": "available"},
        "gates": {"cost": cost},
        "receipts": receipt_bindings(directory),
        "evaluation": evaluation,
        "evaluation_calendar_digest": _hash([r["date"] for r in candidate["curve"]]),
    }
    write(directory / "validation.json", validation)
    payloads = [
        platform_result(
            equity_returns=[0.002 * ((i + offset) % 5 - 2) for i in range(260)],
            benchmark_returns=[0.0] * 260,
        )
        for offset in range(12)
    ]
    for i, payload in enumerate(payloads):
        family_definition = StrategyDefinition(
            kind="factor_blend", title=f"Artificial family member {i}",
            symbols=list(DEFAULT_UNIVERSE), history_start="2015-01-01", top_n=2,
            factors=[{"factor_id": "momentum", "lookback": 30 + i,
                      "direction": "higher_is_better"}],
        )
        payload.update(
            frequency="daily", definition=family_definition.model_dump(mode="json"),
            definition_digest=family_definition.content_digest, source="futu",
            price_adjustment="qfq", profile={"benchmark_symbol": "SPY"},
        )
        write(
            tmp_path
            / "strategy_library"
            / f"family-{i}"
            / "validations"
            / "test"
            / "platform-result.json",
            payload,
        )
        write(tmp_path / "strategy_library" / f"family-{i}" / "validations" / "test"
              / "validation.json", {"definition_digest": family_definition.content_digest})
    rows = family_from_payloads(payloads)
    rows = [row.model_copy(update={
        "window_start": payload["curve"][0]["date"],
        "window_end": payload["curve"][-1]["date"],
        "metadata": {**row.metadata, "strategy_definition_digest": payload["definition_digest"]},
    }) for row, payload in zip(rows, payloads, strict=True)]
    ledger = tmp_path / "trials" / "trials.jsonl"
    ledger.parent.mkdir()
    ledger.write_text("".join(json.dumps(row.model_dump(mode="json")) + "\n" for row in rows))
    args = dict(
        settings=settings,
        protocol=protocol,
        validation_path=directory / "validation.json",
        expected_validation_sha=admission.file_sha(directory / "validation.json"),
        definition_digest=definition_digest,
        source_sha256=admission.file_sha(directory.parent.parent / "definition.json"),
        evaluation=evaluation,
        book={"candidates": []},
    )
    return args


def authoritative(context):
    from quant_system.research.external_intake import _sha
    from quant_system.research.intake_evaluation import digest

    protocol = admission.freeze_protocol(
        context["protocol"]["job_id"],
        context["protocol"]["proposal_digest"],
        mode="authoritative",
    )
    path = (
        context["settings"].data.data_dir / "research_intake/jobs" / (protocol["job_id"] + ".json")
    )
    job = json.loads(path.read_text())
    job["admission_protocol"] = context["protocol"] = protocol
    for plan in job["plans"]:
        plan["origin"]["admission_protocol_digest"] = protocol["protocol_digest"]
    job["plans_sha256"] = _sha(job["plans"])
    evaluation = context["evaluation"]
    evaluation["plans_sha256"] = job["plans_sha256"]
    evaluation.pop("evaluation_id")
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    job["evaluation"] = evaluation
    write(path, job)
    validation = json.loads(context["validation_path"].read_text())
    validation["evaluation"] = evaluation
    write(context["validation_path"], validation)
    context["expected_validation_sha"] = admission.file_sha(context["validation_path"])


def qualify(args, expected_tier="T2"):
    probe = admission.evaluate_validation(**args)
    assert probe["gate"]["tier_recommendation"]["tier"] == expected_tier, probe
    refs = {}
    root = args["settings"].data.data_dir / "qualification-fixture"
    for kind, checks in admission._REQUIRED_QUALIFICATIONS.items():
        evidence = root / f"{kind}-evidence.json"
        write(evidence, {"scope": "sealed_test_evidence", "kind": kind})
        path = root / f"{kind}.json"
        write(
            path,
            {
                "schema": admission.QUALIFICATION_SCHEMA,
                "kind": kind,
                "status": "passed",
                "scope": admission.SCOPE,
                "code_digest": args["protocol"]["code"]["digest"],
                "input_digest": _hash(probe["source_binding"]),
                "checks": {name: {"status": "passed"} for name in checks},
                "evidence": [{"path": str(evidence), "sha256": admission.file_sha(evidence)}],
            },
        )
        refs[kind] = {"path": str(path), "sha256": admission.file_sha(path)}
    index = args["settings"].data.data_dir / "research_intake/admission_v2/qualifications.json"
    write(
        index,
        {
            "schema": "admission_qualification_index/v1",
            "entries": {_hash(probe["source_binding"]): refs},
        },
    )
    index.chmod(0o600)
    # Only the explicit test producer can create these registrations. Production
    # has no equivalent arbitrary-JSON registration function.
    module = sys.modules["quant_system.research.admission_qualifier"]
    for kind, descriptor in refs.items():
        module.registrations[kind, descriptor["sha256"]] = {
            "scope": admission.SCOPE,
            "code_digest": args["protocol"]["code"]["digest"],
            "input_digest": _hash(probe["source_binding"]),
        }
        module.contexts[kind, descriptor["sha256"]] = admission.qualification_input_context(
            probe["source_binding"]
        )
    return args, admission.evaluate_validation(**args)


def test_numeric_t2_without_scoped_qualifications_remains_unfunded(context):
    record = admission.evaluate_validation(**context)
    assert record["gate"]["tier_recommendation"]["tier"] == "T2"
    assert record["status"] == "not_evaluated" and record["validated_tier"] == "T0"
    assert record["capital_authorized"] is False
    assert all(value["status"] == "not_evaluated" for value in record["qualifications"].values())


def test_parallel_receipt_never_authorizes_capital_even_when_complete(context):
    args, record = qualify(context)
    assert record["status"] == "passed" and record["validated_tier"] == "T2"
    ref = admission.write_receipt(args["validation_path"].parent, record)
    with pytest.raises(ValueError, match="parallel_has_no_capital"):
        admission.verify_for_new_capital(
            args["settings"],
            ref,
            definition_digest=context["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=context["source_sha256"],
            book=args["book"],
        )


def test_authoritative_t2_requires_source_switch_and_unchanged_family(context, monkeypatch):
    authoritative(context)
    args, record = qualify(context)
    ref = admission.write_receipt(args["validation_path"].parent, record)
    kwargs = dict(
        definition_digest=context["definition_digest"],
        validation_sha256=args["expected_validation_sha"],
        source_sha256=context["source_sha256"],
        book=args["book"],
    )
    with pytest.raises(ValueError, match="authority_disabled"):
        admission.verify_for_new_capital(args["settings"], ref, **kwargs)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    assert (
        admission.verify_for_new_capital(args["settings"], ref, **kwargs)["validated_tier"] == "T2"
    )
    ledger = args["settings"].data.data_dir / "trials/trials.jsonl"
    ledger.write_text(ledger.read_text() + "\n")
    with pytest.raises(ValueError, match="family_changed"):
        admission.verify_for_new_capital(args["settings"], ref, **kwargs)


def test_authority_needs_the_source_switch_and_installed_activation_together(
    context, monkeypatch
):
    """An activation file in a data directory is not a source switch by itself."""
    from quant_system.research import admission_activation

    authoritative(context)
    args, record = qualify(context)
    ref = admission.write_receipt(args["validation_path"].parent, record)
    kwargs = dict(
        definition_digest=context["definition_digest"],
        validation_sha256=args["expected_validation_sha"],
        source_sha256=context["source_sha256"],
        book=args["book"],
    )
    with pytest.raises(ValueError, match="authority_disabled"):
        admission.verify_for_new_capital(args["settings"], ref, **kwargs)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    assert (
        admission.verify_for_new_capital(args["settings"], ref, **kwargs)["validated_tier"] == "T2"
    )
    monkeypatch.setattr(admission_activation, "configured", lambda _settings: False)
    with pytest.raises(ValueError, match="authority_disabled"):
        admission.verify_for_new_capital(args["settings"], ref, **kwargs)


def test_replacement_without_lifecycle_is_not_evaluated(context):
    record = admission.evaluate_validation(**context, upgrade_target={"sleeve_id": "still-running"})
    assert record["status"] == "not_evaluated"
    assert record["reasons"] == ["admission_v2_replacement_lifecycle_unverified"]


@pytest.mark.parametrize("field,value", [("benchmark_symbol", "QQQ"), ("symbols", ["SPY"])])
def test_disclosed_profile_mismatch_rejects_even_resigned_engine_receipts(context, field, value):
    directory = context["validation_path"].parent
    result = json.loads((directory / "platform-result.json").read_text())
    result["profile"][field] = value
    write(directory / "platform-result.json", result)
    for name, digest_field in (
        ("qlib-replay.json", "platform_result_sha256"),
        ("signal-analysis.json", "result_sha256"),
    ):
        document = json.loads((directory / name).read_text())
        document["source"][digest_field] = admission.file_sha(directory / "platform-result.json")
        write(directory / name, document)
    validation = json.loads(context["validation_path"].read_text())
    validation["receipts"] = receipt_bindings(directory)
    write(context["validation_path"], validation)
    context["expected_validation_sha"] = admission.file_sha(context["validation_path"])
    rejected = admission.evaluate_validation(**context)
    assert rejected["gate"] is None
    assert rejected["reasons"] == ["admission_v2_result_profile_mismatch"]


@pytest.mark.parametrize(
    "field,value,allowed",
    [("title", "new display label", True), ("top_n", 3, False), ("commission_bps", 2, False)],
)
def test_planned_display_title_is_not_computation_but_other_fields_remain_bound(
    context, field, value, allowed
):
    from quant_system.research.external_intake import _sha
    from quant_system.research.intake_evaluation import digest

    path = (
        context["settings"].data.data_dir
        / "research_intake/jobs"
        / (context["protocol"]["job_id"] + ".json")
    )
    job = json.loads(path.read_text())
    job["plans"][0]["payload"][field] = value
    job["plans_sha256"] = _sha(job["plans"])
    evaluation = dict(context["evaluation"])
    evaluation["plans_sha256"] = job["plans_sha256"]
    evaluation.pop("evaluation_id")
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    job["evaluation"] = context["evaluation"] = evaluation
    write(path, job)
    validation = json.loads(context["validation_path"].read_text())
    validation["evaluation"] = evaluation
    write(context["validation_path"], validation)
    context["expected_validation_sha"] = admission.file_sha(context["validation_path"])
    before = context["source_sha256"]
    result = admission.evaluate_validation(**context)
    assert (result["gate"] is not None) is allowed, result["reasons"]
    assert (
        admission.file_sha(context["validation_path"].parent.parent.parent / "definition.json")
        == before
    )


def test_self_reported_json_without_fixed_producer_never_passes(context, monkeypatch):
    args, _ = qualify(context)
    # Keep all f69 self-reported pass/checks/scope/hash files, but remove the
    # explicitly mocked local execution verifier: JSON is not qualification.
    monkeypatch.setitem(sys.modules, "quant_system.research.admission_qualifier", None)
    rejected = admission.evaluate_validation(**args)
    assert rejected["status"] == "not_evaluated"
    assert all(
        row["reason"] == "qualification_producer_unavailable"
        for row in rejected["qualifications"].values()
    )


def test_qualified_but_different_control_scope_stays_not_evaluated(context, sealed_producer):
    args, receipt = qualify(context)
    ref = receipt["qualification_refs"]["consumer"]
    sealed_producer.contexts["consumer", ref["sha256"]]["top_n"] = 99
    rejected = admission.evaluate_validation(**args)
    assert rejected["status"] == "not_evaluated"
    assert (
        rejected["qualifications"]["consumer"]["reason"]
        == "qualification_calibration_context_mismatch"
    )


def test_disclosed_resigned_outer_receipt_cannot_change_protocol_mode(context):
    authoritative(context)
    args, receipt = qualify(context)
    receipt["mode"] = receipt["protocol"]["mode"] = "parallel"
    receipt["receipt_digest"] = _hash({k: v for k, v in receipt.items() if k != "receipt_digest"})
    ref = admission.write_receipt(args["validation_path"].parent, receipt)
    with pytest.raises(ValueError, match="protocol_digest_mismatch"):
        admission.read_bound_receipt(
            args["settings"],
            ref,
            definition_digest=args["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=args["source_sha256"],
        )


@pytest.mark.parametrize("mutation", ["intent", "target", "missing"])
def test_candidate_descriptor_intent_is_derived_from_bound_protocol(context, mutation):
    args, receipt = qualify(context)
    ref = admission.write_receipt(args["validation_path"].parent, receipt)
    assert ref["intent_kind"] == "new_independent"
    if mutation == "intent":
        ref["intent_kind"] = "replacement"
    elif mutation == "target":
        ref["target_sleeve_id"] = "invented"
    else:
        ref.pop("intent_kind")
    with pytest.raises(ValueError, match="descriptor_intent"):
        admission.read_bound_receipt(
            args["settings"],
            ref,
            definition_digest=args["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=args["source_sha256"],
        )


def test_old_parallel_without_intent_descriptor_remains_readable(context):
    args, receipt = qualify(context)
    protocol = context["protocol"]
    protocol.pop("intent")
    protocol["protocol_digest"] = _hash(
        {k: v for k, v in protocol.items() if k != "protocol_digest"}
    )
    path = (
        context["settings"].data.data_dir / "research_intake/jobs" / (protocol["job_id"] + ".json")
    )
    job = json.loads(path.read_text())
    job["admission_protocol"] = protocol
    for plan in job["plans"]:
        plan["origin"]["admission_protocol_digest"] = protocol["protocol_digest"]
    from quant_system.research.external_intake import _sha

    job["plans_sha256"] = _sha(job["plans"])
    write(path, job)
    receipt["protocol"] = protocol
    receipt["receipt_digest"] = _hash({k: v for k, v in receipt.items() if k != "receipt_digest"})
    ref = admission.write_receipt(args["validation_path"].parent, receipt)
    ref.pop("intent_kind")
    assert (
        admission.read_bound_receipt(
            args["settings"],
            ref,
            definition_digest=args["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=args["source_sha256"],
        )["mode"]
        == "parallel"
    )


def test_scope_or_input_qualification_tampering_is_not_a_pass(context):
    args, record = qualify(context)
    ref = record["qualification_refs"]["review"]
    path = __import__("pathlib").Path(ref["path"])
    value = json.loads(path.read_text())
    value["input_digest"] = "0" * 64
    write(path, value)
    changed = copy.deepcopy(record["qualification_refs"])
    changed["review"]["sha256"] = admission.file_sha(path)
    index = args["settings"].data.data_dir / "research_intake/admission_v2/qualifications.json"
    write(
        index,
        {
            "schema": "admission_qualification_index/v1",
            "entries": {_hash(record["source_binding"]): changed},
        },
    )
    rejected = admission.evaluate_validation(**args)
    assert rejected["status"] == "not_evaluated" and rejected["validated_tier"] == "T0"


def test_late_qualification_uses_same_protocol_and_preserves_unknown_receipt(context):
    first = admission.evaluate_validation(**context)
    before = admission.write_receipt(context["validation_path"].parent, first)
    old_bytes = __import__("pathlib").Path(before["path"]).read_bytes()
    protocol_digest = context["protocol"]["protocol_digest"]
    args, qualified = qualify(context)
    after = admission.write_receipt(args["validation_path"].parent, qualified)
    assert args["protocol"]["protocol_digest"] == protocol_digest
    assert before["sha256"] != after["sha256"] and before["path"] != after["path"]
    assert __import__("pathlib").Path(before["path"]).read_bytes() == old_bytes
    repeated = admission.write_receipt(
        args["validation_path"].parent, admission.evaluate_validation(**args)
    )
    assert repeated == after


def test_new_peer_after_qualification_fails_cas_before_capital(context, monkeypatch):
    authoritative(context)
    args, qualified = qualify(context)
    ref = admission.write_receipt(args["validation_path"].parent, qualified)
    from tests.test_capital_evidence import definition_archive
    from tests.test_capital_peer_binding import historical_peer

    _, archived, _ = definition_archive(args["settings"].data.data_dir / "peer-originals")
    peer = archived[6]
    peer.update(status="hung", sleeve_id="old-sleeve")
    book = {"candidates": [peer]}
    historical_peer(args["settings"], peer)
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    with pytest.raises(ValueError, match="peers_changed"):
        admission.verify_for_new_capital(
            args["settings"],
            ref,
            definition_digest=context["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=context["source_sha256"],
            book=book,
        )


def test_changed_base_price_receipt_cannot_be_laundered_by_valid_admission(context, monkeypatch):
    authoritative(context)
    args, qualified = qualify(context)
    ref = admission.write_receipt(args["validation_path"].parent, qualified)
    (args["validation_path"].parent / "prices.parquet").write_bytes(b"changed")
    monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
    with pytest.raises(ValueError, match="inputs_or_code_changed"):
        admission.verify_for_new_capital(
            args["settings"],
            ref,
            definition_digest=context["definition_digest"],
            validation_sha256=args["expected_validation_sha"],
            source_sha256=context["source_sha256"],
            book=args["book"],
        )


@pytest.mark.parametrize('module', ['fingerprint_grading.py', 'intake_factor_evaluation.py'])
def test_research_and_historical_identity_adapter_changes_invalidate_protocol(monkeypatch, module):
    from pathlib import Path

    protocol = admission.freeze_protocol('sealed-job', 'a' * 64)
    original = admission.file_sha
    monkeypatch.setattr(admission, 'file_sha', lambda p: 'f' * 64
                        if Path(p).name == module else original(p))
    with pytest.raises(ValueError, match='admission_v2_code_changed'):
        admission.verify_protocol(protocol)
