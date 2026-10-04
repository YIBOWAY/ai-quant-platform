"""Sealed intake tests: no network, Docker, provider or real account effects."""

import copy
import io
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from quant_system.research import external_intake as service
from quant_system.research import external_intake_cli as cli
from quant_system.research.strategy_definition import StrategyDefinition


@pytest.fixture
def settings(tmp_path, monkeypatch):
    value = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    value.model_copy = lambda **_: value
    monkeypatch.setattr(cli, "load_settings", lambda: value)
    return value


def policy(settings, **updates):
    directory = service.root(settings)
    directory.mkdir(exist_ok=True)
    path = directory / "policy.json"
    path.write_text(json.dumps(service.IntakePolicy(enabled=True, **updates).model_dump()))
    path.chmod(0o600)
    return path


def proposal(**updates):
    return {
        "schema_version": 1,
        "proposal_id": "grok-2026-09-09-01",
        "source_urls": ["https://example.org/original-paper"],
        "source_title": "ORIGINAL_PRIVATE_SOURCE_TITLE",
        "published_at": "2024-01-10",
        "retrieved_at": "2026-09-09T08:00:00Z",
        "hypothesis": "DO_NOT_PRINT_SOURCE_HYPOTHESIS",
        "expression": "$close/Ref($close,21)-1",
        "adaptation_note": "DO_NOT_PRINT_PRIVATE_ADAPTATION",
        **updates,
    }


def active_proposal(**updates):
    return proposal(
        **{
            "baseline_factor_ids": ["momentum"],
            "increment_objective": {
                "metric": "sharpe",
                "minimum_improvement": 0.1,
                "max_regressions": {},
            },
            **updates,
        }
    )


def invoke(args, data=""):
    output = io.StringIO()
    code = cli.main(args, stdin=io.StringIO(data), stdout=output)
    return code, json.loads(output.getvalue())


class SealedLibrary:
    def __init__(self):
        self.entries = {}
        self.calls = []
        self.validation_status = "validated"
        self.validate_hook = None
        self.enable_hook = None
        self.archives = {}
        self.recovery_ready = False

    def read_strategy(self, _settings, strategy_id):
        if strategy_id not in self.entries:
            raise FileNotFoundError
        return copy.deepcopy(self.entries[strategy_id])

    def compose_strategy(self, _settings, payload):
        definition = StrategyDefinition(history_start="2015-01-01", **payload)
        return self._save_definition(_settings, definition, {"type": "compose"})

    def _save_definition(self, _settings, definition, origin):
        strategy_id = "strategy-" + definition.content_digest[:24]
        self.calls.append(("compose", strategy_id, definition.model_dump(mode="json")))
        if strategy_id in self.entries:
            return copy.deepcopy(self.entries[strategy_id])
        self.entries[strategy_id] = {
            "strategy_id": strategy_id,
            "definition_digest": definition.content_digest,
            "status": "draft",
            "origin": copy.deepcopy(origin),
            "execution_ready": True,
        }
        return copy.deepcopy(self.entries[strategy_id])

    def validate_strategy(
        self, settings, strategy_id, expected_digest, *, evaluation=None, publish_entry=True,
        admission_context=None,
    ):
        self.calls.append(("validate", strategy_id, expected_digest))
        entry = (
            self.entries[strategy_id] if publish_entry else copy.deepcopy(self.entries[strategy_id])
        )
        assert entry["definition_digest"] == expected_digest
        entry.update(
            status=self.validation_status,
            validation={
                "run_id": "validation-" + "1" * 32,
                "definition_digest": expected_digest,
                "platform_metrics": {
                    "sharpe": 1.0 if entry["origin"].get("variant") == "baseline" else 1.23
                },
                "start": evaluation["start"] if evaluation else entry["origin"].get("start"),
                "end": evaluation["end"] if evaluation else entry["origin"].get("end"),
                "comparison": {"accepted": True},
                "evaluation_calendar_digest": "c" * 64,
                "blockers": [] if self.validation_status == "validated" else ["dsr_failed"],
                "historical_scope": "retrospective_not_unseen_holdout",
            },
            validation_sha256="2" * 64,
            candidate_id="strategy-candidate",
            evaluation=copy.deepcopy(evaluation),
        )
        try:
            if self.validate_hook:
                self.validate_hook(settings, entry)
        finally:
            if evaluation and entry["status"] in {"validated", "validation_failed"}:
                self.archives[strategy_id, evaluation["evaluation_id"]] = copy.deepcopy(entry)
        return copy.deepcopy(entry)

    def find_evaluation(self, settings, strategy_id, evaluation):
        return copy.deepcopy(self.archives.get((strategy_id, evaluation["evaluation_id"])))

    def evaluation_recovery_ready(self, settings, strategy_id, evaluation):
        return self.recovery_ready

    def enable_strategy(self, settings, strategy_id, expected_digest, *, expected_receipt=None):
        from quant_system.research.validation_receipts import require_activation_receipt

        if expected_receipt is not None:
            require_activation_receipt(self.entries[strategy_id], expected_receipt)
        self.calls.append(("enable", strategy_id, expected_digest))
        entry = self.entries[strategy_id]
        assert entry["definition_digest"] == expected_digest
        if self.enable_hook:
            self.enable_hook(settings, entry)
        entry.update(status="paper_running", sleeve_id="sleeve-new-intake")
        return copy.deepcopy(entry)


@pytest.fixture
def engine(monkeypatch):
    sealed = SealedLibrary()
    for name in (
        "compose_strategy",
        "_save_definition",
        "validate_strategy",
        "enable_strategy",
        "read_strategy",
        "find_evaluation",
        "evaluation_recovery_ready",
    ):
        monkeypatch.setattr(service.library, name, getattr(sealed, name))
    monkeypatch.setattr(
        service.library,
        "_collect_prices",
        lambda *_: (
            pd.DataFrame({"timestamp": ["2026-09-08"], "symbol": ["SPY"], "close": [100.0]}),
            {},
        ),
    )
    return sealed


