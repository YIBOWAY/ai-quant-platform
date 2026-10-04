"""Bounded switch evidence; no real queue, source switch or funds are modified."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.research import admission_activation as activation
from quant_system.research import admission_v2 as admission
from tests import test_admission_v2 as core
from tests.test_admission_qualification_flow import recipes


@pytest.fixture
def sealed_stage(tmp_path, monkeypatch):
    """Only the expensive fixed verifier is sealed; real state/protocol/CAS run."""
    context = core.context.__wrapped__(tmp_path)
    settings = context["settings"]
    recipes(settings)
    path = tmp_path / "research_intake/jobs" / (context["protocol"]["job_id"] + ".json")
    job = json.loads(path.read_text())
    job["status"] = "completed"
    core.write(path, job)
    history = tmp_path / "history.json"
    core.write(history, {"validation_references": []})
    monkeypatch.setattr(activation, "HISTORY_SHA", admission.file_sha(history))
    calls = []

    def review(settings, cohort):
        calls.append(dict(cohort))
        return {
            "closing_population": activation._current_population(settings),
            "rows": [{"job_id": job["job_id"], "conclusion_changed": True}],
            "files": {str(path): admission.file_sha(path)},
            "current_stage_populations": [],
            "historical_control_populations": [],
        }

    monkeypatch.setattr(activation, "_review_stage", review)
    monkeypatch.setattr(
        activation,
        "_classify_job",
        lambda settings, job: {"classification": "in_scope", "job_id": job["job_id"]},
    )
    activation._WARM.clear()
    return settings, history, path, calls


def test_empty_parallel_cohort_cannot_activate(tmp_path):
    from quant_system.research import admission_activation as activation

    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    result = activation.review_and_activate(settings, historical_inventory=None)
    assert result["status"] == "blocked"
    assert not activation.configured(settings)
    assert not (tmp_path / "research_intake/admission_v2/activation.json").exists()


def test_state_does_not_warm_funds_and_scope_remains_fixed(sealed_stage, monkeypatch):
    settings, history, _, calls = sealed_stage
    result = activation.review_and_activate(settings, historical_inventory=history)
    assert result["status"] == "activated" and not result["capital_authorized"]
    binding = activation.protocol_binding(settings)
    protocol = admission.freeze_protocol(
        "intake-" + "b" * 24, "d" * 64, mode="authoritative", activation=binding
    )
    context = binding["supported_scope"]["context"]
    with pytest.raises(ValueError, match="preflight_required"):
        activation.verify_for_funding(settings, protocol, context, allow_execution=False)
    assert len(calls) == 1
    activation.verify_for_funding(settings, protocol, context, allow_execution=True)
    assert len(calls) == 2
    monkeypatch.setattr(activation, "_review_stage", lambda *a: pytest.fail("money-lock program"))
    activation.verify_for_funding(settings, protocol, context, allow_execution=False)
    with pytest.raises(ValueError, match="outside_frozen_scope"):
        activation.verify_for_funding(
            settings, protocol, {**context, "end": "2026-09-21"}, allow_execution=False
        )
    activation._WARM.clear()
    with pytest.raises(ValueError, match="preflight_required"):
        activation.verify_for_funding(settings, protocol, context, allow_execution=False)


def test_disclosed_identical_activation_retry_keeps_original_protocol_binding(sealed_stage):
    settings, history, _, _ = sealed_stage
    first = activation.review_and_activate(settings, historical_inventory=history)
    binding = activation.protocol_binding(settings)
    protocol = admission.freeze_protocol(
        "intake-" + "b" * 24, "d" * 64, mode="authoritative", activation=binding
    )
    context = binding["supported_scope"]["context"]
    activation.verify_for_funding(settings, protocol, context, allow_execution=True)
    path = activation._root(settings) / "activation.json"
    original = path.read_bytes()
    second = activation.review_and_activate(settings, historical_inventory=history)
    assert first["state_digest"] == second["state_digest"]
    assert path.read_bytes() == original
    activation.verify_for_funding(settings, protocol, context, allow_execution=False)


def test_new_authoritative_job_does_not_change_closed_parallel_cohort(sealed_stage):
    from quant_system.research.external_intake import _sha

    settings, history, path, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    protocol = admission.freeze_protocol(
        "intake-" + "b" * 24,
        "d" * 64,
        mode="authoritative",
        activation=activation.protocol_binding(settings),
    )
    context = protocol["activation"]["supported_scope"]["context"]
    activation.verify_for_funding(settings, protocol, context, allow_execution=True)
    job = json.loads(path.read_text())
    job["job_id"] = protocol["job_id"]
    protocol = admission.freeze_protocol(
        job["job_id"],
        job["payload_sha256"],
        mode="authoritative",
        activation=activation.protocol_binding(settings),
    )
    job["admission_protocol"] = protocol
    for plan in job["plans"]:
        plan["origin"]["admission_protocol_digest"] = protocol["protocol_digest"]
    job["plans_sha256"] = _sha(job["plans"])
    core.write(path.parent / (job["job_id"] + ".json"), job)
    activation.verify_for_funding(settings, protocol, context, allow_execution=False)


def test_review_cas_rejects_job_change_before_state_write(sealed_stage, monkeypatch):
    settings, history, path, _ = sealed_stage
    real = activation._review_stage

    def change(settings, cohort):
        result = real(settings, cohort)
        job = json.loads(path.read_text())
        job["new_event"] = "changed during review"
        core.write(path, job)
        return result

    monkeypatch.setattr(activation, "_review_stage", change)
    result = activation.review_and_activate(settings, historical_inventory=history)
    assert result["status"] == "blocked" and "before_publish" in result["reasons"][0]
    assert not activation.configured(settings)


def test_stage_source_mutation_revokes_warm_state(sealed_stage):
    settings, history, path, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    protocol = admission.freeze_protocol(
        "intake-" + "b" * 24,
        "d" * 64,
        mode="authoritative",
        activation=activation.protocol_binding(settings),
    )
    context = protocol["activation"]["supported_scope"]["context"]
    activation.verify_for_funding(settings, protocol, context, allow_execution=True)
    job = json.loads(path.read_text())
    job["status"] = "queued"
    core.write(path, job)
    with pytest.raises(ValueError, match="stage_inputs_changed"):
        activation.verify_for_funding(settings, protocol, context, allow_execution=False)


def test_resigned_state_cannot_omit_input_files_from_warm_proof(sealed_stage):
    from pathlib import Path

    settings, history, _, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    state_path = activation._root(settings) / "activation.json"
    state = json.loads(state_path.read_text())
    stage_path = Path(state["stage"]["path"])
    stage = json.loads(stage_path.read_text())
    stage["review"]["files"] = {}
    stage = activation._seal({k: v for k, v in stage.items() if k != "digest"})
    core.write(stage_path, stage)
    state["stage"]["sha256"] = admission.file_sha(stage_path)
    state = activation._seal({k: v for k, v in state.items() if k != "digest"})
    core.write(state_path, state)
    state_path.chmod(0o600)
    protocol = admission.freeze_protocol(
        "intake-" + "b" * 24,
        "d" * 64,
        mode="authoritative",
        activation=activation.protocol_binding(settings),
    )
    with pytest.raises(ValueError, match="file_manifest_mismatch"):
        activation.verify_for_funding(
            settings,
            protocol,
            protocol["activation"]["supported_scope"]["context"],
            allow_execution=True,
        )


def test_actual_new_capital_uses_bound_activation_under_source_switch(tmp_path, monkeypatch):
    """Actual account/sleeve consumer; fixed verification capabilities are explicitly sealed."""
    from pathlib import Path

    from quant_system.execution import assistant_remote as remote
    from quant_system.research import external_intake as intake
    from quant_system.research import strategy_library as library
    from tests.test_admission_v2_consumers import consumer

    producer = core.sealed_producer.__wrapped__(monkeypatch)
    next(producer)
    try:
        context = core.context.__wrapped__(tmp_path)
        source_context = admission.qualification_input_context(
            {"validation_path": str(context["validation_path"])}
        )
        source_context["rebalance"] = "monthly"
        monkeypatch.setattr(
            activation,
            "_scope",
            lambda _dataset=None: {
                "scope": admission.SCOPE,
                "dataset": "sealed_test_only",
                "context": source_context,
            },
        )
        recipes(context["settings"])
        path = tmp_path / "research_intake/jobs" / (context["protocol"]["job_id"] + ".json")
        phase = json.loads(path.read_text())
        phase.update(status="completed", budget_day="2000-01-01")
        core.write(path, phase)
        history = tmp_path / "history.json"
        core.write(history, {"validation_references": []})
        monkeypatch.setattr(activation, "HISTORY_SHA", admission.file_sha(history))
        stage_calls = []

        def fixed_review(settings, cohort):
            stage_calls.append(cohort)
            return {
                "rows": [],
                "files": {str(path): admission.file_sha(path)},
                "closing_population": activation._current_population(settings),
            }

        monkeypatch.setattr(activation, "_review_stage", fixed_review)
        monkeypatch.setattr(
            activation,
            "_classify_job",
            lambda settings, job: {"classification": "in_scope", "job_id": job["job_id"]},
        )
        assert (
            activation.review_and_activate(context["settings"], historical_inventory=history)[
                "status"
            ]
            == "activated"
        )
        state_path = activation._root(context["settings"]) / "activation.json"
        state_before = state_path.read_bytes()
        ledger_path = tmp_path / "trials/trials.jsonl"
        ledger_before = ledger_path.read_bytes()
        # Disable automatic producer for this transaction fixture; explicit
        # sealed registrations below still pass the ordinary full consumer.
        monkeypatch.setattr(
            "quant_system.research.admission_qualification_flow.ensure_qualifications",
            lambda *a, **k: {"status": "not_configured"},
        )
        settings, _, result, entry, _ = consumer(
            context, monkeypatch, "parallel", keep_context_job=True
        )
        protocol = result["admission_protocol"]
        assert ledger_path.read_bytes() != ledger_before
        assert len(ledger_path.read_text().splitlines()) == len(ledger_before.splitlines()) + 1
        assert protocol["mode"] == "authoritative" and "activation" in protocol
        assert intake.read_policy(settings).admission_mode == "parallel"
        args = dict(
            settings=settings,
            protocol=protocol,
            validation_path=Path(entry["admission_v2"]["path"]).parent / "validation.json",
            expected_validation_sha=entry["validation_sha256"],
            definition_digest=entry["definition_digest"],
            source_sha256=entry["source_sha256"],
            evaluation=entry["evaluation"],
            book=remote.load_book(settings),
        )
        core.qualify(args)
        catalog = activation._root(settings) / "qualifications.json"
        assert catalog.is_file() and json.loads(catalog.read_text())["entries"]
        replay = activation.review_and_activate(settings, historical_inventory=history)
        assert replay["status"] == "activated" and state_path.read_bytes() == state_before
        ready = library.refresh_admission(
            settings, entry["strategy_id"], entry["evaluation"], protocol, publish_entry=True
        )
        candidate = next(
            c
            for c in remote.load_book(settings)["candidates"]
            if c["candidate_id"] == ready["candidate_id"]
        )
        assert admission.AUTHORITATIVE_ENABLED is False
        with pytest.raises(remote.AssistantRemoteError, match="authority_disabled"):
            remote.hang_candidate(
                settings,
                candidate_id=candidate["candidate_id"],
                expected_source_digest=candidate["source_digest"],
            )
        # Actual money needs the module source switch and the installed
        # activation together; the binding preflight still runs at enable time.
        monkeypatch.setattr(admission, "AUTHORITATIVE_ENABLED", True)
        before = len(stage_calls)
        outcome = remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
        assert outcome["status"] == "hung" and len(stage_calls) == before + 1
    finally:
        producer.close()


@pytest.mark.parametrize("tier", ["T2", "T0"])
def test_fixed_stage_reviews_real_all_variant_gate_without_requiring_winners(
    tmp_path, monkeypatch, tier
):
    """Saved-curve/gate/lineage are real; only qualification capability is sealed."""
    import importlib
    import sys

    from quant_system.research.validation_receipts import receipt_bindings

    # Load this real dependency before replacing only the qualification
    # capability module. Selected-node runs must not depend on suite order.
    importlib.import_module("quant_system.research.admission_window")
    producer = core.sealed_producer.__wrapped__(monkeypatch)
    next(producer)
    try:
        context = core.context.__wrapped__(tmp_path)
        settings = context["settings"]
        run = context["validation_path"].parent
        if tier == "T0":
            result = json.loads((run / "platform-result.json").read_text())
            equity = 10000
            for i, row in enumerate(result["curve"]):
                equity *= 1 - 0.003 + (0.004 if i % 2 else -0.004)
                row["equity"] = equity
            core.write(run / "platform-result.json", result)
            for name, field in (
                ("qlib-replay.json", "platform_result_sha256"),
                ("signal-analysis.json", "result_sha256"),
            ):
                item = json.loads((run / name).read_text())
                item["source"][field] = admission.file_sha(run / "platform-result.json")
                core.write(run / name, item)
            base = json.loads(context["validation_path"].read_text())
            base["receipts"] = receipt_bindings(run)
            core.write(context["validation_path"], base)
            context["expected_validation_sha"] = admission.file_sha(context["validation_path"])
        _, receipt = core.qualify(context, expected_tier=tier)
        descriptor = admission.write_receipt(run, receipt)
        path = tmp_path / "research_intake/jobs" / (context["protocol"]["job_id"] + ".json")
        job = json.loads(path.read_text())
        job.update(
            status="completed",
            results=[
                {
                    "variant": "formula",
                    "admission_v2": descriptor,
                    "validation_sha256": context["expected_validation_sha"],
                }
            ],
        )
        core.write(path, job)
        recipes(settings)
        scope = admission.qualification_input_context(receipt["source_binding"])
        monkeypatch.setattr(
            activation, "_scope", lambda: {"scope": admission.SCOPE, "context": scope}
        )
        monkeypatch.setattr(
            "quant_system.research.admission_qualification_flow.ensure_qualifications",
            lambda *a, **k: {"status": "registered"},
        )
        fixed = sys.modules["quant_system.research.admission_qualifier"]
        verify = fixed.verify_registered_qualification

        def capability(*args, **kwargs):
            result = verify(*args, **kwargs)
            if kwargs["kind"] == "consumer" and result["status"] == "passed":
                result["details"].update(
                    calibration_digest="a" * 64,
                    control_version="sealed",
                    historical_control_population={"family_digest": "b" * 64},
                )
            return result

        monkeypatch.setattr(fixed, "verify_registered_qualification", capability)
        reviewed = activation._review_stage(settings, activation._snapshot(settings)["cohort"])
        assert len(reviewed["rows"]) == 1
        assert reviewed["rows"][0]["current_qualified_tier"] == tier
        assert reviewed["rows"][0]["current_family_n_trials"] == 12
        monkeypatch.setattr(
            activation,
            "_scope",
            lambda _dataset=None: {
                "scope": admission.SCOPE,
                "context": {**scope, "top_n": scope["top_n"] + 1},
            },
        )
        outside = activation._snapshot(settings)
        assert outside["cohort"] == {} and outside["unknown"] == []
        assert outside["exclusions"][0]["job_id"] == job["job_id"]
        assert "top_n" in outside["exclusions"][0]["variants"][0]["scope_mismatches"]
        (run / "prices.parquet").write_bytes(b"changed actual input")
        corrupted = activation._snapshot(settings)
        assert corrupted["exclusions"] == [] and corrupted["unknown"]
        assert job["job_id"] in corrupted["cohort"]
        job["results"] = []
        core.write(path, job)
        with pytest.raises(ValueError, match="variants_incomplete"):
            activation._review_stage(settings, activation._snapshot(settings)["cohort"])
    finally:
        producer.close()


def _legacy_parallel_job(tmp_path, monkeypatch):
    """A consumer job frozen as parallel, exactly as jobs accepted before the switch."""
    from quant_system.execution import assistant_remote as remote
    from tests.test_admission_v2_consumers import consumer

    producer = core.sealed_producer.__wrapped__(monkeypatch)
    next(producer)
    context = core.context.__wrapped__(tmp_path)
    settings = context["settings"]
    settings, job, _, _, _ = consumer(context, monkeypatch, "parallel")
    recipes(settings)
    candidate = remote.load_book(settings)["candidates"][0]
    assert admission.candidate_receipt(settings, candidate)["mode"] == "parallel"
    return producer, settings, job, candidate


def test_parallel_job_keeps_legacy_capital_path_before_the_switch(tmp_path, monkeypatch):
    from quant_system.execution import assistant_remote as remote

    producer, settings, _, candidate = _legacy_parallel_job(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(
            activation, "_activation_status", lambda _settings: ("absent", None)
        )
        outcome = remote.hang_candidate(
            settings,
            candidate_id=candidate["candidate_id"],
            expected_source_digest=candidate["source_digest"],
        )
        assert outcome["status"] == "hung"
    finally:
        producer.close()


def test_installed_switch_withdraws_new_capital_from_parallel_job(tmp_path, monkeypatch):
    from quant_system.execution import assistant_remote as remote

    producer, settings, job, candidate = _legacy_parallel_job(tmp_path, monkeypatch)
    try:
        history = tmp_path / "history.json"
        core.write(history, {"validation_references": []})
        monkeypatch.setattr(activation, "HISTORY_SHA", admission.file_sha(history))
        path = tmp_path / "research_intake/jobs" / (job["job_id"] + ".json")
        monkeypatch.setattr(
            activation,
            "_review_stage",
            lambda settings, cohort: {
                "rows": [],
                "files": {str(path): admission.file_sha(path)},
                "closing_population": activation._current_population(settings),
            },
        )
        monkeypatch.setattr(
            activation,
            "_classify_job",
            lambda settings, job: {"classification": "in_scope", "job_id": job["job_id"]},
        )
        assert (
            activation.review_and_activate(settings, historical_inventory=history)["status"]
            == "activated"
        )
        assert (activation._root(settings) / "activation.json").is_file()
        monkeypatch.setattr(
            activation, "_activation_status", lambda _settings: ("valid", {"digest": "x"})
        )
        with pytest.raises(
            remote.AssistantRemoteError, match="activation_parallel_capital_blocked"
        ):
            remote.hang_candidate(
                settings,
                candidate_id=candidate["candidate_id"],
                expected_source_digest=candidate["source_digest"],
            )
        assert not (settings.data.data_dir / "api_runs").exists()
    finally:
        producer.close()


def test_bound_input_outside_frozen_scope_ends_terminal_not_waiting(tmp_path, monkeypatch):
    """A bound input outside the frozen scope has no retry, so it must not keep waiting."""
    from quant_system.execution import assistant_remote as remote
    from quant_system.research import external_intake as intake
    from tests.test_admission_v2_consumers import consumer

    producer = core.sealed_producer.__wrapped__(monkeypatch)
    next(producer)
    try:
        context = core.context.__wrapped__(tmp_path)
        settings = context["settings"]
        source_context = admission.qualification_input_context(
            {"validation_path": str(context["validation_path"])}
        )
        source_context["rebalance"] = "monthly"
        monkeypatch.setattr(
            activation,
            "_scope",
            lambda _dataset=None: {
                "scope": admission.SCOPE,
                "dataset": "sealed_test_only",
                "context": {**source_context, "start": "2014-01-01"},
            },
        )
        path = tmp_path / "research_intake/jobs" / (context["protocol"]["job_id"] + ".json")
        phase = json.loads(path.read_text())
        phase.update(status="completed", budget_day="2000-01-01")
        core.write(path, phase)
        history = tmp_path / "history.json"
        core.write(history, {"validation_references": []})
        monkeypatch.setattr(activation, "HISTORY_SHA", admission.file_sha(history))
        monkeypatch.setattr(
            activation,
            "_review_stage",
            lambda settings, cohort: {
                "rows": [],
                "files": {str(path): admission.file_sha(path)},
                "closing_population": activation._current_population(settings),
            },
        )
        monkeypatch.setattr(
            activation,
            "_classify_job",
            lambda settings, job: {"classification": "in_scope", "job_id": job["job_id"]},
        )
        recipes(settings)
        assert (
            activation.review_and_activate(settings, historical_inventory=history)["status"]
            == "activated"
        )
        monkeypatch.setattr(
            "quant_system.research.admission_qualification_flow.ensure_qualifications",
            lambda *a, **k: {"status": "not_configured"},
        )
        settings, _, result, _, _ = consumer(
            context, monkeypatch, "parallel", keep_context_job=True
        )
        assert result["status"] == "activation_blocked"
        assert result["results"][0]["phase"] == "activation_blocked"
        assert result["results"][0]["error"] == "activation_input_outside_frozen_scope"
        report = intake.sync_report(settings)
        item = next(row for row in report["items"] if row["job_id"] == result["job_id"])
        assert item["status"] == "activation_blocked"
        assert item["results"][0]["error"] == "activation_input_outside_frozen_scope"
        assert not (settings.data.data_dir / "api_runs").exists()
        assert remote.load_book(settings)["candidates"] == []
    finally:
        producer.close()


def test_present_but_unusable_activation_blocks_legacy_capital(tmp_path):
    """A present-but-invalid switch must not look like an absent one."""
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    assert activation.activation_status(settings) == "absent"
    assert not activation.capital_requires_authoritative_job(settings, None)

    root = activation._root(settings)
    root.mkdir(parents=True)
    (root / "activation.json").write_text(
        json.dumps({"schema": activation.SCHEMA, "digest": "0" * 64})
    )
    status = activation.activation_status(settings)
    assert status.startswith("invalid:")
    assert not activation.configured(settings)
    assert activation.capital_requires_authoritative_job(settings, None)
    assert activation.capital_requires_authoritative_job(settings, {"mode": "parallel"})
    assert not activation.capital_requires_authoritative_job(
        settings, {"mode": "authoritative"}
    )


@pytest.mark.parametrize(
    "kind", ["dangling_symlink", "directory", "fifo", "json_list", "json_null"]
)
def test_nonregular_or_nonobject_activation_never_looks_absent(tmp_path, monkeypatch, kind):
    """Real malformed filesystem entries cannot silently restore the legacy path."""
    import os

    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    path = activation._root(settings) / "activation.json"
    path.parent.mkdir(parents=True)
    if kind == "dangling_symlink":
        path.symlink_to(path.parent / "missing.json")
    elif kind == "directory":
        path.mkdir(mode=0o700)
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
        original_read = Path.read_text

        def refuse_fifo_read(p, *args, **kwargs):
            assert p != path, "nonregular activation must be rejected before reading"
            return original_read(p, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", refuse_fifo_read)
    else:
        path.write_text("[]" if kind == "json_list" else "null")
        path.chmod(0o600)
    assert activation.activation_status(settings).startswith("invalid:")
    assert not activation.configured(settings)
    assert activation.capital_requires_authoritative_job(settings, {"mode": "parallel"})
    with pytest.raises(ValueError):
        activation.protocol_binding(settings)


def test_dangling_activation_blocks_actual_isolated_legacy_consumer(tmp_path, monkeypatch):
    from quant_system.execution import assistant_remote as remote

    producer, settings, _, candidate = _legacy_parallel_job(tmp_path, monkeypatch)
    try:
        path = activation._root(settings) / "activation.json"
        path.symlink_to(path.parent / "missing.json")
        before = remote.load_book(settings)
        with pytest.raises(
            remote.AssistantRemoteError, match="activation_parallel_capital_blocked"
        ):
            remote.hang_candidate(
                settings,
                candidate_id=candidate["candidate_id"],
                expected_source_digest=candidate["source_digest"],
            )
        assert remote.load_book(settings) == before
        assert not (settings.data.data_dir / "api_runs").exists()
    finally:
        producer.close()


def test_activation_read_error_blocks_legacy_capital(tmp_path, monkeypatch):
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    path = activation._root(settings) / "activation.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}")
    path.chmod(0o600)
    original_read = Path.read_text

    def denied(p, *args, **kwargs):
        if p == path:
            raise PermissionError("isolated activation read denied")
        return original_read(p, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    assert activation.activation_status(settings).startswith("invalid:")
    assert not activation.configured(settings)
    assert activation.capital_requires_authoritative_job(settings, None)


@pytest.mark.parametrize("change", ["source", "missing_stage"])
def test_expired_activation_keeps_parallel_capital_withdrawn(sealed_stage, change):
    settings, history, _, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    path = activation._root(settings) / "activation.json"
    state = json.loads(path.read_text())
    if change == "source":
        state["code_digest"] = "0" * 64
        state = activation._seal({k: v for k, v in state.items() if k != "digest"})
        core.write(path, state)
        path.chmod(0o600)
    else:
        Path(state["stage"]["path"]).unlink()
    assert activation.activation_status(settings).startswith("invalid:")
    assert not activation.configured(settings)
    assert activation.capital_requires_authoritative_job(settings, {"mode": "parallel"})


def test_deactivate_cannot_race_an_active_review(sealed_stage):
    from quant_system.research.external_intake import _lock

    settings, history, _, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    path = activation._root(settings) / "activation.json"
    before = path.read_bytes()
    with (
        _lock(activation._root(settings) / "activation-review.lock", nonblocking=True),
        pytest.raises(BlockingIOError),
    ):
        activation.deactivate(settings, reason="isolated competing revoke")
    assert path.read_bytes() == before
    assert not (activation._root(settings) / "deactivated").exists()


@pytest.mark.parametrize("kind", ["dangling_symlink", "valid_symlink", "directory", "fifo"])
def test_deactivate_refuses_nonregular_state_before_reading(tmp_path, monkeypatch, kind):
    import os

    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    path = activation._root(settings) / "activation.json"
    path.parent.mkdir(parents=True)
    target = tmp_path / "other-state.json"
    target.write_bytes(b'{"original":"must remain untouched"}\n')
    target.chmod(0o600)
    if kind in {"dangling_symlink", "valid_symlink"}:
        path.symlink_to(target if kind == "valid_symlink" else tmp_path / "missing.json")
    elif kind == "directory":
        path.mkdir(mode=0o700)
    else:
        os.mkfifo(path, 0o600)
    original_read = Path.read_bytes

    def refuse_nonregular_read(p):
        assert p != path, "nonregular activation must be refused before reading"
        return original_read(p)

    monkeypatch.setattr(Path, "read_bytes", refuse_nonregular_read)
    with pytest.raises(ValueError, match="activation_regular_file_required"):
        activation.deactivate(settings, reason="isolated nonregular revoke")
    assert target.read_bytes() == b'{"original":"must remain untouched"}\n'
    assert path.is_symlink() or path.exists()
    assert activation.capital_requires_authoritative_job(settings, None)


def test_deactivation_final_compare_preserves_changed_current_state(sealed_stage, monkeypatch):
    from quant_system.research import external_intake as intake

    settings, history, _, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    path = activation._root(settings) / "activation.json"
    original_write = intake._write
    changed = b'{"isolated_external_change":true}\n'

    def change_after_note(p, value):
        original_write(p, value)
        if p.name.endswith(".removed.json"):
            path.write_bytes(changed)

    monkeypatch.setattr(intake, "_write", change_after_note)
    with pytest.raises(ValueError, match="deactivate_artifact_changed_during_move"):
        activation.deactivate(settings, reason="isolated concurrent filesystem change")
    assert path.read_bytes() == changed
    assert activation.capital_requires_authoritative_job(settings, None)


def test_repeated_deactivation_of_same_bytes_preserves_both_event_notes(sealed_stage):
    settings, history, _, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    path = activation._root(settings) / "activation.json"
    original = path.read_bytes()
    first = activation.deactivate(settings, reason="first isolated revoke")
    first_note = Path(first["archived_at"]).with_suffix("").with_suffix(".removed.json")
    first_bytes = first_note.read_bytes()
    # Explicit isolated restore models the same sealed state being installed again.
    path.write_bytes(original)
    path.chmod(0o600)
    second = activation.deactivate(settings, reason="second isolated revoke")
    assert first_note.read_bytes() == first_bytes
    assert first["archived_at"] != second["archived_at"]
    assert len(list(first_note.parent.glob("*.removed.json"))) == 2


def test_deactivate_archives_sealed_switch_and_resumes_pre_switch_rules(sealed_stage):
    settings, history, _, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    assert activation.activation_status(settings) == "valid"
    result = activation.deactivate(settings, reason="unit_test_revoke")
    assert result["status"] == "deactivated"
    assert activation.activation_status(settings) == "absent"
    assert not activation.configured(settings)
    assert not activation.capital_requires_authoritative_job(settings, None)

    archived = Path(result["archived_at"])
    assert archived.read_bytes()
    assert admission.file_sha(archived) == result["activation_sha256"]
    assert archived.parent.stat().st_mode & 0o777 == 0o700
    assert archived.stat().st_mode & 0o777 == 0o600
    note_path = archived.with_suffix("").with_suffix(".removed.json")
    assert note_path.stat().st_mode & 0o777 == 0o600
    note = json.loads(note_path.read_text())
    assert note["reason"] == "unit_test_revoke"
    assert note["valid_at_removal"] is True
    with pytest.raises(ValueError, match="activation_missing"):
        activation.deactivate(settings, reason="second_time_refused")


def test_later_parallel_job_does_not_brick_the_installed_switch(sealed_stage):
    """Natural out-of-scope parallel jobs may arrive after activation without muting it."""
    settings, history, path, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    binding = activation.protocol_binding(settings)
    protocol = admission.freeze_protocol(
        "intake-" + "c" * 24, "e" * 64, mode="authoritative", activation=binding
    )
    context = binding["supported_scope"]["context"]
    activation.verify_for_funding(settings, protocol, context, allow_execution=True)

    from quant_system.research.external_intake import _sha

    later = json.loads(path.read_text())
    later["job_id"] = "intake-" + "f" * 24
    later_protocol = admission.freeze_protocol(
        later["job_id"], later["payload_sha256"], mode="parallel"
    )
    later["admission_protocol"] = later_protocol
    for plan in later["plans"]:
        plan["origin"]["admission_protocol_digest"] = later_protocol["protocol_digest"]
    later["plans_sha256"] = _sha(later["plans"])
    core.write(path.parent / (later["job_id"] + ".json"), later)

    activation._WARM.clear()
    activation.verify_for_funding(settings, protocol, context, allow_execution=True)
    activation._WARM.clear()
    with pytest.raises(ValueError, match="preflight_required"):
        activation.verify_for_funding(settings, protocol, context, allow_execution=False)


def test_recorded_cohort_member_change_still_bricks_the_switch(sealed_stage):
    settings, history, path, _ = sealed_stage
    assert (
        activation.review_and_activate(settings, historical_inventory=history)["status"]
        == "activated"
    )
    binding = activation.protocol_binding(settings)
    protocol = admission.freeze_protocol(
        "intake-" + "c" * 24, "e" * 64, mode="authoritative", activation=binding
    )
    context = binding["supported_scope"]["context"]
    activation.verify_for_funding(settings, protocol, context, allow_execution=True)
    tampered = json.loads(path.read_text())
    tampered["tampered_after_switch"] = True
    core.write(path, tampered)
    with pytest.raises(ValueError, match="activation_stage_inputs_changed"):
        activation.verify_for_funding(settings, protocol, context, allow_execution=True)
