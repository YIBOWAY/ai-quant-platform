from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from typer.testing import CliRunner

from quant_system.hermes import paper_gate_cli
from quant_system.hermes.paper_gate_authority import PaperGateNotFound
from quant_system.hermes.paper_run_attestation import (
    PaperRunAttestationUnavailable,
)

runner = CliRunner()
COMMAND_ID = "11111111-1111-4111-8111-111111111111"


@dataclass
class _Record:
    gate_id: str

    def to_operator_dict(self) -> dict[str, object]:
        return {
            "command_id": COMMAND_ID,
            "command_ref": f"command:{COMMAND_ID}",
            "gate_id": self.gate_id,
            "platform_session_id": "platform-session",
            "registered_expected_status": None,
            "reviewed_commit": None,
            "workspace_id": "workspace-root",
        }


@dataclass
class _CompletionRecord:
    gate_id: str

    def to_operator_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "hqa_completion_receipt_ref": ("hqa-paper-completion:" + "a" * 32),
            "status": "completed",
            "workspace_id": "workspace-root",
        }


class _Authority:
    registered: list[object] = []
    completed: list[object] = []

    def __init__(self, _settings: object) -> None:
        pass

    def register_challenge(self, request: Any) -> _Record:
        self.registered.append(request)
        return _Record(request.gate_id)

    def get_operator_record(self, gate_id: str) -> dict[str, object]:
        if gate_id == "missing":
            raise PaperGateNotFound()
        return _Record(gate_id).to_operator_dict()

    def register_completion(self, request: Any) -> _CompletionRecord:
        self.completed.append(request)
        return _CompletionRecord(request.gate_id)

    def list_observed(self, workspace_id: str) -> list[dict[str, object]]:
        assert workspace_id == "workspace-root"
        return [{"gate_id": "gate-one", "workspace_id": workspace_id}]


class _AttestationAuthority:
    requests: list[object] = []

    def __init__(self, _settings: object) -> None:
        pass

    def attest(self, request: Any) -> dict[str, object]:
        self.requests.append(request)
        return {
            "actual_model": "test-model",
            "actual_provider": "test-provider",
            "attestation_ref": "paper-run-attestation:" + "a" * 64,
            "command_id": request.command_id,
            "command_state": "succeeded",
            "evidence_digest": "a" * 64,
            "hermes_run_id": request.hermes_run_id,
            "hermes_runtime_instance_id": "b" * 32,
            "hermes_runtime_started_at": "2026-07-26T00:00:00.000000Z",
            "hermes_session_id": request.hermes_session_id,
            "hqa_run_ref": f"run:{request.hermes_run_id}",
            "mode": request.mode,
            "output_digest": "c" * 64,
            "platform_session_id": request.platform_session_id,
            "provider_evidence_ref": (
                "provider-evidence:paper-run-" + "a" * 64
            ),
            "resolved_hermes_session_id": request.hermes_session_id,
            "schema_version": 1,
            "terminal_event_ref": "hermes-event:terminal-test",
            "workspace_id": request.workspace_id,
        }


def _register_document() -> dict[str, object]:
    return {
        "attempt_ref": "attempt:paper-plan",
        "command_id": f"command:{COMMAND_ID}",
        "expected_task_version": 7,
        "gate_id": "gate-one",
        "gate_kind": "gate1",
        "hermes_run_id": "hermes-run-one",
        "hermes_session_id": "web_managed-one",
        "hqa_gate_ref": "gate:hqa-paper",
        "platform_session_id": "platform-session",
        "reviewed_source_sha256": "a" * 64,
        "source_file_ref": "/tmp/factor.py",
        "task_ref": "task:paper",
        "universe": "Global equities",
        "workspace_id": "workspace-root",
    }


def _completion_document() -> dict[str, object]:
    return {
        "completion_evidence": {
            "schema_version": "agent-v0.2-paper-completion/v1",
        },
        "gate_id": "gate-three",
        "hqa_completion_receipt_digest": "a" * 64,
        "hqa_completion_receipt_ref": ("hqa-paper-completion:" + "a" * 32),
        "workspace_id": "workspace-root",
    }