def test_default_paused_reads_are_observational(settings, engine):
    assert service.run_once(settings) == {"status": "paused", "processed": 0}
    caps = service.capabilities(settings)
    assert caps["policy"]["enabled"] is False
    assert len(caps["scope"]["symbols"]) == 24
    assert caps["scope"]["benchmark_symbol"] == "SPY"
    assert caps["scope"]["top_n"] == 5
    assert service.list_jobs(settings) == {"items": []}
    with pytest.raises(ValueError, match="intake_paused"):
        service.submit(settings, proposal())
    assert not service.root(settings).exists()
    assert not engine.calls


def test_sync_report_empty_reads_do_not_initialize_state(settings, engine):
    code, report = invoke(["sync-report"])
    assert code == 0
    assert report["items"] == [] and report["total_jobs"] == 0
    assert report["latest_job_updated_at"] is None
    assert not service.root(settings).exists()
    assert not engine.calls


def test_sync_report_includes_rejections_without_writes_or_private_material(settings, engine):
    policy(settings)
    first = service.submit(settings, active_proposal())
    engine.validation_status = "validation_failed"
    service.run_once(settings)
    service.submit(settings, proposal(proposal_id="next-job"))
    before = {str(p): p.read_bytes() for p in service.root(settings).rglob("*") if p.is_file()}
    calls = list(engine.calls)

    code, report = invoke(["sync-report"])
    assert code == 0 and report["ok"]
    assert report["total_jobs"] == 2
    assert report["counts_by_outcome"] == {"quality_rejected": 1, "queued": 1}
    item = next(row for row in report["items"] if row["job_id"] == first["job_id"])
    assert item["outcome"] == "quality_rejected"
    assert item["results"][0]["blockers"] == ["dsr_failed"]
    assert item["results"][0]["validation_run_id"]
    assert item["results"][0]["validation_sha256"]
    assert item["record_sha256"]
    assert "DO_NOT_PRINT" not in json.dumps(report)
    assert "ORIGINAL_PRIVATE" not in json.dumps(report)
    after = {str(p): p.read_bytes() for p in service.root(settings).rglob("*") if p.is_file()}
    assert before == after
    assert engine.calls == calls
    assert report["content_sha256"] == invoke(["sync-report"])[1]["content_sha256"]


def test_sync_report_does_not_report_corrupt_ledger_as_empty(settings):
    policy(settings)
    job = service.submit(settings, proposal())
    path = service._job_path(settings, job["job_id"])
    raw = json.loads(path.read_text())
    raw["proposal"]["hypothesis"] = "changed"
    path.write_text(json.dumps(raw))
    code, report = invoke(["sync-report"])
    assert code == 2 and report["ok"] is False
    assert report["error"] == "intake_record_integrity_failed"


def test_policy_owner_only_and_never_set_by_cli(settings):
    path = policy(settings)
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner_only"):
        service.read_policy(settings)
    path.chmod(0o600)
    assert service.read_policy(settings).enabled
    code, result = invoke(["policy", "--auto-enable"])
    assert code == 2 and result["error"] == "intake_cli_arguments_invalid"


def test_policy_symlink_rejected(settings):
    path = policy(settings)
    original = path.with_name("original.json")
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(ValueError, match="owner_only"):
        service.read_policy(settings)


@pytest.mark.parametrize(
    "updates",
    [
        {"schema_version": True},
        {"schema_version": "1"},
        {"source_urls": ["http://example.org"]},
        {"source_urls": ["https://user:secret@example.org"]},
        {"source_urls": []},
        {"retrieved_at": "2026-09-09T00:00:00"},
        {"published_at": "2026-02-30"},
        {"hypothesis": " "},
        {"command": "run something"},
        {"auto_enable": True},
        {"baseline_factor_ids": ["momentum", "momentum"]},
        {"baseline_factor_ids": ["momentum", "rsi", "macd"]},
    ],
)
def test_strict_schema(settings, updates, engine):
    policy(settings)
    with pytest.raises((ValidationError, ValueError)):
        service.submit(settings, proposal(**updates))
    assert service.list_jobs(settings) == {"items": []}
    assert not engine.calls


@pytest.mark.parametrize(
    "raw,error",
    [
        ('{"x":1,"x":2}', "duplicate_json_key"),
        ('{"x":{"a":1,"a":2}}', "duplicate_json_key"),
        ('{"x":NaN}', "nonfinite_json"),
        ("[]", "object_required"),
        ("{", "json_invalid"),
        ("中" * 30_000, "too_large"),
    ],
)
def test_json_protocol(raw, error):
    with pytest.raises(ValueError, match=error):
        service.strict_json(raw)


@pytest.mark.parametrize(
    "updates",
    [
        {"expression": "__import__('os').system('id')"},
        {"expression": "Mean($close,253)"},
        {"expression": "$vwap"},
        {"baseline_factor_ids": ["unregistered-factor"]},
    ],
)
def test_compile_and_baselines_reject_before_jobs_or_provider(settings, updates, engine):
    policy(settings)
    with pytest.raises(ValueError):
        service.submit(settings, proposal(**updates))
    assert service.list_jobs(settings) == {"items": []}
    assert not engine.calls


