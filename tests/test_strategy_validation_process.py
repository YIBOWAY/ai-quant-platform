"""Sealed process results: no real validation, provider, subprocess, or account."""

import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from quant_system.api.routes import strategy_library as route
from quant_system.research import strategy_validation_process as process

IDENTIFIER = "strategy-" + "a" * 24
DIGEST = "b" * 64


@pytest.fixture
def state(tmp_path, monkeypatch):
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path / "isolated-data"))
    directory = process.service._directory(settings, IDENTIFIER)
    directory.mkdir(parents=True)
    entry = {"strategy_id": IDENTIFIER, "definition_digest": DIGEST, "status": "validating"}
    (directory / "entry.json").write_text(json.dumps(entry))
    monkeypatch.setattr(process, "_current_is_python311", lambda: False)
    monkeypatch.setattr(process.os, "access", lambda *_a: True)
    monkeypatch.setattr(process.subprocess, "run", lambda *_a, **_k: pytest.fail("real subprocess"))
    return settings, directory, entry


def test_python311_uses_existing_domain_directly(state, monkeypatch):
    settings, _, entry = state
    monkeypatch.setattr(process, "_current_is_python311", lambda: True)
    calls = []
    monkeypatch.setattr(
        process.service, "validate_strategy", lambda *args: calls.append(args) or entry
    )
    assert process.validate_in_research_runtime(settings, IDENTIFIER, DIGEST) == entry
    assert calls == [(settings, IDENTIFIER, DIGEST)]


@pytest.mark.parametrize("override", [None, "/sealed/research-python"])
def test_other_python_pins_worker_version_exact_identity_and_data_directory(
    state, monkeypatch, override
):
    settings, directory, entry = state
    if override is None:
        monkeypatch.delenv("QS_D34_WORKER_PYTHON", raising=False)
    else:
        monkeypatch.setenv("QS_D34_WORKER_PYTHON", override)
    monkeypatch.setenv("SEALED_INHERITED_SETTING", "preserved")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "-m" in argv:
            (directory / "entry.json").write_text(json.dumps({**entry, "status": "validated"}))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(process.subprocess, "run", run)
    result = process.validate_in_research_runtime(settings, IDENTIFIER, DIGEST)
    assert result["status"] == "validated"
    assert len(calls) == 2
    python = override or str(process._ROOT / ".venv/bin/python")
    assert calls[0][0][:4] == [python, "-I", "-B", "-c"]
    assert "(3, 11)" in calls[0][0][-1]
    argv, kwargs = calls[1]
    assert argv == [
        python,
        "-B",
        "-m",
        "quant_system.research.strategy_library_cli",
        "validate",
        IDENTIFIER,
        "--expected-digest",
        DIGEST,
    ]
    assert kwargs["env"]["QS_DATA_DIR"] == str(settings.data.data_dir.resolve())
    assert kwargs["env"]["PYTHONPATH"] == str(process._ROOT / "src")
    assert kwargs["env"]["SEALED_INHERITED_SETTING"] == "preserved"
    assert kwargs["env"]["QS_DATABASE_AUTO_MIGRATE"] == "false"
    assert kwargs["stdout"] == kwargs["stderr"] == kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["cwd"] == process._ROOT and kwargs["timeout"] == 600


@pytest.mark.parametrize(
    "failure,expected",
    [
        ("version", "strategy_validation_python_version_invalid"),
        ("timeout", "strategy_validation_process_timeout"),
        ("exit", "strategy_validation_process_failed"),
        ("incomplete", "strategy_validation_process_incomplete"),
    ],
)
def test_failed_process_releases_api_lock_and_saves_small_failure_receipt(
    state, monkeypatch, failure, expected
):
    settings, directory, _ = state
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if "-m" not in argv:
            return SimpleNamespace(returncode=1 if failure == "version" else 0)
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 600, output="DO_NOT_EMIT_TOKEN")
        return SimpleNamespace(returncode=2 if failure == "exit" else 0)

    monkeypatch.setattr(process.subprocess, "run", run)
    monkeypatch.setattr(route, "_ACTIVE", IDENTIFIER)
    assert route._LOCK.acquire(blocking=False)
    route._validate(settings, IDENTIFIER, DIGEST)
    assert route._ACTIVE is None and not route._LOCK.locked()
    assert len(calls) == (1 if failure == "version" else 2)
    entry = json.loads((directory / "entry.json").read_text())
    assert entry["status"] == "validation_failed" and entry["error"] == expected
    receipts = list((directory / "failures").glob("process-*.json"))
    assert len(receipts) == 1 and "DO_NOT_EMIT_TOKEN" not in receipts[0].read_text()
    receipt = json.loads(receipts[0].read_text())
    assert receipt["definition_digest"] == DIGEST and receipt["strategy_id"] == IDENTIFIER


def test_domain_gate_failure_is_preserved_without_process_reclassification(state, monkeypatch):
    settings, directory, entry = state

    def run(argv, **_kwargs):
        if "-m" in argv:
            (directory / "entry.json").write_text(
                json.dumps(
                    {
                        **entry,
                        "status": "validation_failed",
                        "validation": {"blockers": ["dsr_failed"]},
                    }
                )
            )
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(process.subprocess, "run", run)
    result = process.validate_in_research_runtime(settings, IDENTIFIER, DIGEST)
    assert result["validation"]["blockers"] == ["dsr_failed"]
    assert not (directory / "failures").exists()


def test_api_keeps_background_acceptance_and_defers_calculation(state, monkeypatch):
    settings, _, entry = state
    monkeypatch.setattr(route.service, "read_strategy", lambda *_a: {**entry, "status": "draft"})
    tasks = BackgroundTasks()
    try:
        result = route.validate_strategy(
            IDENTIFIER,
            route.StrategyAction(expected_digest=DIGEST),
            settings,
            tasks,
        )
        assert result["status"] == "validating" and len(tasks.tasks) == 1
        assert tasks.tasks[0].func is route._validate
        assert tasks.tasks[0].args == (settings, IDENTIFIER, DIGEST)
    finally:
        route._ACTIVE = None
        if route._LOCK.locked():
            route._LOCK.release()