def test_strict_json_cli_register_show_and_list(
    monkeypatch,
) -> None:
    _Authority.registered.clear()
    _Authority.completed.clear()
    monkeypatch.setattr(paper_gate_cli, "PaperGateAuthority", _Authority)
    monkeypatch.setattr(paper_gate_cli, "load_settings", object)

    registered = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["register"],
        input=json.dumps(_register_document()),
    )
    assert registered.exit_code == 0, registered.output
    payload = json.loads(registered.stdout)
    assert payload["contract"] == "agent-v0.2-paper-gate-cli/v1"
    assert payload["operation"] == "register"
    assert payload["gate"]["command_ref"] == f"command:{COMMAND_ID}"
    assert len(_Authority.registered) == 1

    completed = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["complete"],
        input=json.dumps(_completion_document()),
    )
    assert completed.exit_code == 0, completed.output
    completion_payload = json.loads(completed.stdout)
    assert completion_payload["operation"] == "complete"
    assert completion_payload["completion"]["status"] == "completed"
    assert len(_Authority.completed) == 1

    shown = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["show"],
        input=(
            '{"gate_id":"gate-one","platform_session_id":"platform-session",'
            '"workspace_id":"workspace-root"}'
        ),
    )
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)["gate"]["reviewed_commit"] is None

    listed = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["list"],
        input='{"workspace_id":"workspace-root"}',
    )
    assert listed.exit_code == 0
    assert json.loads(listed.stdout)["gates"][0]["gate_id"] == "gate-one"


def test_strict_json_cli_attest_run_is_registered_and_read_only(
    monkeypatch,
) -> None:
    _AttestationAuthority.requests.clear()
    monkeypatch.setattr(
        paper_gate_cli,
        "PaperRunAttestationAuthority",
        _AttestationAuthority,
    )
    monkeypatch.setattr(paper_gate_cli, "load_settings", object)
    document = {
        "command_id": COMMAND_ID,
        "hermes_run_id": "run-paper-plan",
        "hermes_session_id": "web_managed-one",
        "mode": "subject",
        "platform_session_id": "platform-session",
        "workspace_id": "workspace-root",
    }

    result = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["attest-run"],
        input=json.dumps(document),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "attestation": {
            "actual_model": "test-model",
            "actual_provider": "test-provider",
            "attestation_ref": "paper-run-attestation:" + "a" * 64,
            "command_id": COMMAND_ID,
            "command_state": "succeeded",
            "evidence_digest": "a" * 64,
            "hermes_run_id": "run-paper-plan",
            "hermes_runtime_instance_id": "b" * 32,
            "hermes_runtime_started_at": "2026-07-26T00:00:00.000000Z",
            "hermes_session_id": "web_managed-one",
            "hqa_run_ref": "run:run-paper-plan",
            "mode": "subject",
            "output_digest": "c" * 64,
            "platform_session_id": "platform-session",
            "provider_evidence_ref": (
                "provider-evidence:paper-run-" + "a" * 64
            ),
            "resolved_hermes_session_id": "web_managed-one",
            "schema_version": 1,
            "terminal_event_ref": "hermes-event:terminal-test",
            "workspace_id": "workspace-root",
        },
        "contract": "agent-v0.2-paper-gate-cli/v1",
        "ok": True,
        "operation": "attest-run",
    }
    assert len(_AttestationAuthority.requests) == 1


def test_attest_run_unavailable_is_a_retryable_process_failure(
    monkeypatch,
) -> None:
    class _Unavailable:
        def __init__(self, _settings: object) -> None:
            pass

        def attest(self, _request: Any) -> dict[str, object]:
            raise PaperRunAttestationUnavailable("temporary observer outage")

    monkeypatch.setattr(paper_gate_cli, "PaperRunAttestationAuthority", _Unavailable)
    monkeypatch.setattr(paper_gate_cli, "load_settings", object)

    result = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["attest-run"],
        input=json.dumps(
            {
                "command_id": COMMAND_ID,
                "hermes_run_id": "run-paper-plan",
                "hermes_session_id": "web_managed-one",
                "mode": "subject",
                "platform_session_id": "platform-session",
                "workspace_id": "workspace-root",
            }
        ),
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == (
        "paper_run_attestation_unavailable"
    )