def test_submit_idempotency_budget_and_owner_only_receipt(settings, engine):
    policy(settings)
    first = service.submit(settings, proposal())
    assert first["status"] == "queued" and first["duplicate"] is False
    again = service.submit(settings, proposal())
    assert again["job_id"] == first["job_id"] and again["duplicate"] is True
    with pytest.raises(ValueError, match="id_conflict"):
        service.submit(settings, proposal(hypothesis="changed"))
    for number in (2, 3):
        service.submit(settings, proposal(proposal_id=f"grok-{number}"))
    with pytest.raises(ValueError, match="daily_budget_exhausted"):
        service.submit(settings, proposal(proposal_id="grok-4"))
    assert service.submit(settings, proposal())["duplicate"] is True
    assert len(service.list_jobs(settings)["items"]) == 3
    path = service._job_path(settings, first["job_id"])
    assert path.stat().st_mode & 0o777 == 0o600
    assert "DO_NOT_PRINT" not in json.dumps(first)
    assert "DO_NOT_PRINT_SOURCE_HYPOTHESIS" in path.read_text()
    assert not engine.calls


def test_budget_rolls_at_shanghai_midnight(settings, monkeypatch):
    policy(settings, max_proposals_per_day=1)
    monkeypatch.setattr(service, "_now", lambda: datetime(2026, 9, 9, 15, 59, tzinfo=UTC))
    service.submit(settings, proposal())
    monkeypatch.setattr(service, "_now", lambda: datetime(2026, 9, 9, 16, 0, tzinfo=UTC))
    assert service.submit(settings, proposal(proposal_id="next-day"))["status"] == "queued"


@pytest.mark.parametrize("limit", [None, 5])
def test_owner_daily_cap_change_preserves_jobs_and_idempotency(settings, engine, limit):
    policy(settings)
    original = service.submit(settings, proposal())
    for n in (2, 3):
        service.submit(settings, proposal(proposal_id=f"before-{n}"))
    old_bytes = service._job_path(settings, original["job_id"]).read_bytes()
    policy(settings, max_proposals_per_day=limit)
    for n in (4, 5):
        service.submit(settings, proposal(proposal_id=f"after-{n}"))
    assert service.submit(settings, proposal())["duplicate"] is True
    assert service._job_path(settings, original["job_id"]).read_bytes() == old_bytes
    if limit is None:
        assert service.submit(settings, proposal(proposal_id="after-6"))["status"] == "queued"
    else:
        with pytest.raises(ValueError, match="daily_budget_exhausted"):
            service.submit(settings, proposal(proposal_id="after-6"))
    assert not engine.calls


@pytest.mark.parametrize("field", ["proposal", "plans"])
def test_record_tampering_rejected(settings, field):
    policy(settings)
    submitted = service.submit(settings, proposal())
    path = service._job_path(settings, submitted["job_id"])
    record = json.loads(path.read_text())
    record[field] = {} if field == "proposal" else []
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="integrity_failed"):
        service.show(settings, submitted["job_id"])


def test_empty_zero_library_calls_and_no_lock_creation(settings, engine):
    policy(settings)
    assert service.run_once(settings) == {"status": "empty", "processed": 0}
    assert not (service.root(settings) / "worker.lock").exists()
    assert engine.calls == []


def test_baseline_augmented_and_only_augmented_auto_enabled(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, active_proposal(baseline_factor_ids=["momentum", "volatility"]))
    result = service.run_once(settings)
    assert result["status"] == "completed"
    assert [r["variant"] for r in result["results"]] == ["baseline", "augmented"]
    assert result["results"][0]["status"] == "validated"
    assert result["results"][1]["status"] == "paper_running"
    assert [c[0] for c in engine.calls] == ["compose", "validate", "compose", "validate", "enable"]
    for _, _, payload in [c for c in engine.calls if c[0] == "compose"]:
        assert payload["rebalance"] == "monthly" and payload["top_n"] == 5
        assert payload["commission_bps"] == 1 and payload["slippage_bps"] == 5
        assert payload["normalization"] == "rank"
        assert all(f["weight"] == 1 for f in payload["factors"])
    count = len(engine.calls)
    assert service.run_once(settings)["status"] == "empty"
    assert len(engine.calls) == count
    assert result["results"][1]["validation"]["platform_metrics"]["sharpe"] == 1.23
    assert "DO_NOT_PRINT" not in json.dumps(result)


def test_installed_activation_refuses_new_capital_to_frozen_parallel_job(
    settings, engine, monkeypatch
):
    """The installed switch, not policy.auto_enable, must withdraw legacy capital."""
    from quant_system.research import admission_activation

    policy(settings, auto_enable=True)
    submitted = service.submit(
        settings, active_proposal(baseline_factor_ids=["momentum", "volatility"])
    )
    job = service._load_job(settings, submitted["job_id"])
    assert job["admission_protocol"]["mode"] == "parallel"
    monkeypatch.setattr(
        admission_activation, "_activation_status", lambda _settings: ("valid", {"digest": "x"})
    )
    result = service.run_once(settings)
    assert result["status"] == "activation_blocked"
    assert result["results"][1]["phase"] == "activation_blocked"
    assert result["results"][1]["error"] == "activation_parallel_capital_blocked"
    assert [call[0] for call in engine.calls] == ["compose", "validate", "compose", "validate"]
    report = service.sync_report(settings)
    assert report["items"][0]["outcome"] == "activation_blocked"
    assert report["items"][0]["results"][1]["error"] == "activation_parallel_capital_blocked"


def test_no_baseline_only_one_validation_default_no_activation(settings, engine):
    policy(settings)
    service.submit(settings, proposal())
    result = service.run_once(settings)
    assert result["status"] == "completed"
    assert result["results"][0]["variant"] == "formula"
    assert [c[0] for c in engine.calls] == ["compose", "validate"]


def test_validation_failure_retained_without_retry_or_enable(settings, engine):
    policy(settings, auto_enable=True)
    engine.validation_status = "validation_failed"
    service.submit(settings, proposal())
    result = service.run_once(settings)
    assert result["status"] == "failed"
    assert result["outcome"] == "quality_rejected"
    assert service.show(settings, result["job_id"])["outcome"] == "quality_rejected"
    assert result["results"][0]["validation"]["blockers"] == ["dsr_failed"]
    assert service.run_once(settings)["status"] == "empty"
    assert [c[0] for c in engine.calls] == ["compose", "validate"]


