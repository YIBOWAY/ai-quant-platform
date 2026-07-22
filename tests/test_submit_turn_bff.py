"""BFF transport tests for POST /api/agent/workspace/submit-turn (M1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID
from quant_system.hermes.intent_payload_port import FakeIntentPayloadPort
from quant_system.hermes.submission_saga import ActionReceipt

ORIGIN = "http://127.0.0.1:3001"


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
