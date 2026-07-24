"""V4 workspace BFF transport — mutation fail-closed, snapshot/follow owner-gated."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import (
    CSRF_HEADER_NAME,
    issue_bootstrap_token,
)
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID

ORIGIN = "http://127.0.0.1:3001"
WORKSPACE_ID = "ws-bff-v4"


def _settings() -> Settings:
    # Pin mutation OFF so hermetic transport tests ignore the operator's local
    # QS_LOCAL_MUTATION_* env (Local Dark Enablement must not leak into CI).
    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        api_cors_origins=[
            ORIGIN,
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ],
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=_settings(),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    return TestClient(app)


def _browser_headers(*, origin: str = ORIGIN, site: str = "same-origin") -> dict[str, str]:
    return {
        "Origin": origin,
        "Sec-Fetch-Site": site,
        "Host": "testserver",
    }


def _bootstrap(client: TestClient, tmp_path: Path) -> dict[str, str]:
    token = issue_bootstrap_token(tmp_path)
    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    return {
        "csrf": payload["csrf_token"],
        "session_id": payload["session_id"],
    }


def test_workspace_act_without_session_fails(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        f"/api/workspace/{WORKSPACE_ID}/act",
        json={
            "action": {
                "schema_version": 1,
                "kind": "managed_session.create",
                "client_action_id": "x",
                "workspace": {"workspace_id": WORKSPACE_ID},
                "provider_policy_digest": "a" * 64,
                "payload_ttl_days": 7,
            }
        },
        headers=_browser_headers(),
    )
    assert response.status_code in {401, 403}


def test_workspace_act_with_csrf_still_mutation_disabled(tmp_path: Path) -> None:
    client = _client(tmp_path)
    boot = _bootstrap(client, tmp_path)
    headers = {
        **_browser_headers(),
        CSRF_HEADER_NAME: boot["csrf"],
    }
    response = client.post(
        f"/api/workspace/{WORKSPACE_ID}/act",
        json={
            "action": {
                "schema_version": 1,
                "kind": "managed_session.create",
                "client_action_id": "act-bff-1",
                "workspace": {"workspace_id": WORKSPACE_ID},
                "provider_policy_digest": "a" * 64,
                "payload_ttl_days": 7,
            }
        },
        headers=headers,
    )
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "forbidden"
    assert "authenticated_mutation_bff_unavailable" in detail["message"]


def test_workspace_snapshot_and_follow_require_owner_session(tmp_path: Path) -> None:
    client = _client(tmp_path)
    denied = client.get(
        f"/api/workspace/{WORKSPACE_ID}/snapshot",
        headers=_browser_headers(),
    )
    assert denied.status_code == 401

    _bootstrap(client, tmp_path)
    snap = client.get(
        f"/api/workspace/{WORKSPACE_ID}/snapshot",
        headers=_browser_headers(),
    )
    assert snap.status_code == 200, snap.text
    body = snap.json()
    assert body["workspace"]["workspace_id"] == WORKSPACE_ID
    assert body["owner_user_id"] == str(ROOT_USER_ID)
    assert body["mutation_enabled"] is False
    assert body["authority_health"]["mutation"] == "disabled"
    # L5a/V7a: approvals slot is present and honestly empty (no invented challenges).
    # V7a hermetic authority is reachable → health ready even when empty.
    assert body.get("approvals") == []
    assert body["authority_health"].get("command_approval") == "ready"
    # L5b: Task/Attempt/Run authority slots stay empty; health unavailable.
    # V7f: result projector is mounted → empty results[] + health ready (honest empty).
    assert body.get("tasks") == []
    assert body.get("attempts") == []
    assert body.get("runs") == []
    assert body.get("results") == []
    # V7g-A-M1: hermetic vertical projectors mounted; empty lists remain honest.
    assert body["authority_health"].get("task") == "ready"
    assert body["authority_health"].get("attempt") == "ready"
    assert body["authority_health"].get("run") == "ready"
    assert body["authority_health"].get("result") == "ready"

    follow = client.get(
        f"/api/workspace/{WORKSPACE_ID}/follow?after_cursor=0",
        headers=_browser_headers(),
    )
    assert follow.status_code == 200, follow.text
    page = follow.json()
    assert page["mutation_enabled"] is False
    assert page["events"] == []

    authorities = client.get(
        "/api/workspace/authorities",
        headers=_browser_headers(),
    )
    assert authorities.status_code == 200
    assert authorities.json()["mutation_enabled"] is False


def test_workspace_cross_origin_snapshot_fails(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _bootstrap(client, tmp_path)
    cross = client.get(
        f"/api/workspace/{WORKSPACE_ID}/snapshot",
        headers=_browser_headers(origin="http://evil.example", site="cross-site"),
    )
    assert cross.status_code == 403


def test_workspace_follow_stream_requires_owner_and_emits_sse(tmp_path: Path) -> None:
    """L4b: SSE follow is owner-gated; ready frame is command-lifecycle only."""
    client = _client(tmp_path)
    denied = client.get(
        f"/api/workspace/{WORKSPACE_ID}/follow/stream?after_cursor=0&max_ticks=1&poll_seconds=0",
        headers=_browser_headers(),
    )
    assert denied.status_code == 401

    _bootstrap(client, tmp_path)
    # Bound the generator so TestClient cannot hang on the long-lived stream.
    response = client.get(
        f"/api/workspace/{WORKSPACE_ID}/follow/stream"
        f"?after_cursor=0&max_ticks=1&poll_seconds=0",
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text
    assert "text/event-stream" in response.headers.get("content-type", "")
    body = response.text
    assert "event: ready" in body
    assert "command_lifecycle" in body
    assert "event: reconnect" in body
    # No assistant token / message body channel in this stream.
    assert "assistant_token" not in body
    assert "message_body" not in body


def test_health_still_mutation_false_with_workspace_module(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    ledger = response.json()["hermes_command_ledger"]
    assert ledger["mutation_enabled"] is False
    assert "agent_workspace_authorities_ready" in ledger


def test_hermes_gateway_blockers_drop_csrf_unavailable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/hermes/gateway")
    assert response.status_code == 200
    payload = response.json()
    assert payload["chat_write_ready"] is False
    blockers = payload["platform_delivery_blockers"]
    assert "authenticated_mutation_bff_unavailable" in blockers
    assert "research_workflow_submission_unavailable" in blockers
    assert "independent_security_review_unavailable" in blockers
    assert "user_chat_cutover_approval_required" in blockers
    assert "csrf_protection_unavailable" not in blockers


def test_workspace_authorities_include_research_and_blockers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _bootstrap(client, tmp_path)
    authorities = client.get(
        "/api/workspace/authorities",
        headers=_browser_headers(),
    )
    assert authorities.status_code == 200, authorities.text
    body = authorities.json()
    assert body["mutation_enabled"] is False
    assert body["composer_open"] is False
    assert body["chat_write_ready"] is False
    assert body["research_binding_ready"] is False
    assert "research_workflow_submission_unavailable" in body["platform_delivery_blockers"]
    assert body["platform_delivery_blocker_count"] == len(body["platform_delivery_blockers"])