@pytest.mark.parametrize("changed", [{"error": "provider_failed"}, {"phase": "outcome_unknown"}])
def test_operational_problem_is_not_reported_as_quality_rejection(changed):
    result = {
        "phase": "done",
        "status": "validation_failed",
        "error": None,
        "validation": {"run_id": "validation-" + "1" * 32, "blockers": ["dsr_failed"]},
        **changed,
    }
    assert service._summary({"status": "failed", "results": [result]})["outcome"] == "errored"


def test_archived_rejected_diagnostics_require_exact_hash_and_identity(settings):
    import hashlib

    strategy_id, run_id = "strategy-" + "a" * 24, "validation-" + "b" * 32
    directory = service.library._directory(settings, strategy_id) / "validations" / run_id
    directory.mkdir(parents=True)
    receipt = {
        "run_id": run_id,
        "definition_digest": "d" * 64,
        "status": "failed",
        "gates": {
            "dsr": {"value": 0.91, "n_trials": 20, "secret": "PRIVATE"},
            "cost": {"cost_bps": 6},
        },
    }
    raw = json.dumps(receipt).encode()
    path = directory / "validation.json"
    path.write_bytes(raw)
    result = {
        "strategy_id": strategy_id,
        "definition_digest": "d" * 64,
        "validation": {"run_id": run_id},
        "validation_sha256": hashlib.sha256(raw).hexdigest(),
    }
    diagnostics = service._diagnostics(settings, result)
    assert diagnostics["dsr"]["value"] == 0.91
    assert diagnostics["dsr"]["n_trials"] == 20
    assert "PRIVATE" not in json.dumps(diagnostics)
    assert diagnostics["cost"]["multiplier"] is None
    path.write_bytes(raw + b" ")
    assert service._diagnostics(settings, result)["status"] == "unavailable"
    path.write_bytes(raw)
    result["definition_digest"] = "e" * 64
    assert service._diagnostics(settings, result)["status"] == "unavailable"


def test_existing_strategy_gets_detached_evaluation_never_auto_enabled(settings, engine):
    policy(settings, auto_enable=True)
    submitted = service.submit(settings, proposal())
    plan = service._load_job(settings, submitted["job_id"])["plans"][0]
    engine.compose_strategy(settings, plan["payload"])
    engine.validate_strategy(settings, plan["strategy_id"], plan["definition_digest"])
    original = copy.deepcopy(engine.entries[plan["strategy_id"]])
    engine.calls.clear()
    result = service.run_once(settings)
    assert result["status"] == "completed"
    assert not result["results"][0]["created_by_intake"]
    assert result["results"][0]["status"] == "validated"
    assert [c[0] for c in engine.calls] == ["compose", "validate"]
    assert engine.entries[plan["strategy_id"]] == original


def test_enabling_policy_later_does_not_retroactively_authorize_queued_job(settings, engine):
    policy(settings)
    service.submit(settings, proposal())
    policy(settings, auto_enable=True)
    result = service.run_once(settings)
    assert result["results"][0]["status"] == "validated"
    assert [c[0] for c in engine.calls] == ["compose", "validate"]


def test_process_crash_after_validation_reconciles_without_second_validation(settings, engine):
    policy(settings, auto_enable=True)
    submitted = service.submit(settings, active_proposal())

    def interrupted(_settings, _entry):
        raise KeyboardInterrupt

    engine.validate_hook = interrupted
    with pytest.raises(KeyboardInterrupt):
        service.run_once(settings)
    assert service.show(settings, submitted["job_id"])["status"] == "running"
    engine.validate_hook = None
    result = service.run_once(settings)
    assert result["status"] == "completed"
    assert [c[0] for c in engine.calls] == ["compose", "validate", "compose", "validate", "enable"]


def test_interrupted_unfinished_validation_becomes_unknown_without_retry(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, proposal())

    def interrupted(_settings, entry):
        entry["status"] = "validating"
        raise KeyboardInterrupt

    engine.validate_hook = interrupted
    with pytest.raises(KeyboardInterrupt):
        service.run_once(settings)
    result = service.run_once(settings)
    assert result["status"] == "outcome_unknown"
    assert service.run_once(settings)["status"] == "outcome_unknown"
    assert [c[0] for c in engine.calls] == ["compose", "validate"]


def test_enable_exception_after_effect_reconciles_once(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, active_proposal())

    def interrupted(_settings, entry):
        entry.update(status="paper_running", sleeve_id="sleeve-real-receipt")
        raise TimeoutError("DO_NOT_PRINT_TRANSPORT_SECRET")

    engine.enable_hook = interrupted
    result = service.run_once(settings)
    assert result["status"] == "completed"
    assert result["results"][1]["sleeve_id"] == "sleeve-real-receipt"
    assert len([c for c in engine.calls if c[0] == "enable"]) == 1


def test_unconfirmed_enable_not_retried(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, active_proposal())

    def interrupted(_settings, _entry):
        raise TimeoutError("DO_NOT_PRINT_TRANSPORT_SECRET")

    engine.enable_hook = interrupted
    result = service.run_once(settings)
    assert result["status"] == "outcome_unknown"
    assert "DO_NOT_PRINT" not in json.dumps(result)
    assert service.run_once(settings)["status"] == "empty"
    assert len([c for c in engine.calls if c[0] == "enable"]) == 1


