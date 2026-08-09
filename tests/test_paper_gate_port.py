from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from quant_system.hermes.paper_gate_port import (
    PaperGateCliSettings,
    PaperGatePortError,
    SubprocessPaperGatePort,
    _validate_receipt,
)


def test_subprocess_port_uses_fixed_module_and_keeps_note_off_argv_and_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    platform_root = tmp_path / "platform"
    quant_system = platform_root / "ai-quant" / "bin" / "quant-system"
    quant_system.parent.mkdir(parents=True)
    quant_system.write_text("", encoding="utf-8")
    seen: dict[str, object] = {}
    runner_calls = 0
    response_session_ref = "session:paper-session-1"
    monkeypatch.setenv("FUTU_API_SECRET", "must-not-reach-paper-gate")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-paper-gate")
    monkeypatch.setenv("HQA_PROVIDER_API_SECRET", "must-not-reach-paper-gate")
    monkeypatch.setenv("HQA_WORKFLOW_OWNER_USER_ID", "local-owner-test")

    def runner(argv, **kwargs):
        nonlocal runner_calls
        runner_calls += 1
        seen["argv"] = list(argv)
        seen["input"] = kwargs["input"]
        seen["env"] = dict(kwargs["env"])
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(
                json.dumps(
                    {
                        "ok": True,
                        "managed_session_ref": response_session_ref,
                        "operation_id": "gate2-action-1",
                        "task_ref": "task:paper-task-1",
                        "gate_ref": "gate:paper-gate-1",
                        "gate1_confirmation_id": "gate1-" + "1" * 32,
                        "reviewed_source_digest": "1" * 64,
                        "attempt_ref": "attempt:paper-2",
                        "task_version": 9,
                        "candidate_id": "factor-paper-1",
                        "candidate_digest": "2" * 64,
                        "decision": "approve",
                        "registration": "manual_required",
                        "review_note_digest": hashlib.sha256(
                            b"Human reviewed exact candidate source."
                        ).hexdigest(),
                        "hqa_receipt_ref": "hqa-paper-gate:gate2-action-1",
                        "hqa_receipt_digest": "3" * 64,
                    }
                ).encode("utf-8")
                + b"\n"
            ),
            stderr=b"",
        )

    port = SubprocessPaperGatePort(
        cli_settings=PaperGateCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            platform_root=platform_root,
            timeout_seconds=15,
        ),
        runner=runner,
    )
    note = "Human reviewed exact candidate source."
    request = {
        "managed_session_ref": "session:paper-session-1",
        "operation_id": "gate2-action-1",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 8,
        "gate_ref": "gate:paper-gate-1",
        "gate1_confirmation_id": "gate1-" + "1" * 32,
        "reviewed_source_digest": "1" * 64,
        "candidate_id": "factor-paper-1",
        "expected_digest": "2" * 64,
        "expected_status": "pending",
        "note": note,
    }
    result = port.execute(
        "approve",
        request,
    )

    assert result["candidate_id"] == "factor-paper-1"
    assert result["managed_session_ref"] == "session:paper-session-1"
    assert seen["argv"] == [
        str(python),
        "-m",
        "hqa.paper_gate_cli",
        "approve",
    ]
    assert note in seen["input"].decode("utf-8")  # type: ignore[union-attr]
    assert (
        json.loads(seen["input"])["managed_session_ref"]  # type: ignore[arg-type]
        == "session:paper-session-1"
    )
    assert note not in " ".join(seen["argv"])  # type: ignore[arg-type]
    assert note not in json.dumps(seen["env"], sort_keys=True)
    assert "FUTU_API_SECRET" not in seen["env"]  # type: ignore[operator]
    assert "DATABASE_URL" not in seen["env"]  # type: ignore[operator]
    assert "HQA_PROVIDER_API_SECRET" not in seen["env"]  # type: ignore[operator]
    env = seen["env"]
    assert env["PYTHONPATH"].split(":")[0] == str(hqa_root)  # type: ignore[index]
    assert env["HQA_AIQP_DIR"] == str(platform_root)  # type: ignore[index]
    assert env["HQA_QUANT_SYSTEM_BIN"] == str(quant_system)  # type: ignore[index]
    assert env["HQA_WORKFLOW_OWNER_USER_ID"] == "local-owner-test"  # type: ignore[index]

    response_session_ref = "web_this-is-a-hermes-session-id"
    with pytest.raises(
        PaperGatePortError,
        match="substituted receipt identity",
    ):
        port.execute("approve", request)

    invalid_request = dict(request)
    invalid_request["managed_session_ref"] = "web_this-is-a-hermes-session-id"
    before = runner_calls
    with pytest.raises(
        PaperGatePortError,
        match="exact managed Session reference",
    ):
        port.execute("approve", invalid_request)
    assert runner_calls == before


def test_promote_receipt_requires_two_distinct_workflow_events() -> None:
    request = {
        "managed_session_ref": "session:paper-session-1",
        "operation_id": "gate3-action-1",
        "task_ref": "task:paper-task-1",
        "expected_task_version": 8,
        "attempt_ref": "attempt:paper-research",
        "run_ref": "run:paper-research",
        "gate_ref": "gate:paper-gate-3",
        "candidate_id": "factor-paper-1",
        "expected_digest": "2" * 64,
        "final_backtest_receipt_id": "backtest-" + "3" * 32,
        "base_commit": "4" * 40,
    }
    document = {
        "ok": True,
        "managed_session_ref": request["managed_session_ref"],
        "operation_id": request["operation_id"],
        "hqa_receipt_ref": "hqa-paper-gate:gate3-action-1",
        "hqa_receipt_digest": "5" * 64,
        "task_ref": request["task_ref"],
        "task_version": 10,
        "attempt_ref": request["attempt_ref"],
        "workflow_gate_resolution_event_id": "event:" + "6" * 64,
        "workflow_gate3_event_id": "event:" + "7" * 64,
        "run_ref": request["run_ref"],
        "gate_ref": request["gate_ref"],
        "candidate_id": request["candidate_id"],
        "candidate_digest": request["expected_digest"],
        "final_backtest_receipt_id": request["final_backtest_receipt_id"],
        "base_commit": request["base_commit"],
        "promotion_id": "promo-" + "8" * 32 + "-r10",
        "promotion_status": "awaiting_human_commit",
        "worktree": "/tmp/paper-review",
        "patch": "/tmp/paper-review.patch",
        "manifest": "/tmp/paper-review.json",
        "human_git_commit_required": True,
        "auto_commit": False,
    }
    assert _validate_receipt("promote", request, document)["task_version"] == 10

    single_event_version = {**document, "task_version": 9}
    with pytest.raises(PaperGatePortError, match="does not match"):
        _validate_receipt("promote", request, single_event_version)

    reused_event = {
        **document,
        "workflow_gate3_event_id": document["workflow_gate_resolution_event_id"],
    }
    with pytest.raises(PaperGatePortError, match="does not match"):
        _validate_receipt("promote", request, reused_event)
