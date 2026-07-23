from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY

import pytest
from fastapi.testclient import TestClient

from quant_system.api.dependencies import get_hermes_api_read_client
from quant_system.api.routes import hermes as hermes_routes
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
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID
from quant_system.hermes.submission_saga import ActionReceipt

ORIGIN = "http://127.0.0.1:3001"
SESSION_ID = "discord-session-1"


class _Gateway:
    pass


def _browser_headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "Host": "testserver",
    }


def _settings(*, mutation: bool) -> Settings:
    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=True),
        local_mutation=LocalMutationSettings(
            enabled=mutation,
            composer_open=mutation,
        ),
        api_cors_origins=[ORIGIN],
    )


def _client(tmp_path: Path, *, mutation: bool) -> TestClient:
    app = create_app(
        settings=_settings(mutation=mutation),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    app.dependency_overrides[get_hermes_api_read_client] = _Gateway
    return TestClient(app, base_url="http://127.0.0.1")


def _bootstrap(client: TestClient, tmp_path: Path) -> str:
    token = issue_bootstrap_token(tmp_path)
    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text
    return str(response.json()["csrf_token"])


def _body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "client_action_id": "fork-browser-1",
        "fork_point": "message:41",
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _admit_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        hermes_routes,
        "composer_readiness_snapshot",
        lambda _settings, *, fresh=False: {
            "chat_write_ready": True,
            "release_blockers": [],
        },
    )


def test_external_fork_route_requires_owner_and_csrf(tmp_path: Path) -> None:
    client = _client(tmp_path, mutation=True)
    unauthenticated = client.post(
        f"/api/hermes/sessions/{SESSION_ID}/forks-to-managed",
        json=_body(),
        headers=_browser_headers(),
    )
    assert unauthenticated.status_code in {401, 403}

    _bootstrap(client, tmp_path)
    no_csrf = client.post(
        f"/api/hermes/sessions/{SESSION_ID}/forks-to-managed",
        json=_body(),
        headers=_browser_headers(),
    )
    assert no_csrf.status_code == 403


def test_external_fork_route_stays_closed_when_local_mutation_is_off(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, mutation=False)
    csrf = _bootstrap(client, tmp_path)

    response = client.post(
        f"/api/hermes/sessions/{SESSION_ID}/forks-to-managed",
        json=_body(),
        headers={**_browser_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


def test_external_fork_route_requires_effective_release_before_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, mutation=True)
    csrf = _bootstrap(client, tmp_path)
    monkeypatch.setattr(
        hermes_routes,
        "composer_readiness_snapshot",
        lambda _settings, *, fresh=False: {
            "chat_write_ready": False,
            "release_blockers": ["release_evidence_digest_mismatch"],
        },
    )
    monkeypatch.setattr(
        hermes_routes,
        "submit_external_session_fork",
        lambda *_args, **_kwargs: pytest.fail("service must remain closed"),
    )

    response = client.post(
        f"/api/hermes/sessions/{SESSION_ID}/forks-to-managed",
        json=_body(),
        headers={**_browser_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "agent_v02_release_not_ready",
        "message": "Agent v0.2 durable release admission is closed",
        "blockers": ["release_evidence_digest_mismatch"],
        "mutation_enabled": True,
    }


def test_external_fork_route_delegates_only_selected_session_and_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, mutation=True)
    csrf = _bootstrap(client, tmp_path)
    calls: list[dict[str, object]] = []

    def submit(_settings: object, gateway: object, **kwargs: object) -> ActionReceipt:
        calls.append({"gateway": gateway, **kwargs})
        return ActionReceipt(
            status="accepted",
            client_action_id=str(kwargs["client_action_id"]),
            action_digest="a" * 64,
            workspace_id=PLATFORM_WORKSPACE_ID,
            platform_session_id="wm_child",
            hermes_session_id="web_" + ("b" * 40),
            mutation_enabled=True,
        )

    monkeypatch.setattr(
        hermes_routes,
        "submit_external_session_fork",
        submit,
    )

    response = client.post(
        f"/api/hermes/sessions/{SESSION_ID}/forks-to-managed",
        json=_body(),
        headers={**_browser_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "accepted"
    assert response.json()["session_ref"] == "session:wm_child"
    assert response.json()["hermes_session_id"] == "web_" + ("b" * 40)
    assert calls == [
        {
            "gateway": ANY,
            "hermes_session_id": SESSION_ID,
            "fork_point": "message:41",
            "client_action_id": "fork-browser-1",
            "mutation_enabled": True,
            "actor_owner_user_id": ROOT_USER_ID,
        }
    ]


@pytest.mark.parametrize(
    "body",
    [
        _body(fork_point="message:0"),
        _body(fork_point="cursor:41"),
        _body(extra="browser-must-not-supply-policy"),
    ],
)
def test_external_fork_route_rejects_non_exact_or_extra_body(
    tmp_path: Path,
    body: dict[str, object],
) -> None:
    client = _client(tmp_path, mutation=True)
    csrf = _bootstrap(client, tmp_path)

    response = client.post(
        f"/api/hermes/sessions/{SESSION_ID}/forks-to-managed",
        json=body,
        headers={**_browser_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 422


def test_external_fork_route_is_rate_limited_by_authenticated_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, mutation=True)
    client.app.state.services["owner_mutation_rate_limiter"] = OwnerMutationRateLimiter(
        max_requests=1, window_seconds=60
    )
    csrf = _bootstrap(client, tmp_path)
    monkeypatch.setattr(
        hermes_routes,
        "submit_external_session_fork",
        lambda *_args, **kwargs: ActionReceipt(
            status="accepted",
            client_action_id=str(kwargs["client_action_id"]),
            action_digest="a" * 64,
            workspace_id=PLATFORM_WORKSPACE_ID,
            platform_session_id="wm_child",
            hermes_session_id="web_" + ("b" * 40),
            mutation_enabled=True,
        ),
    )
    headers = {**_browser_headers(), CSRF_HEADER_NAME: csrf}
    route = f"/api/hermes/sessions/{SESSION_ID}/forks-to-managed"

    assert client.post(route, json=_body(), headers=headers).status_code == 200
    limited = client.post(route, json=_body(), headers=headers)

    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "mutation_rate_limited"
