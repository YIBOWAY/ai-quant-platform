"""BFF transport tests for POST /api/agent/workspace/submit-turn (M1)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from quant_system.api.routes import workspace as workspace_routes
from quant_system.api.safety.local_session import (
    CSRF_HEADER_NAME,
    issue_bootstrap_token,
)
from quant_system.api.safety.mutation_rate_limit import OwnerMutationRateLimiter
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes.dark_identity_profile import (
    PLATFORM_WORKSPACE_ID,
    PROVIDER_POLICY_DIGEST,
    STORE_TTL_DAYS,
)
from quant_system.hermes.intent_payload_port import FakeIntentPayloadPort
from quant_system.hermes.submission_saga import ActionReceipt

ORIGIN = "http://127.0.0.1:3001"


@pytest.fixture(autouse=True)
def _admit_hermetic_bff_release(monkeypatch) -> None:
    """These transport tests isolate the BFF behind an explicitly admitted gate."""

    monkeypatch.setattr(
        workspace_routes,
        "composer_readiness_snapshot",
        lambda _settings, *, fresh=False: {
            "chat_write_ready": True,
            "release_blockers": [],
        },
    )
    monkeypatch.setattr(
        "quant_system.hermes.composite_turn_submit.require_web_writable_session",
        lambda _settings, *, platform_session_id: SimpleNamespace(
            platform_session_id=platform_session_id,
            workspace_id=PLATFORM_WORKSPACE_ID,
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
        ),
    )


def _settings(*, mutation: bool = False) -> Settings:
    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(
            enabled=mutation, composer_open=mutation
        ),
        api_cors_origins=[
            ORIGIN,
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ],
    )


def _client(tmp_path: Path, *, mutation: bool = False) -> TestClient:
    app = create_app(
        settings=_settings(mutation=mutation),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    # Inject Fake port for M1 (no Keychain).
    app.state.services["intent_payload_port"] = FakeIntentPayloadPort()
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


def _body(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "workspace_id": PLATFORM_WORKSPACE_ID,
        "managed_session_ref": "session:managed-bff-1",
        "client_action_id": "intent-bff-0001",
        "prompt": "Reply with exactly: L2a-pong",
    }
    value.update(overrides)
    return value


def test_submit_turn_without_session_fails(tmp_path: Path) -> None:
    client = _client(tmp_path, mutation=True)
    response = client.post(
        "/api/agent/workspace/submit-turn",
        json=_body(),
        headers=_browser_headers(),
    )
    assert response.status_code in {401, 403}


def test_submit_turn_mutation_disabled_with_csrf(tmp_path: Path) -> None:
    client = _client(tmp_path, mutation=False)
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}
    response = client.post(
        "/api/agent/workspace/submit-turn",
        json=_body(),
        headers=headers,
    )
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "forbidden"


def test_submit_turn_empty_prompt_400(tmp_path: Path) -> None:
    client = _client(tmp_path, mutation=True)
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}
    response = client.post(
        "/api/agent/workspace/submit-turn",
        json=_body(prompt="   "),
        headers=headers,
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "validation"


def test_submit_turn_rejects_unknown_workspace(tmp_path: Path) -> None:
    client = _client(tmp_path, mutation=True)
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}
    response = client.post(
        "/api/agent/workspace/submit-turn",
        json=_body(workspace_id="not-admitted"),
        headers=headers,
    )
    assert response.status_code == 400, response.text


def test_submit_turn_happy_path_with_fake_port_and_mocked_turn(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, mutation=True)
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}

    def _fake_turn(settings, action, **kwargs):  # type: ignore[no-untyped-def]
        _ = settings, kwargs
        return ActionReceipt(
            status="accepted",
            client_action_id=action.client_action_id,
            action_digest="f" * 64,
            workspace_id=action.workspace.workspace_id,
            command_id="00000000-0000-4000-8000-0000000000aa",
            platform_session_id="managed-bff-1",
            mutation_enabled=True,
        )

    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        side_effect=_fake_turn,
    ):
        response = client.post(
            "/api/agent/workspace/submit-turn",
            json=_body(),
            headers=headers,
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["payload_ref"].startswith("payload:sha256:")
    assert payload["command_id"]
    assert "prompt" not in payload


def test_submit_turn_has_an_independent_owner_route_budget(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, mutation=True)
    client.app.state.services["owner_mutation_rate_limiter"] = (
        OwnerMutationRateLimiter(max_requests=1, window_seconds=60)
    )
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}
    receipt = ActionReceipt(
        status="accepted",
        client_action_id="intent-bff-rate-01",
        action_digest="d" * 64,
        workspace_id=PLATFORM_WORKSPACE_ID,
        command_id="00000000-0000-4000-8000-0000000000aa",
        platform_session_id="managed-bff-1",
        mutation_enabled=True,
    )
    body = _body(client_action_id="intent-bff-rate-01")

    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=receipt,
    ):
        first = client.post(
            "/api/agent/workspace/submit-turn",
            json=body,
            headers=headers,
        )
        limited = client.post(
            "/api/agent/workspace/submit-turn",
            json=body,
            headers=headers,
        )

    assert first.status_code == 200, first.text
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["detail"]["code"] == "mutation_rate_limited"
    assert boot["csrf"] not in limited.text


def test_act_still_rejects_prompt_field(tmp_path: Path) -> None:
    """``/act`` stays prompt-free: unknown fields → validation."""
    client = _client(tmp_path, mutation=True)
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}
    response = client.post(
        f"/api/workspace/{PLATFORM_WORKSPACE_ID}/act",
        json={
            "action": {
                "schema_version": 1,
                "kind": "conversation.turn",
                "client_action_id": "act-prompt-leak",
                "workspace": {"workspace_id": PLATFORM_WORKSPACE_ID},
                "managed_session_ref": "session:s1",
                "payload_ref": "payload:sha256:" + ("a" * 64),
                "payload_digest": "a" * 64,
                "prompt": "must-not-be-accepted",
            }
        },
        headers=headers,
    )
    # Exact-fields validation → 422 (or unavailable if mutation path differs).
    assert response.status_code in {422, 400, 503, 409}, response.text
    # Must not be a clean accepted turn carrying the prompt.
    if response.status_code == 200:
        assert response.json().get("status") != "accepted"


def test_v8_m2_bff_double_post_same_body_stable_payload(tmp_path: Path) -> None:
    """TC-V8-M1-01 BFF layer: double POST same body → stable payload identity."""
    client = _client(tmp_path, mutation=True)
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}
    body = _body(client_action_id="intent-bff-dbl-01")
    receipt = ActionReceipt(
        status="accepted",
        client_action_id=str(body["client_action_id"]),
        action_digest="d" * 64,
        workspace_id=str(body["workspace_id"]),
        command_id="00000000-0000-4000-8000-0000000000aa",
        platform_session_id="managed-bff-1",
        hermes_session_id="hermes-bff-1",
        mutation_enabled=True,
    )
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=receipt,
    ):
        r1 = client.post(
            "/api/agent/workspace/submit-turn", json=body, headers=headers
        )
        r2 = client.post(
            "/api/agent/workspace/submit-turn", json=body, headers=headers
        )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    j1, j2 = r1.json(), r2.json()
    assert j1["status"] == j2["status"] == "accepted"
    assert j1["payload_digest"] == j2["payload_digest"]
    assert j1["payload_ref"] == j2["payload_ref"]
    assert j1["client_action_id"] == j2["client_action_id"] == body["client_action_id"]
    # Fake port is process-local on app — single binding for client_intent_id.
    port = client.app.state.services["intent_payload_port"]
    assert len(port._store) == 1  # type: ignore[attr-defined]


def test_v8_m2_bff_same_id_different_prompt_409(tmp_path: Path) -> None:
    """TC-V8-M1-02 BFF layer: same client_action_id different prompt → 409."""
    client = _client(tmp_path, mutation=True)
    boot = _bootstrap(client, tmp_path)
    headers = {**_browser_headers(), CSRF_HEADER_NAME: boot["csrf"]}
    body_a = _body(client_action_id="intent-bff-conf-01", prompt="Reply with exactly: L2a-pong")
    body_b = _body(client_action_id="intent-bff-conf-01", prompt="Reply with exactly: OTHER")
    receipt = ActionReceipt(
        status="accepted",
        client_action_id="intent-bff-conf-01",
        action_digest="d" * 64,
        workspace_id=str(body_a["workspace_id"]),
        command_id="00000000-0000-4000-8000-0000000000bb",
        mutation_enabled=True,
    )
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=receipt,
    ) as turn:
        r1 = client.post(
            "/api/agent/workspace/submit-turn", json=body_a, headers=headers
        )
        r2 = client.post(
            "/api/agent/workspace/submit-turn", json=body_b, headers=headers
        )
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 409, r2.text
    detail = r2.json()["detail"]
    assert (
        detail["code"] in {"conflict", "intent_idempotency_conflict"}
        or "conflict" in str(detail).lower()
    )
    assert turn.call_count == 1
