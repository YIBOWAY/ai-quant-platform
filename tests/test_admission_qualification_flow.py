"""Fixed automatic producer wiring; program mocks are explicit and never enter production."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.research import admission_qualification_flow as flow
from tests import test_admission_v2 as core


@pytest.fixture
def context(tmp_path):
    from tests.test_current_consumer_qualification import complete_context

    return complete_context(tmp_path)


def recipes(settings, **changes):
    value = {
        "schema": flow.SCHEMA,
        "enabled": True,
        "revision": "sealed-v1",
        "recipes": {
            "data": {"dataset": "sealed", "source_root": "/sealed-source"},
            "review": {"root": "/sealed-review"},
            "consumer": {
                "current_control_rule": "current-common-quality-control-v1",
                "random_root": "/sealed-random",
                "data_root": "/sealed-family",
                "peer_snapshot_path": "/sealed-peers",
            },
        },
        **changes,
    }
    path = flow._root(settings) / "recipes.json"
    core.write(path, value)
    path.chmod(0o600)
    return path


def program(monkeypatch, *, fail=None, transient=False):
    from quant_system.research import admission_qualifier as qualifier

    calls = []
    monkeypatch.setattr(
        qualifier, "inspect_data_binding", lambda *a, **k: {"input_digest": "a" * 64}
    )

    def register(settings, *, kind, **kwargs):
        calls.append(kind)
        return {
            "descriptor": {"path": "/sealed/" + kind, "sha256": kind, "registration_id": kind},
            "verification": {
                "status": "not_evaluated" if fail == kind else "passed",
                "reason": "sealed-unsupported" if fail == kind else None,
                "details": {"retryable": transient},
            },
        }

    monkeypatch.setattr(qualifier, "register_qualification", register)
    return calls


def test_no_owner_recipe_is_read_only(tmp_path):
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    assert (
        flow.ensure_qualifications(settings, validation_path=tmp_path / "unused", protocol={})[
            "status"
        ]
        == "not_configured"
    )
    assert list(tmp_path.iterdir()) == []


def test_success_uses_fixed_program_and_merges_catalog_once(context, monkeypatch):
    settings = context["settings"]
    recipes(settings)
    calls = program(monkeypatch)
    root = flow._root(settings)
    core.write(
        root / "qualifications.json",
        {
            "schema": "admission_qualification_index/v1",
            "entries": {"old": {"review": {"sha256": "old"}}},
        },
    )
    (root / "qualifications.json").chmod(0o600)
    args = dict(validation_path=context["validation_path"], protocol=context["protocol"])
    first = flow.ensure_qualifications(settings, **args)
    again = flow.ensure_qualifications(settings, **args)
    assert first["status"] == "registered" and again["cached"] is True
    assert calls == ["data", "review", "consumer"]
    assert set(json.loads((root / "qualifications.json").read_text())["entries"]) == {
        "old",
        "a" * 64,
    }
    assert not (settings.data.data_dir / "api_runs").exists()


def test_failure_is_recorded_and_same_input_does_not_rerun_heavy_checks(context, monkeypatch):
    settings = context["settings"]
    path = recipes(settings)
    calls = program(monkeypatch, fail="data")
    args = dict(validation_path=context["validation_path"], protocol=context["protocol"])
    first = flow.ensure_qualifications(settings, **args)
    again = flow.ensure_qualifications(settings, **args)
    assert first["status"] == "not_evaluated" and first["reason"] == "sealed-unsupported"
    assert again["cached"] and calls == ["data"]
    assert len(list((flow._root(settings) / "attempts").glob("*.json"))) == 1
    value = json.loads(path.read_text())
    value["revision"] = "sealed-v2"
    path.write_text(json.dumps(value))
    assert flow.ensure_qualifications(settings, **args)["cached"] is False
    assert calls == ["data", "data"]


def test_model_claims_or_commands_are_not_recipe_fields(context, monkeypatch):
    path = recipes(context["settings"])
    value = json.loads(path.read_text())
    value["recipes"]["consumer"]["script"] = "/tmp/arbitrary.py"
    path.write_text(json.dumps(value))
    calls = program(monkeypatch)
    with pytest.raises(ValueError, match="consumer_recipe_invalid"):
        flow.ensure_qualifications(
            context["settings"],
            validation_path=context["validation_path"],
            protocol=context["protocol"],
        )
    assert calls == []


def test_transient_failure_retries_once_when_backoff_expires_without_engine(context, monkeypatch):
    settings = context["settings"]
    recipes(settings)
    now = [1000.0]
    monkeypatch.setattr(flow.time, "time", lambda: now[0])
    calls = program(monkeypatch, fail="consumer", transient=True)
    args = dict(validation_path=context["validation_path"], protocol=context["protocol"])
    first = flow.ensure_qualifications(settings, **args)
    assert first["retryable"] and first["next_retry_at"] == 1030
    assert flow.ensure_qualifications(settings, **args)["cached"] and len(calls) == 3
    assert not flow.should_retry(settings, **args, previous=first)
    now[0] = 1031
    assert flow.should_retry(settings, **args, previous=first)
    second = flow.ensure_qualifications(settings, **args)
    assert second["attempt_number"] == 2 and second["next_retry_at"] == 1151
    assert len(calls) == 6
    assert (
        len(list((flow._root(settings) / "attempts/history" / first["attempt_id"]).glob("*.json")))
        == 2
    )
    assert second["backtests_run"] == second["new_trials"] == 0


def test_busy_attempt_is_retryable_and_does_not_wait_or_run_producer(context, monkeypatch):
    from quant_system.research.external_intake import _lock, _private_directory

    settings = context["settings"]
    recipes(settings)
    calls = program(monkeypatch)
    configuration = flow.read_recipes(settings)
    identity, _ = flow._input_key(
        settings, context["validation_path"], context["protocol"], configuration
    )
    attempts = flow._root(settings) / "attempts"
    _private_directory(attempts)
    with _lock(attempts / (identity + ".lock")):
        result = flow.ensure_qualifications(
            settings, validation_path=context["validation_path"], protocol=context["protocol"]
        )
    assert result["status"] == "not_evaluated" and result["retryable"]
    assert result["reason"] == "qualification_production_busy"
    assert result["next_retry_at"] > flow.time.time()
    assert calls == []
    assert not flow.should_retry(
        settings,
        validation_path=context["validation_path"],
        protocol=context["protocol"],
        previous=result,
    )


def test_native_validation_auto_attempt_and_refresh_do_not_repeat_engine_or_failed_checks(
    context, monkeypatch
):
    from quant_system.research import external_intake as intake
    from quant_system.research import strategy_library as library
    from tests.test_admission_v2_consumers import consumer

    recipes(context["settings"])
    producer_calls = program(monkeypatch, fail="data")
    settings, _, job, entry, engine_calls = consumer(context, monkeypatch, "authoritative")
    assert job["status"] == "admission_waiting"
    # This artificial native-engine boundary now supplies its definition but
    # still has no original fills. Verify that exact fixture gap before checking
    # the real guard; do not weaken this to accepting any rejection reason.
    run = Path(entry["admission_v2"]["path"]).parent
    original = json.loads((run / "platform-result.json").read_text())
    assert original["definition"] == entry["definition"]
    assert original["definition_digest"] == entry["definition_digest"]
    assert "trades" not in original
    assert entry["qualification_flow"]["reason"] == "current_control_cost_fills_unavailable"
    assert producer_calls == [] and engine_calls == ["engine"]
    owner = intake._load_job(settings, job["job_id"])
    refreshed = library.refresh_admission(
        settings,
        entry["strategy_id"],
        entry["evaluation"],
        owner["admission_protocol"],
        publish_entry=True,
    )
    assert refreshed["qualification_flow"]["cached"]
    assert producer_calls == [] and engine_calls == ["engine"]
    assert intake.run_once(settings)["status"] == "empty"


def test_atomic_catalog_failure_is_not_registered_and_remains_retryable(context, monkeypatch):
    recipes(context["settings"])
    calls = program(monkeypatch)

    def busy(*args):
        raise BlockingIOError("sealed catalog lock busy")

    monkeypatch.setattr(flow, "_publish", busy)
    result = flow.ensure_qualifications(
        context["settings"],
        validation_path=context["validation_path"],
        protocol=context["protocol"],
    )
    assert result["status"] == "not_evaluated" and result["retryable"]
    assert calls == ["data", "review", "consumer"]


def test_disclosed_crash_after_immutable_history_recovers_memo_without_rerunning(
    context, monkeypatch
):
    from quant_system.research import external_intake as intake

    recipes(context["settings"])
    calls = program(monkeypatch, fail="data")
    original, failed = intake._write, []

    def fail_once(path, value):
        if path.parent.name == "attempts" and not failed:
            failed.append(str(path))
            raise OSError("crash after immutable history before memo")
        return original(path, value)

    monkeypatch.setattr(intake, "_write", fail_once)
    args = dict(validation_path=context["validation_path"], protocol=context["protocol"])
    with pytest.raises(OSError, match="after immutable history"):
        flow.ensure_qualifications(context["settings"], **args)
    recovered = flow.ensure_qualifications(context["settings"], **args)
    again = flow.ensure_qualifications(context["settings"], **args)
    assert recovered["cached"] and again["cached"] and calls == ["data"]
    assert len(list((flow._root(context["settings"]) / "attempts").glob("*.json"))) == 1
    assert len(list((flow._root(context["settings"]) / "attempts/history").glob("*/*.json"))) == 1