def test_strict_json_cli_rejects_unknown_trailing_and_missing(
    monkeypatch,
) -> None:
    _Authority.registered.clear()
    _Authority.completed.clear()
    monkeypatch.setattr(paper_gate_cli, "PaperGateAuthority", _Authority)
    monkeypatch.setattr(paper_gate_cli, "load_settings", object)

    unknown = _register_document()
    unknown["prompt"] = "must never cross this port"
    result = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["register"],
        input=json.dumps(unknown),
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_code"] == ("paper_gate_cli_invalid_input")
    assert _Authority.registered == []

    trailing = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["show"],
        input=(
            '{"gate_id":"gate-one","platform_session_id":"platform-session",'
            '"workspace_id":"workspace-root"} '
            '{"gate_id":"gate-two","platform_session_id":"platform-session",'
            '"workspace_id":"workspace-root"}'
        ),
    )
    assert trailing.exit_code == 2
    assert json.loads(trailing.stdout)["error_code"] == ("paper_gate_cli_invalid_input")

    duplicate = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["show"],
        input=(
            '{"gate_id":"gate-one","gate_id":"gate-two",'
            '"platform_session_id":"platform-session",'
            '"workspace_id":"workspace-root"}'
        ),
    )
    assert duplicate.exit_code == 2
    assert json.loads(duplicate.stdout)["error_code"] == ("paper_gate_cli_invalid_input")

    nonfinite = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["list"],
        input='{"workspace_id":"workspace-root","x":NaN}',
    )
    assert nonfinite.exit_code == 2
    assert json.loads(nonfinite.stdout)["error_code"] == ("paper_gate_cli_invalid_input")

    missing = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["register"],
        input="{}",
    )
    assert missing.exit_code == 2

    completion_unknown = _completion_document()
    completion_unknown["prompt"] = "browser must not register completion"
    rejected_completion = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["complete"],
        input=json.dumps(completion_unknown),
    )
    assert rejected_completion.exit_code == 2
    assert _Authority.completed == []

    invalid_attestation = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["attest-run"],
        input='{"mode":"subject"}',
    )
    assert invalid_attestation.exit_code == 2
    assert (
        json.loads(invalid_attestation.stdout)["error_code"]
        == "paper_gate_cli_invalid_input"
    )


def test_show_missing_has_distinct_recovery_code(monkeypatch) -> None:
    monkeypatch.setattr(paper_gate_cli, "PaperGateAuthority", _Authority)
    monkeypatch.setattr(paper_gate_cli, "load_settings", object)
    result = runner.invoke(
        paper_gate_cli.paper_gate_app,
        ["show"],
        input=(
            '{"gate_id":"missing","platform_session_id":"platform-session",'
            '"workspace_id":"workspace-root"}'
        ),
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error_code"] == "paper_gate_not_found"


def test_show_fails_closed_on_workspace_or_session_substitution(monkeypatch) -> None:
    monkeypatch.setattr(paper_gate_cli, "PaperGateAuthority", _Authority)
    monkeypatch.setattr(paper_gate_cli, "load_settings", object)

    for document in (
        {
            "gate_id": "gate-one",
            "platform_session_id": "platform-session",
            "workspace_id": "other-workspace",
        },
        {
            "gate_id": "gate-one",
            "platform_session_id": "other-session",
            "workspace_id": "workspace-root",
        },
    ):
        result = runner.invoke(
            paper_gate_cli.paper_gate_app,
            ["show"],
            input=json.dumps(document),
        )
        assert result.exit_code == 2
        assert json.loads(result.stdout)["error_code"] == ("paper_gate_context_mismatch")