def test_pause_during_validation_stops_activation(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, proposal())

    def pause(_settings, _entry):
        path = service.root(settings) / "policy.json"
        value = json.loads(path.read_text())
        value["enabled"] = False
        path.write_text(json.dumps(value))

    engine.validate_hook = pause
    result = service.run_once(settings)
    assert result["results"][0]["status"] == "validated"
    assert [c[0] for c in engine.calls] == ["compose", "validate"]
    assert service.run_once(settings)["status"] == "paused"


def test_mismatched_pair_windows_are_not_reported_available():
    job = {
        "plans": [{"variant": "augmented", "activation_eligible": True}],
        "results": [
            {
                "variant": variant,
                "phase": "done",
                "status": "validated",
                "window": {"start": "2018-01-01", "end": end},
            }
            for variant, end in (("baseline", "2026-09-08"), ("augmented", "2026-09-09"))
        ],
    }
    service._finished_status(job)
    assert job["comparison_status"] != "available"


def test_missing_increment_objective_does_not_silently_auto_enable(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, proposal(baseline_factor_ids=["momentum"]))
    result = service.run_once(settings)
    assert result["status"] == "activation_blocked"
    assert not [call for call in engine.calls if call[0] == "enable"]


def test_legacy_available_pair_is_read_as_unpaired_without_changing_archived_bytes(settings):
    policy(settings)
    submitted = service.submit(settings, active_proposal())
    path = service._job_path(settings, submitted["job_id"])
    job = json.loads(path.read_text())
    job.update(
        status="completed",
        comparison_status="available",
        results=[
            {
                "variant": variant,
                "phase": "done",
                "status": "validated",
                "strategy_id": plan["strategy_id"],
                "definition_digest": plan["definition_digest"],
                "validation": {
                    "run_id": "validation-" + "a" * 32,
                    "start": "2018-01-01",
                    "end": end,
                },
            }
            for variant, end, plan in zip(
                ["baseline", "augmented"],
                ["2026-09-08", "2026-09-09"],
                job["plans"],
                strict=True,
            )
        ],
    )
    service._write(path, job)
    original_bytes, original_mtime = path.read_bytes(), path.stat().st_mtime_ns
    shown = service.show(settings, submitted["job_id"])
    assert shown["comparison_status"] == "legacy_unpaired"
    assert shown["comparison_status_recorded"] == "available"
    assert shown["status"] == shown["outcome"] == "completed"
    assert service.list_jobs(settings)["items"][0]["comparison_status"] == "legacy_unpaired"
    assert path.read_bytes() == original_bytes
    assert path.stat().st_mtime_ns == original_mtime


def test_new_frozen_pair_summary_preserves_available(settings, engine):
    policy(settings)
    service.submit(settings, active_proposal())
    result = service.run_once(settings)
    assert result["comparison_status"] == "available"
    assert service.show(settings, result["job_id"])["comparison_status"] == "available"


def test_pause_after_validation_is_durably_waiting_not_completed(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, proposal())

    def pause(_settings, _entry):
        path = service.root(settings) / "policy.json"
        value = json.loads(path.read_text())
        value["enabled"] = False
        path.write_text(json.dumps(value))

    engine.validate_hook = pause
    result = service.run_once(settings)
    assert result["status"] == "validated_waiting_policy"
    assert result["results"][0]["phase"] == "validated_waiting_policy"


def test_worker_processes_only_one_job_and_flock_serializes(settings, engine):
    policy(settings)
    first = service.submit(settings, proposal())
    service.submit(settings, proposal(proposal_id="second", expression="-$close/Ref($close,21)"))
    with service._lock(service.root(settings) / "worker.lock"):
        assert service.run_once(settings) == {"status": "busy", "processed": 0}
    assert engine.calls == []
    assert service.run_once(settings)["job_id"] == first["job_id"]
    assert [item["status"] for item in service.list_jobs(settings)["items"]].count("queued") == 1


def test_cli_json_receipt_suppresses_engine_noise(settings, engine, monkeypatch):
    policy(settings)
    code, submitted = invoke(["submit"], json.dumps(proposal()))
    assert code == 0 and submitted["contract"] == service.CONTRACT
    original = service.library.validate_strategy

    def noisy(*args, **kwargs):
        print("DO_NOT_PRINT_ENGINE_OUTPUT")
        return original(*args, **kwargs)

    monkeypatch.setattr(service.library, "validate_strategy", noisy)
    code, result = invoke(["run-once"])
    assert code == 0 and result["status"] == "completed"
    assert "DO_NOT_PRINT" not in json.dumps(result)
    code, shown = invoke(["show", submitted["job_id"]])
    assert code == 0 and shown["job_id"] == submitted["job_id"]
    code, invalid = invoke(["show", "../../escape"])
    assert code == 2 and invalid["error"] == "intake_job_id_invalid"


def test_competing_draft_gets_detached_result_without_ownership(settings, engine, monkeypatch):
    policy(settings, auto_enable=True)
    service.submit(settings, proposal())

    def other_creator(current_settings, definition, _origin):
        return engine._save_definition(current_settings, definition, {"type": "compose"})

    monkeypatch.setattr(service.library, "_save_definition", other_creator)
    result = service.run_once(settings)
    assert result["status"] == "completed"
    assert result["results"][0]["created_by_intake"] is False
    assert [c[0] for c in engine.calls] == ["compose", "validate"]
    assert engine.entries[result["results"][0]["strategy_id"]]["status"] == "draft"


def test_real_atomic_save_binds_origin_and_reuses_exact_prior_owner(settings, monkeypatch):
    # Real immutable storage, but no validate/provider/account operation.
    monkeypatch.setattr(service.library, "validate_strategy", lambda *_: pytest.fail("provider"))
    monkeypatch.setattr(service.library, "enable_strategy", lambda *_: pytest.fail("account"))
    policy(settings)
    one = service.submit(settings, proposal())
    plan = service._load_job(settings, one["job_id"])["plans"][0]
    entry = service._save_plan(settings, plan)
    assert service._owned(entry, plan)
    assert entry["origin"]["job_id"] == one["job_id"]
    assert entry["origin"]["end"] == plan["origin"]["end"]
    two = service.submit(settings, proposal(proposal_id="same-formula-different-source"))
    other = service._load_job(settings, two["job_id"])["plans"][0]
    reused = service._save_plan(settings, other)
    assert reused["strategy_id"] == entry["strategy_id"]
    assert not service._owned(reused, other)
    assert reused["origin"] == entry["origin"]


