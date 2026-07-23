"""Unit tests for Intent Payload CLI Port (Fake + subprocess with Fake crypto CLI)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.hermes.dark_identity_profile import (
    PROVIDER_POLICY_DIGEST,
    build_bind_resolve_request,
    build_put_request,
)
from quant_system.hermes.intent_payload_port import (
    FakeIntentPayloadPort,
    IntentPayloadCliSettings,
    IntentPayloadPortError,
    SubprocessIntentPayloadPort,
    build_intent_payload_port,
)


def test_fake_put_and_bind_resolve_round_trip() -> None:
    port = FakeIntentPayloadPort()
    put_req = build_put_request(
        managed_session_ref="session:m1",
        client_intent_id="intent-fake-1",
        prompt="Reply with exactly: L2a-pong",
        payload_ttl_days=7,
    )
    receipt = port.put_intent(put_req)
    assert receipt["ok"] is True
    assert receipt["payload_ref"].startswith("payload:sha256:")
    assert "prompt" not in receipt

    again = port.put_intent(put_req)
    assert again["payload_digest"] == receipt["payload_digest"]

    resolve_req = build_bind_resolve_request(
        payload_ref=receipt["payload_ref"],
        managed_session_ref="session:m1",
        consumer_ref="command:cmd-1",
    )
    resolved = port.bind_and_resolve_prompt(resolve_req)
    assert resolved["prompt"] == "Reply with exactly: L2a-pong"
    assert resolved["consumer_ref"] == "command:cmd-1"


def test_fake_put_idempotency_conflict() -> None:
    port = FakeIntentPayloadPort()
    base = build_put_request(
        managed_session_ref="s1",
        client_intent_id="same-id",
        prompt="one",
        payload_ttl_days=7,
    )
    port.put_intent(base)
    with pytest.raises(IntentPayloadPortError) as exc:
        port.put_intent({**base, "prompt": "two"})
    assert exc.value.code == "intent_idempotency_conflict"
    assert exc.value.retryable is False


def test_fake_consumer_conflict() -> None:
    port = FakeIntentPayloadPort()
    receipt = port.put_intent(
        build_put_request(
            managed_session_ref="s1",
            client_intent_id="i1",
            prompt="hi",
            payload_ttl_days=7,
        )
    )
    port.bind_and_resolve_prompt(
        build_bind_resolve_request(
            payload_ref=receipt["payload_ref"],
            managed_session_ref="s1",
            consumer_ref="command:a",
        )
    )
    with pytest.raises(IntentPayloadPortError) as exc:
        port.bind_and_resolve_prompt(
            build_bind_resolve_request(
                payload_ref=receipt["payload_ref"],
                managed_session_ref="s1",
                consumer_ref="command:b",
            )
        )
    assert exc.value.code == "intent_consumer_conflict"


def test_subprocess_port_maps_structured_error(tmp_path: Path) -> None:
    def runner(argv, **kwargs):  # type: ignore[no-untyped-def]
        _ = argv, kwargs
        stdout = json.dumps(
            {
                "error": {
                    "code": "intent_idempotency_conflict",
                    "message": "conflict",
                    "retryable": False,
                }
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return subprocess.CompletedProcess(
            args=argv,
            returncode=2,
            stdout=stdout,
            stderr=b"",
        )

    port = SubprocessIntentPayloadPort(
        cli_settings=IntentPayloadCliSettings(
            python_executable=Path("/usr/bin/true"),
            hqa_root=tmp_path,
            timeout_seconds=5.0,
        ),
        runner=runner,
    )
    # Bypass is_file checks by using tmp_path as both and stubbing via runner only
    # after path checks — create dummy python file.
    py = tmp_path / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    port = SubprocessIntentPayloadPort(
        cli_settings=IntentPayloadCliSettings(
            python_executable=py,
            hqa_root=tmp_path,
            timeout_seconds=5.0,
        ),
        runner=runner,
    )
    with pytest.raises(IntentPayloadPortError) as exc:
        port.put_intent({"prompt": "x", "client_intent_id": "y"})
    assert exc.value.code == "intent_idempotency_conflict"


def test_subprocess_port_put_rejects_prompt_echo(tmp_path: Path) -> None:
    def runner(argv, **kwargs):  # type: ignore[no-untyped-def]
        _ = argv, kwargs
        stdout = json.dumps(
            {
                "ok": True,
                "payload_ref": "payload:sha256:" + ("a" * 64),
                "payload_digest": "a" * 64,
                "prompt": "LEAK",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return subprocess.CompletedProcess(
            args=argv, returncode=0, stdout=stdout, stderr=b""
        )

    py = tmp_path / "python"
    py.write_text("#!/bin/sh\n", encoding="utf-8")
    py.chmod(0o755)
    port = SubprocessIntentPayloadPort(
        cli_settings=IntentPayloadCliSettings(
            python_executable=py,
            hqa_root=tmp_path,
            timeout_seconds=5.0,
        ),
        runner=runner,
    )
    with pytest.raises(IntentPayloadPortError) as exc:
        port.put_intent({"prompt": "x", "client_intent_id": "y"})
    assert exc.value.code == "intent_cli_leaked_prompt"


def test_build_intent_payload_port_injectable() -> None:
    fake = FakeIntentPayloadPort()
    port = build_intent_payload_port(port=fake)
    assert port is fake


def test_cli_settings_from_settings_block(tmp_path: Path) -> None:
    py = tmp_path / "py"
    py.write_text("", encoding="utf-8")
    hqa = tmp_path / "hqa"
    hqa.mkdir()
    settings = SimpleNamespace(
        intent_payload=SimpleNamespace(
            python_executable=py,
            hqa_root=hqa,
            timeout_seconds=9.0,
        )
    )
    cli = IntentPayloadCliSettings.from_settings(settings)
    assert cli.python_executable == py
    assert cli.hqa_root == hqa
    assert cli.timeout_seconds == 9.0


def test_locked_digest_constant_exported_for_create_session() -> None:
    # Create managed session must use the same digest as put.
    assert len(PROVIDER_POLICY_DIGEST) == 64


def test_intent_payload_input_resolver_bind_resolve() -> None:
    from types import SimpleNamespace

    from quant_system.hermes.intent_payload_port import intent_payload_input_resolver

    port = FakeIntentPayloadPort()
    put_req = build_put_request(
        managed_session_ref="session:m1",
        client_intent_id="intent-resolve-1",
        prompt="Reply with exactly: L2a-pong",
        payload_ttl_days=7,
    )
    receipt = port.put_intent(put_req)
    resolver = intent_payload_input_resolver(port=port)
    prompt = resolver(
        SimpleNamespace(
            command_id="cmd-uuid-1",
            payload_ref="platform-payload://sha256/" + receipt["payload_digest"],
            platform_session_id="m1",
        )
    )
    assert prompt == "Reply with exactly: L2a-pong"
    assert port.resolves[-1]["consumer_ref"] == "command:cmd-uuid-1"
    assert port.resolves[-1]["payload_ref"] == receipt["payload_ref"]
