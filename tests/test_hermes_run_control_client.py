from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from quant_system.config.settings import HermesGatewaySettings
from quant_system.hermes.gateway_client import (
    HermesRunControlError,
    OfficialHermesRunControlClient,
)

DIGEST = "a" * 64
RUN_ID = "run-control-1"
CHALLENGE_ID = "challenge-control-1"
APPROVAL_ID = "approval-core-1"
EXPIRES_AT = "2099-01-01T00:00:00.000000Z"
EXPIRES_EPOCH = 4_070_908_800.0


def _token_file(tmp_path: Path) -> Path:
    path = tmp_path / "hermes-api.key"
    path.write_text("test-only-token\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _settings(tmp_path: Path) -> HermesGatewaySettings:
    return HermesGatewaySettings(
        enabled=True,
        base_url="http://127.0.0.1:8642",
        api_key_file=_token_file(tmp_path),
        timeout_seconds=0.2,
        max_response_bytes=64 * 1024,
    )


def _capabilities() -> dict[str, object]:
    return {
        "object": "hermes.api_server.capabilities",
        "model": "test",
        "contract_version": 1,
        "runtime": {
            "instance_id": "1" * 32,
            "started_at": "2026-07-25T01:02:03.000000Z",
            "pid": 123,
            "build": {
                "schema_version": 1,
                "source": "git_worktree",
                "ready": True,
                "root_realpath": "/reviewed/hermes",
                "module_realpath": "/reviewed/hermes/gateway/platforms/api_server.py",
                "entrypoint_sha256": "2" * 64,
                "commit": "3" * 40,
                "tree": "4" * 40,
                "clean": True,
                "digest": "5" * 64,
            },
        },
        "features": {
            "session_resources": True,
            "run_submission": True,
            "run_events_sse": True,
            "run_status": True,
            "run_approval_response": True,
            "run_stop": True,
            "managed_run_sessions": True,
        },
        "durable": {
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
        },
    }


def _sse(*events: dict[str, object]) -> bytes:
    frames: list[str] = []
    for event in events:
        seq = event["seq"]
        event_type = event["event"]
        frames.append(
            f"id: {seq}\nevent: {event_type}\n"
            f"data: {json.dumps(event, separators=(',', ':'))}\n\n"
        )
    frames.append(": stream closed\n\n")
    return "".join(frames).encode()


def _approval_request(*, seq: int = 1) -> dict[str, object]:
    return {
        "seq": seq,
        "event": "approval.request",
        "event_id": f"event-{seq}",
        "run_id": RUN_ID,
        "challenge_id": CHALLENGE_ID,
        "approval_id": APPROVAL_ID,
        "action_digest": DIGEST,
        "expires_at": EXPIRES_EPOCH,
        "choices": ["once", "deny"],
    }


def test_exact_pending_approval_is_verified_before_once_post(tmp_path: Path) -> None:
    seen: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=_capabilities())
        if request.url.path == f"/v1/runs/{RUN_ID}/events":
            return httpx.Response(
                200,
                content=_sse(_approval_request()),
                headers={"content-type": "text/event-stream"},
            )
        if request.url.path == f"/v1/runs/{RUN_ID}/approval":
            return httpx.Response(
                200,
                json={
                    "object": "hermes.run.approval_response",
                    "run_id": RUN_ID,
                    "choice": "once",
                    "decision_status": "committed",
                    "waiter_signal_status": "confirmed",
                    "challenge_id": CHALLENGE_ID,
                    "approval_id": APPROVAL_ID,
                    "action_digest": DIGEST,
                },
            )
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    client = OfficialHermesRunControlClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.respond_approval_exact(
        RUN_ID,
        choice="once",
        challenge_id=CHALLENGE_ID,
        action_digest=DIGEST,
        expected_status="pending",
        expected_expires_at=EXPIRES_AT,
    )

    assert result.waiter_signal_status == "confirmed"
    assert seen == [
        ("GET", "/v1/capabilities", None),
        ("GET", f"/v1/runs/{RUN_ID}/events", None),
        (
            "POST",
            f"/v1/runs/{RUN_ID}/approval",
            {
                "choice": "once",
                "challenge_id": CHALLENGE_ID,
                "action_digest": DIGEST,
            },
        ),
    ]


