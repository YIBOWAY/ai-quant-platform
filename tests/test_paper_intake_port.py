from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from quant_system.hermes.command_ledger import HermesCommand
from quant_system.hermes.dispatch_adapter import HermesRunObservation
from quant_system.hermes.paper_intake_port import (
    PaperIntakePortError,
    SubprocessPaperIntakePreparationPort,
    SubprocessPaperIntakeVerificationPort,
)
from quant_system.hermes.run_lifecycle_port import HermesRunCliSettings


def _command() -> HermesCommand:
    from tests.test_hermes_connector_dispatch import _cmd

    return replace(
        _cmd(state="delivered", version=4),
        hermes_session_id="web_root",
        resolved_hermes_session_id="web_tip",
        hermes_run_id="run_paper_1",
    )


def _observation(command: HermesCommand) -> HermesRunObservation:
    return HermesRunObservation(
        status="succeeded",
        conversation_hermes_session_id="web_root",
        hermes_session_id="web_tip",
        hermes_run_id="run_paper_1",
        evidence_digest="b" * 64,
        next_cursor=4,
        replay_complete=True,
    )


def _accepted(command: HermesCommand) -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": "hqa.paper_intake/v1",
        "disposition": "accepted",
        "command_id": str(command.command_id),
        "payload_ref": "payload:sha256:" + ("b" * 64),
        "hermes_session_id": "web_tip",
        "hermes_run_id": "run_paper_1",
        "observation_evidence_digest": "b" * 64,
        "execution_contract_digest": "c" * 64,
        "research_claim_digest": "d" * 64,
        "discovery_mode": "web_search",
        "search_result_count": 1,
        "search_results_digest": "e" * 64,
        "full_text_mode": "direct_pdf",
        "full_text_bytes": 9000,
        "full_text_sha256": "f" * 64,
        "paper_url_sha256": "1" * 64,
        "paper_identity_sha256": "2" * 64,
        "source_file_ref": "/private/paper-intake/factor.py",
        "source_bytes": 120,
        "source_sha256": "3" * 64,
        "receipt_ref": "paper-intake-receipt:sha256:" + ("4" * 64),
        "receipt_digest": "4" * 64,
    }


def _port(tmp_path: Path, runner) -> SubprocessPaperIntakeVerificationPort:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    return SubprocessPaperIntakeVerificationPort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key="stdin-secret",
            timeout_seconds=5.0,
        ),
        workspace_id="ws-local-main",
        runner=runner,
    )


def _preparation_port(tmp_path: Path, runner) -> SubprocessPaperIntakePreparationPort:
    verifier = _port(tmp_path, runner)
    return SubprocessPaperIntakePreparationPort(
        cli_settings=verifier.cli_settings,
        runner=runner,
    )


def _prepare_request() -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "kind": "paper_intake",
        "owner_id": "owner-local-root",
        "workspace_id": "workspace:ws-local-main",
        "session_id": "session:managed-1",
        "client_intent_id": "paper-intake-0001",
        "provider_policy": {
            "primary": {"provider": "openai", "model": "gpt-5"},
            "fallbacks": [],
        },
        "prompt": "private exact paper request",
        "ttl_days": 7,
        "paper_title": "A Testable Paper Factor",
        "universe": ["SPY", "QQQ"],
    }


def _prepared_receipt() -> dict[str, object]:
    return {
        "ok": True,
        "schema_version": "2.0",
        "payload_ref": "payload:sha256:" + ("a" * 64),
        "payload_digest": "a" * 64,
        "kind": "paper_intake",
        "client_intent_id": "paper-intake-0001",
        "provider_policy_digest": (
            "be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31"
        ),
        "created_at": "2026-08-10T00:00:00.000000Z",
        "expires_at": "2026-08-17T00:00:00.000000Z",
        "ttl_days": 7,
        "status": "active",
        "research_claim_digest": "c" * 64,
        "execution_contract_digest": "d" * 64,
    }


def test_preparation_port_sends_private_fields_only_over_stdin_and_validates_receipt(
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def runner(argv, **kwargs):
        captured["argv"] = argv
        captured["request"] = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(_prepared_receipt()).encode(),
            stderr=b"",
        )

    receipt = _preparation_port(tmp_path, runner).prepare(_prepare_request())

    assert receipt["payload_ref"] == "payload:sha256:" + ("a" * 64)
    assert receipt["execution_contract_digest"] == "d" * 64
    assert captured["argv"][-2:] == ["hqa.paper_intake_cli", "prepare"]
    assert "private exact paper request" not in " ".join(captured["argv"])
    assert captured["request"]["paper_title"] == "A Testable Paper Factor"


def test_preparation_port_rejects_receipt_with_substituted_client_identity(
    tmp_path: Path,
) -> None:
    document = _prepared_receipt()
    document["client_intent_id"] = "paper-intake-other"

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(document).encode(),
            stderr=b"",
        )

    with pytest.raises(PaperIntakePortError) as captured:
        _preparation_port(tmp_path, runner).prepare(_prepare_request())

    assert captured.value.code == "paper_intake_cli_invalid_receipt"


def test_subprocess_port_accepts_exact_body_free_receipt(tmp_path: Path) -> None:
    command = _command()
    captured: dict[str, object] = {}

    def runner(argv, **kwargs):
        captured["argv"] = argv
        captured["request"] = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(_accepted(command)).encode(), stderr=b""
        )

    decision = _port(tmp_path, runner).verify(command, _observation(command))

    assert decision.disposition == "accepted"
    assert decision.receipt_digest == "4" * 64
    assert decision.source_sha256 == "3" * 64
    assert captured["argv"][-2:] == ["hqa.paper_intake_cli", "verify"]
    assert "stdin-secret" not in " ".join(captured["argv"])
    request = captured["request"]
    assert request["owner_id"] == "owner-local-root"
    assert request["command_id"] == str(command.command_id)
    assert request["endpoint"]["api_key"] == "stdin-secret"


def test_subprocess_port_maps_typed_nonretryable_rejection(tmp_path: Path) -> None:
    command = _command()

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            2,
            stdout=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "paper_intake_discovery_missing",
                        "message": "redacted",
                        "retryable": False,
                    },
                }
            ).encode(),
            stderr=b"private transcript",
        )

    with pytest.raises(PaperIntakePortError) as captured:
        _port(tmp_path, runner).verify(command, _observation(command))

    assert captured.value.code == "paper_intake_discovery_missing"
    assert captured.value.retryable is False
    assert "private transcript" not in str(captured.value)


def test_subprocess_port_rejects_substituted_receipt_identity(tmp_path: Path) -> None:
    command = _command()
    document = _accepted(command)
    document["hermes_run_id"] = "run_other"

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv, 0, stdout=json.dumps(document).encode(), stderr=b""
        )

    with pytest.raises(PaperIntakePortError) as captured:
        _port(tmp_path, runner).verify(command, _observation(command))

    assert captured.value.code == "paper_intake_cli_invalid_receipt"
