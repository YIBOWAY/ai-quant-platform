"""Hermetic tests for the platform -> HQA durable Run subprocess seam."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.hermes.dispatch_adapter import (
    HermesDispatchRequest,
    fixed_input_resolver,
)
from quant_system.hermes.intent_payload_port import IntentPayloadPortError
from quant_system.hermes.run_lifecycle_port import (
    HermesRunCliSettings,
    HermesRunPortError,
    SubprocessHermesRunLifecyclePort,
    _parse_stdout,
    build_subprocess_run_lifecycle_port,
)


def _compatible_capability_receipt() -> dict[str, object]:
    durable = {
        name: {
            "supported": True,
            "grounded": True,
            "evidence": f"store.transactional_probe:{name}",
        }
        for name in (
            "idempotency",
            "event_replay",
            "approval_cas",
            "idempotent_stop",
            "restart_reconcile",
            "run_evidence",
        )
    }
    return {
        "ok": True,
        "capabilities": {
            "contract_version": 1,
            "features": {
                "session_resources": True,
                "run_submission": True,
                "run_events_sse": True,
                "run_status": True,
                "run_approval_response": True,
                "run_stop": True,
                "managed_run_sessions": True,
                "managed_run_history_authority": "hermes_session_db",
                "managed_session_fork_mode": (
                    "preserve_source_exact_message_cursor"
                ),
            },
            "durable": durable,
        },
        "cli_contract": {
            "schema_version": 1,
            "profile": "local_agent_v0_2",
            "operations": [
                "capabilities",
                "submit",
                "status",
                "events",
                "session-ensure",
                "session-fork",
            ],
            "write_contract": {
                "run_submit_fields": ["input", "session_id", "metadata"],
                "platform_must_not_send": [
                    "conversation_history",
                    "previous_response_id",
                ],
                "fork_requires": {
                    "preserve_source": True,
                    "fork_point_format": "message:<positive-integer-id>",
                },
            },
        },
        "durable_ready": True,
        "managed_session_ready": True,
    }


def _request() -> HermesDispatchRequest:
    return HermesDispatchRequest(
        command_id="00000000-0000-4000-8000-000000000001",
        kind="research_chat",
        client_request_id="client-action-1",
        platform_session_id="wm_registry_only",
        canonical_request_digest="a" * 64,
        payload_ref="hqa-payload:sha256:" + ("b" * 64),
        provider_policy_digest="c" * 64,
        hermes_session_id="web_managed_1",
    )


def test_strict_capability_preflight_validates_real_hqa_cli_contract(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    operations: list[str] = []

    def runner(argv, **_kwargs):
        operations.append(argv[-1])
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(_compatible_capability_receipt()).encode(),
            stderr=b"",
        )

    port = SubprocessHermesRunLifecyclePort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key="stdin-only-secret",
            timeout_seconds=5.0,
        ),
        input_resolver=fixed_input_resolver("unused"),
        runner=runner,
    )

    receipt = port.require_compatible_capabilities()

    assert operations == ["capabilities"]
    assert receipt.cli_operations == (
        "capabilities",
        "submit",
        "status",
        "events",
        "session-ensure",
        "session-fork",
    )
    assert receipt.hermes_contract_version == 1
    assert len(receipt.evidence_digest) == 64
    assert "stdin-only-secret" not in repr(receipt)


def test_strict_capability_preflight_rejects_drifted_hqa_operation_surface(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    drifted = _compatible_capability_receipt()
    cli_contract = drifted["cli_contract"]
    assert isinstance(cli_contract, dict)
    cli_contract["operations"] = ["capabilities", "submit", "unsafe-extra"]

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(drifted).encode(),
            stderr=b"api-key=must-not-escape",
        )

    port = SubprocessHermesRunLifecyclePort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key="stdin-only-secret",
            timeout_seconds=5.0,
        ),
        input_resolver=fixed_input_resolver("unused"),
        runner=runner,
    )

    with pytest.raises(HermesRunPortError) as captured:
        port.require_compatible_capabilities()

    assert captured.value.code == "run_cli_contract_mismatch"
    assert captured.value.retryable is False
    assert "unsafe-extra" not in str(captured.value)
    assert "stdin-only-secret" not in str(captured.value)


def test_capability_preflight_uses_short_bounded_probe_deadlines(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    observed: dict[str, object] = {}

    def runner(argv, **kwargs):
        observed["process_timeout"] = kwargs["timeout"]
        observed["request"] = json.loads(kwargs["input"])
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(_compatible_capability_receipt()).encode(),
            stderr=b"",
        )

    port = SubprocessHermesRunLifecyclePort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key=None,
            timeout_seconds=120.0,
        ),
        input_resolver=fixed_input_resolver("unused"),
        runner=runner,
    )

    port.require_compatible_capabilities()

    request = observed["request"]
    assert isinstance(request, dict)
    endpoint = request["endpoint"]
    assert isinstance(endpoint, dict)
    assert endpoint["timeout_seconds"] == 5.0
    assert observed["process_timeout"] == 7.0


def test_submit_uses_strict_hqa_cli_and_preserves_managed_session(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv, **kwargs):
        document = json.loads(kwargs["input"])
        calls.append((list(argv), document))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "run_id": "run_durable_1",
                    "created": True,
                    "idempotency_key": (
                        "platform-command:00000000-0000-4000-8000-000000000001"
                    ),
                }
            ).encode(),
            stderr=b"",
        )

    port = SubprocessHermesRunLifecyclePort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key="top-secret",
            timeout_seconds=5.0,
        ),
        input_resolver=fixed_input_resolver("hello managed thread"),
        runner=runner,
    )

    result = port.submit_or_recover(_request())

    assert result.kind == "accepted"
    assert result.hermes_run_id == "run_durable_1"
    assert result.hermes_session_id == "web_managed_1"
    argv, document = calls[0]
    assert argv[-2:] == ["hqa.hermes_run_cli", "submit"]
    assert "top-secret" not in " ".join(argv)
    assert "hello managed thread" not in " ".join(argv)
    assert document["idempotency_key"] == (
        "platform-command:00000000-0000-4000-8000-000000000001"
    )
    request_body = document["request_body"]
    assert isinstance(request_body, dict)
    assert request_body["session_id"] == "web_managed_1"
    assert request_body["input"] == "hello managed thread"


def test_observe_requires_gapless_replay_and_returns_terminal_evidence(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    operations: list[str] = []

    def runner(argv, **kwargs):
        operation = argv[-1]
        operations.append(operation)
        request = json.loads(kwargs["input"])
        if operation == "status":
            payload = {
                "ok": True,
                "run_id": "run_durable_2",
                "session_id": "web_managed_2",
                "status": "succeeded",
                "actual_policy": {"model": "gpt-5", "provider": "openai"},
                "usage": {"input_tokens": 9, "output_tokens": 3},
            }
        else:
            assert operation == "events"
            assert request["since_seq"] == 0
            payload = {
                "ok": True,
                "run_id": "run_durable_2",
                "since_seq": 0,
                "next_seq": 2,
                "events": [
                    {
                        "seq": 1,
                        "event_type": "message.delta",
                        "run_id": "run_durable_2",
                        "payload": {"delta": "working"},
                    },
                    {
                        "seq": 2,
                        "event_type": "run.completed",
                        "run_id": "run_durable_2",
                        "payload": {"usage": {}},
                    },
                ],
            }
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(payload).encode(),
            stderr=b"",
        )

    port = SubprocessHermesRunLifecyclePort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key=None,
            timeout_seconds=5.0,
        ),
        input_resolver=fixed_input_resolver("unused"),
        runner=runner,
    )

    observation = port.observe(
        hermes_session_id="web_managed_2",
        hermes_run_id="run_durable_2",
        after_cursor=0,
    )

    assert operations == ["status", "events"]
    assert observation.status == "succeeded"
    assert observation.replay_complete is True
    assert observation.next_cursor == 2
    assert observation.evidence_digest is not None


def test_factory_normalizes_intent_payload_settings_failure(monkeypatch) -> None:
    from quant_system.hermes.intent_payload_port import (
        IntentPayloadCliSettings,
        IntentPayloadPortError,
    )

    def fail_settings(_settings):
        raise IntentPayloadPortError(
            "intent_port_misconfigured",
            "secret path must not escape",
            retryable=False,
        )

    monkeypatch.setattr(IntentPayloadCliSettings, "from_settings", fail_settings)
    settings = SimpleNamespace(
        hermes_gateway=SimpleNamespace(enabled=True, base_url="http://127.0.0.1:8642")
    )

    with pytest.raises(HermesRunPortError) as captured:
        build_subprocess_run_lifecycle_port(settings, input_resolver=lambda _request: "x")

    assert captured.value.code == "run_port_misconfigured"
    assert "secret path" not in captured.value.message


@pytest.mark.parametrize(
    ("retryable", "expected_kind", "error_code"),
    [
        (True, "unavailable", "intent_cli_timeout"),
        (False, "rejected", "intent_consumer_conflict"),
    ],
)
def test_submit_preserves_structured_payload_resolution_semantics(
    tmp_path: Path,
    retryable: bool,
    expected_kind: str,
    error_code: str,
) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()

    def fail_resolve(_request):
        raise IntentPayloadPortError(
            error_code,
            "secret resolver detail",
            retryable=retryable,
        )

    def no_run_call(*_args, **_kwargs):
        raise AssertionError("Run CLI must not execute after payload resolution failure")

    port = SubprocessHermesRunLifecyclePort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key=None,
            timeout_seconds=5.0,
        ),
        input_resolver=fail_resolve,
        runner=no_run_call,
    )

    result = port.submit_or_recover(_request())

    assert result.kind == expected_kind
    assert result.error_code == error_code
    assert result.network_attempted is False
    assert "secret resolver detail" not in repr(result)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"ok":true,"ok":false}',
        b'{"ok":true,"usage":NaN}',
        b'{"ok":true,"usage":Infinity}',
        b'{"ok":true}\n{"ok":true}',
        b"x" * 4_194_305,
    ],
)
def test_stdout_parser_rejects_ambiguous_or_unbounded_documents(raw: bytes) -> None:
    with pytest.raises(HermesRunPortError) as captured:
        _parse_stdout(raw)

    assert captured.value.code == "run_cli_invalid_stdout"
    assert captured.value.retryable is True


def test_cli_error_message_cannot_escape_the_secret_free_boundary(
    tmp_path: Path,
) -> None:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout=json.dumps(
                {
                    "error": {
                        "code": "transport_error",
                        "message": "prompt and api-key secret",
                        "retryable": True,
                    }
                }
            ).encode(),
            stderr=b"other secret",
        )

    port = SubprocessHermesRunLifecyclePort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key=None,
            timeout_seconds=5.0,
        ),
        input_resolver=fixed_input_resolver("unused"),
        runner=runner,
    )

    with pytest.raises(HermesRunPortError) as captured:
        port.observe(
            hermes_session_id="web_managed_2",
            hermes_run_id="run_durable_2",
        )

    assert captured.value.code == "transport_error"
    assert captured.value.retryable is True
    assert "secret" not in str(captured.value)