def test_stale_expiry_fails_closed_before_approval_post(tmp_path: Path) -> None:
    posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.method == "POST":
            posts += 1
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=_capabilities())
        return httpx.Response(
            200,
            content=_sse(_approval_request()),
            headers={"content-type": "text/event-stream"},
        )

    client = OfficialHermesRunControlClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(HermesRunControlError) as exc:
        client.respond_approval_exact(
            RUN_ID,
            choice="deny",
            challenge_id=CHALLENGE_ID,
            action_digest=DIGEST,
            expected_status="pending",
            expected_expires_at="2099-01-01T00:00:01.000000Z",
        )

    assert exc.value.code == "approval_exact_binding_conflict"
    assert posts == 0


def test_exact_decision_replay_can_recover_unknown_waiter_after_restart(
    tmp_path: Path,
) -> None:
    decision = {
        "seq": 2,
        "event": "approval.decision_recorded",
        "event_id": "event-2",
        "run_id": RUN_ID,
        "challenge_id": CHALLENGE_ID,
        "approval_id": APPROVAL_ID,
        "action_digest": DIGEST,
        "choice": "deny",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=_capabilities())
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                content=_sse(_approval_request(), decision),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json={
                "object": "hermes.run.approval_response",
                "run_id": RUN_ID,
                "choice": "deny",
                "decision_status": "committed",
                "waiter_signal_status": "unknown",
                "challenge_id": CHALLENGE_ID,
                "approval_id": APPROVAL_ID,
                "action_digest": DIGEST,
                "idempotent_replay": True,
            },
        )

    client = OfficialHermesRunControlClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.respond_approval_exact(
        RUN_ID,
        choice="deny",
        challenge_id=CHALLENGE_ID,
        action_digest=DIGEST,
        expected_status="pending",
        expected_expires_at=EXPIRES_AT,
    )

    assert result.idempotent_replay is True
    assert result.waiter_signal_status == "unknown"


def test_stop_reconciles_immediate_terminal_status(tmp_path: Path) -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=_capabilities())
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "run_id": RUN_ID,
                    "status": "running",
                    "substate": "stopping",
                },
            )
        return httpx.Response(
            200,
            json={
                "object": "hermes.run",
                "run_id": RUN_ID,
                "status": "stopped",
                "session_id": "web-session",
            },
        )

    client = OfficialHermesRunControlClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    result = client.stop(RUN_ID)

    assert result.status == "stopped"
    assert result.idempotent_replay is False
    assert seen == [
        ("GET", "/v1/capabilities"),
        ("POST", f"/v1/runs/{RUN_ID}/stop"),
        ("GET", f"/v1/runs/{RUN_ID}"),
    ]


def test_capability_failure_prevents_stop_post(tmp_path: Path) -> None:
    posts = 0
    capabilities = _capabilities()
    capabilities["durable"]["idempotent_stop"]["grounded"] = False  # type: ignore[index]

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.method == "POST":
            posts += 1
        return httpx.Response(200, json=capabilities)

    client = OfficialHermesRunControlClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(HermesRunControlError) as exc:
        client.stop(RUN_ID)

    assert exc.value.code == "durable_run_control_unavailable"
    assert posts == 0


def test_event_gap_is_not_accepted_as_approval_authority(tmp_path: Path) -> None:
    request = _approval_request(seq=2)

    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path == "/v1/capabilities":
            return httpx.Response(200, json=_capabilities())
        return httpx.Response(
            200,
            content=_sse(request),
            headers={"content-type": "text/event-stream"},
        )

    client = OfficialHermesRunControlClient(
        _settings(tmp_path),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(HermesRunControlError) as exc:
        client.respond_approval_exact(
            RUN_ID,
            choice="once",
            challenge_id=CHALLENGE_ID,
            action_digest=DIGEST,
            expected_status="pending",
            expected_expires_at=EXPIRES_AT,
        )

    assert exc.value.code == "run_event_replay_incomplete"