def test_baseline_quality_rejection_does_not_mark_successful_augmented_failed(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, active_proposal())

    def fail_baseline(_settings, entry):
        if entry["origin"]["variant"] == "baseline":
            entry["status"] = "validation_failed"
            entry["validation"]["blockers"] = ["dsr_failed"]

    engine.validate_hook = fail_baseline
    result = service.run_once(settings)
    assert result["status"] == "completed"
    assert result["comparison_status"] == "available"
    assert result["results"][0]["status"] == "validation_failed"
    assert result["results"][1]["status"] == "paper_running"


def test_pause_between_claim_and_mutation_resumes_without_lost_job(settings, engine, monkeypatch):
    policy(settings)
    submitted = service.submit(settings, proposal())
    original = service.read_policy
    calls = 0

    def pause_after_claim(current_settings):
        nonlocal calls
        calls += 1
        return service.IntakePolicy(enabled=False) if calls > 1 else original(current_settings)

    monkeypatch.setattr(service, "read_policy", pause_after_claim)
    result = service.run_once(settings)
    assert result["status"] == "paused"
    assert engine.calls == []
    monkeypatch.setattr(service, "read_policy", original)
    resumed = service.run_once(settings)
    assert resumed["job_id"] == submitted["job_id"] and resumed["status"] == "completed"


def test_reconcile_unknown_validation_never_mutates_domain_then_worker_resumes(settings, engine):
    policy(settings, auto_enable=True)
    submitted = service.submit(settings, active_proposal())

    def unknown(_settings, entry):
        entry["status"] = "validating"
        raise TimeoutError

    engine.validate_hook = unknown
    result = service.run_once(settings)
    assert result["status"] == "outcome_unknown"
    strategy_id = result["results"][0]["strategy_id"]
    # Only a bound completed evaluation can resolve this interrupted computation.
    evaluation = result["evaluation"]
    engine.validate_hook = None
    engine.validate_strategy(
        settings,
        strategy_id,
        result["results"][0]["definition_digest"],
        evaluation=evaluation,
        publish_entry=False,
    )
    count = len(engine.calls)
    reconciled = service.reconcile(settings, submitted["job_id"])
    assert reconciled["status"] == "paused"
    assert len(engine.calls) == count
    resumed = service.run_once(settings)
    assert resumed["status"] == "completed"
    assert len([c for c in engine.calls if c[0] == "enable"]) == 1


def test_unknown_enable_survives_crash_before_final_job_write(settings, engine, monkeypatch):
    policy(settings, auto_enable=True)
    submitted = service.submit(settings, active_proposal())

    def uncertain(_settings, _entry):
        raise TimeoutError

    engine.enable_hook = uncertain
    original = service._persist

    def crash_after_unknown(current_settings, job, event):
        original(current_settings, job, event)
        if event.endswith(":activation_unconfirmed"):
            raise KeyboardInterrupt

    monkeypatch.setattr(service, "_persist", crash_after_unknown)
    with pytest.raises(KeyboardInterrupt):
        service.run_once(settings)
    assert service.show(settings, submitted["job_id"])["status"] == "running"
    monkeypatch.setattr(service, "_persist", original)
    assert service.run_once(settings)["status"] == "outcome_unknown"
    assert len([c for c in engine.calls if c[0] == "enable"]) == 1
    assert service.reconcile(settings, submitted["job_id"])["status"] == "outcome_unknown"
    assert len([c for c in engine.calls if c[0] == "enable"]) == 1


def test_cli_schema_errors_locate_fields_without_secret_values_or_messages(settings, engine):
    policy(settings)
    invalid = proposal(
        expression={"value": "DO_NOT_PRINT_FORMULA_SECRET"},
        source_urls=["http://DO_NOT_PRINT_URL_SECRET.example"],
        retrieved_at="DO_NOT_PRINT_TIMESTAMP_SECRET",
        DO_NOT_PRINT_EXTRA_FIELD_SECRET="DO_NOT_PRINT_EXTRA_VALUE_SECRET",
    )
    del invalid["published_at"]
    code, result = invoke(["submit"], json.dumps(invalid))
    assert code == 2 and result["error"] == "intake_schema_invalid"
    errors = {tuple(item["path"]): item for item in result["validation_errors"]}
    assert errors[("published_at",)] == {
        "path": ["published_at"],
        "type": "missing",
        "code": "intake_schema_missing",
    }
    assert errors[("expression",)]["type"] == "string_type"
    assert errors[("source_urls",)]["code"] == "intake_source_url_invalid"
    assert errors[("retrieved_at",)]["code"] == "intake_schema_value_error"
    assert errors[("<unknown_field>",)]["type"] == "extra_forbidden"
    assert all(set(item) == {"path", "type", "code"} for item in errors.values())
    assert "DO_NOT_PRINT" not in json.dumps(result)


def test_two_jobs_reuse_rules_but_not_old_evaluation_window(settings, engine, monkeypatch):
    policy(settings)
    calls = []

    def collect(_settings, symbols, end):
        calls.append(end)
        return pd.DataFrame({"timestamp": [end], "symbol": ["SPY"], "close": [100.0]}), {}

    monkeypatch.setattr(service.library, "_collect_prices", collect)
    monkeypatch.setattr(service, "_now", lambda: datetime(2026, 9, 9, 8, tzinfo=UTC))
    service.submit(settings, active_proposal())
    first = service.run_once(settings)
    first_archives = copy.deepcopy(engine.archives)
    monkeypatch.setattr(service, "_now", lambda: datetime(2026, 9, 10, 8, tzinfo=UTC))
    service.submit(
        settings, active_proposal(proposal_id="next-source", expression="Mean($close,20)/$close")
    )
    second = service.run_once(settings)
    assert calls == ["2026-09-08", "2026-09-09"]
    assert first["results"][0]["strategy_id"] == second["results"][0]["strategy_id"]
    assert first["evaluation"]["evaluation_id"] != second["evaluation"]["evaluation_id"]
    assert second["comparison_status"] == "available"
    for result in second["results"]:
        assert result["window"]["end"] == "2026-09-09"
        assert result["evaluation"] == second["evaluation"]
    assert all(engine.archives[key] == value for key, value in first_archives.items())


def test_paused_validated_pair_resumes_same_job_without_revalidation(settings, engine):
    policy(settings, auto_enable=True)
    submitted = service.submit(settings, active_proposal())

    def pause_augmented(_settings, entry):
        if entry["origin"]["variant"] == "augmented":
            path = service.root(settings) / "policy.json"
            value = json.loads(path.read_text())
            value["enabled"] = False
            path.write_text(json.dumps(value))

    engine.validate_hook = pause_augmented
    waiting = service.run_once(settings)
    assert waiting["status"] == "validated_waiting_policy"
    assert not [call for call in engine.calls if call[0] == "enable"]
    policy(settings, auto_enable=True)
    engine.validate_hook = None
    resumed = service.run_once(settings)
    assert resumed["job_id"] == submitted["job_id"]
    assert resumed["status"] == "completed"
    assert len([call for call in engine.calls if call[0] == "validate"]) == 2
    assert len([call for call in engine.calls if call[0] == "enable"]) == 1
    assert resumed["evaluation"] == waiting["evaluation"]


def test_paused_increment_cannot_enable_a_newer_unpaired_validation(settings, engine):
    policy(settings, auto_enable=True)
    service.submit(settings, active_proposal())

    def pause_augmented(_settings, entry):
        if entry["origin"]["variant"] == "augmented":
            path = service.root(settings) / "policy.json"
            value = json.loads(path.read_text())
            value["enabled"] = False
            path.write_text(json.dumps(value))

    engine.validate_hook = pause_augmented
    waiting = service.run_once(settings)
    assert waiting["status"] == "validated_waiting_policy"
    original = waiting["results"][1]
    current = engine.entries[original["strategy_id"]]
    current.update(validation_sha256="3" * 64, candidate_id="newer-unpaired-candidate")
    current["evaluation"] = {**waiting["evaluation"], "evaluation_id": "different"}
    enabled = []
    engine.enable_hook = lambda _settings, entry: enabled.append(entry["validation_sha256"])
    policy(settings, auto_enable=True)
    resumed = service.run_once(settings)
    assert enabled == []
    assert resumed["status"] == "activation_blocked"
    assert resumed["results"][1]["validation_sha256"] == original["validation_sha256"]


def test_known_dead_computation_reuses_frozen_input_and_same_job(settings, engine):
    policy(settings, auto_enable=True)
    submitted = service.submit(settings, active_proposal())

    def interrupt_augmented(_settings, entry):
        if entry["origin"]["variant"] == "augmented":
            entry["status"] = "validating"
            raise KeyboardInterrupt

    engine.validate_hook = interrupt_augmented
    with pytest.raises(KeyboardInterrupt):
        service.run_once(settings)
    original = service.show(settings, submitted["job_id"])
    engine.recovery_ready = True
    engine.validate_hook = None
    resumed = service.run_once(settings)
    assert resumed["status"] == "completed"
    assert resumed["job_id"] == submitted["job_id"]
    assert resumed["evaluation"] == original["evaluation"]
    assert len([call for call in engine.calls if call[0] == "validate"]) == 3
    assert len([call for call in engine.calls if call[0] == "enable"]) == 1


def test_failed_increment_stays_candidate_and_cannot_change_objective_after_results(
    settings, engine
):
    policy(settings, auto_enable=True)
    body = active_proposal(
        increment_objective={"metric": "sharpe", "minimum_improvement": 0.5, "max_regressions": {}}
    )
    service.submit(settings, body)
    outcome = service.run_once(settings)
    assert outcome["status"] == "activation_blocked"
    assert outcome["increment"]["status"] == "failed"
    assert outcome["results"][1]["status"] == "validated"
    assert not [call for call in engine.calls if call[0] == "enable"]
    body["increment_objective"]["minimum_improvement"] = 0.1
    with pytest.raises(ValueError, match="proposal_id_conflict"):
        service.submit(settings, body)


def test_strategy_spec_preserves_explicit_rules_in_both_variants(settings):
    policy(settings)
    submitted = service.submit(
        settings,
        active_proposal(
            strategy_spec={
                "symbols": ["SPY", "QQQ", "TLT"],
                "benchmark_symbol": "QQQ",
                "rebalance": "weekly",
                "top_n": 2,
                "normalization": "zscore",
                "target_gross_exposure": 0.6,
                "max_weight_per_symbol": 0.3,
                "factor_weights": {"momentum": 0.5},
            }
        ),
    )
    plans = service._load_job(settings, submitted["job_id"])["plans"]
    for plan in plans:
        definition = StrategyDefinition(history_start="2015-01-01", **plan["payload"])
        assert definition.symbols == ("SPY", "QQQ", "TLT")
        assert definition.rebalance == "weekly" and definition.top_n == 2
        assert definition.normalization == "zscore" and definition.target_gross_exposure == 0.6
        assert definition.max_weight_per_symbol == 0.3 and definition.factors[0].weight == 0.5
        assert definition.commission_bps == 1 and definition.slippage_bps == 5


@pytest.mark.parametrize(
    "spec",
    [
        {"rebalance": "intraday"},
        {"symbols": ["HK.00700"]},
        {"commission_bps": 0},
        {"whole_share_orders": True},
    ],
)
def test_strategy_spec_rejects_unsupported_before_enqueue(settings, engine, spec):
    policy(settings)
    with pytest.raises(ValueError):
        service.submit(settings, proposal(strategy_spec=spec))
    assert service.list_jobs(settings) == {"items": []}
    assert not engine.calls and service.list_jobs(settings) == {"items": []}


def test_capabilities_exposes_universe_and_data_availability_additively(settings, monkeypatch):
    # chdir keeps the default relative equity-cache path inside tmp space so the
    # degradation assertions hold regardless of the invoking checkout's data dir.
    monkeypatch.chdir(settings.data.data_dir)
    caps = service.capabilities(settings)
    universe = caps["universe"]
    assert universe["profile_id"] == "stocks_momentum_12_2"
    assert universe["membership_mode"] == "static_snapshot"
    assert universe["symbol_source"] == "static_registry_snapshot_not_index_membership"
    assert universe["symbols"] == caps["scope"]["symbols"]
    assert universe["benchmark_symbol"] == caps["scope"]["benchmark_symbol"] == "SPY"
    limits = universe["strategy_spec_limits"]
    assert limits["symbols_max"] == 60
    assert limits["top_n_max"] == 60
    assert limits["rebalance_allowed"] == ["daily", "weekly", "monthly"]
    assert limits["normalization_allowed"] == ["rank", "zscore"]
    assert limits["selection_allowed"] == ["top", "positive_top", "bottom"]
    assert limits["defaults_when_omitted"]["top_n"] == 5
    assert universe["limitations"]
    data_availability = caps["data_availability"]
    assert data_availability["price_data"]["provider"] == "futu"
    assert data_availability["price_data"]["interval"] == "1d"
    assert data_availability["price_data"]["price_adjustment"] == "qfq"
    assert data_availability["price_data"]["fetch_start"] == "2015-01-01"
    assert (
        data_availability["price_data"]["serving_semantics"]
        == "exact_request_verified_snapshots_reused_else_fetched"
    )
    assert (
        data_availability["price_data"]["coverage_semantics"]
        == "served_ranges_are_locally_verified_not_provider_promises"
    )
    assert data_availability["status"] == "unavailable"
    assert data_availability["reason"] == "equity_bar_cache_not_initialized"
    assert data_availability["served_symbol_ranges"] == []
    assert data_availability["provider_readiness"] == []
    assert data_availability["as_of"]
    # Red-line regression locks: additive keys must not move existing scope values.
    scope = caps["scope"]
    assert scope["dsr_min"] == 0.95
    assert scope["max_hung_correlation"] == 0.7
    assert scope["commission_bps"] == 1
    assert scope["slippage_bps"] == 5
    assert len(scope["symbols"]) == 24


def test_capabilities_served_ranges_from_equity_bar_cache(settings):
    import duckdb

    cache_path = settings.data.data_dir / "futu_equity_bars.duckdb"
    settings.data.duckdb_path = settings.data.data_dir / "quant_system.duckdb"
    connection = duckdb.connect(str(cache_path))
    try:
        connection.execute(
            """
            CREATE TABLE equity_bars (
                provider VARCHAR NOT NULL,
                symbol VARCHAR NOT NULL,
                interval VARCHAR NOT NULL,
                adjustment VARCHAR NOT NULL,
                session_date VARCHAR NOT NULL,
                timestamp VARCHAR NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                volume DOUBLE NOT NULL,
                event_ts VARCHAR NOT NULL,
                knowledge_ts VARCHAR NOT NULL,
                fetched_at VARCHAR NOT NULL,
                PRIMARY KEY (
                    provider, symbol, interval, adjustment, session_date
                )
            )
            """
        )
        connection.executemany(
            "INSERT INTO equity_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "futu",
                    "AAPL",
                    "1d",
                    "qfq",
                    "2020-01-02",
                    "2020-01-02T09:30:00-05:00",
                    300.0,
                    301.0,
                    299.0,
                    300.5,
                    1000.0,
                    "2020-01-02T09:30:00-05:00",
                    "2020-01-02T09:30:00-05:00",
                    "2026-09-10T00:00:00Z",
                ),
                (
                    "futu",
                    "NOT_IN_UNIVERSE",
                    "1d",
                    "qfq",
                    "2020-01-02",
                    "2020-01-02T09:30:00-05:00",
                    100.0,
                    101.0,
                    99.0,
                    100.5,
                    2000.0,
                    "2020-01-02T09:30:00-05:00",
                    "2020-01-02T09:30:00-05:00",
                    "2026-09-10T00:00:00Z",
                ),
            ],
        )
    finally:
        connection.close()

    caps = service.capabilities(settings)
    data_availability = caps["data_availability"]
    assert data_availability["status"] == "available"
    served = {row["symbol"]: row for row in data_availability["served_symbol_ranges"]}
    assert list(served) == ["AAPL"]
    assert served["AAPL"]["first_served_date"] == "2020-01-02"
    assert served["AAPL"]["last_served_date"] == "2020-01-02"
    assert served["AAPL"]["sessions"] == 1
    assert "NOT_IN_UNIVERSE" not in served


def test_cli_capabilities_passthrough_includes_new_keys(settings):
    code, payload = invoke(["capabilities"])
    assert code == 0
    assert payload["ok"] is True
    assert payload["universe"]["profile_id"] == "stocks_momentum_12_2"
    assert "price_data" in payload["data_availability"]
    assert "served_symbol_ranges" in payload["data_availability"]
