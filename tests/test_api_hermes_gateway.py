from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from quant_system.api.dependencies import get_hermes_api_read_client
from quant_system.api.server import create_app
from quant_system.config.settings import HermesGatewaySettings, LocalMutationSettings, Settings


class _FakeHermesReadClient:
    def capabilities(self) -> dict:
        return {
            "model": "codex-local",
            "features": {
                "session_resources": True,
                "run_submission": True,
                "run_events_sse": True,
                "run_events_snapshot": True,
                "run_status": True,
                "run_approval_response": True,
                "run_stop": True,
            },
        }

    def list_sessions(self, *, limit: int, offset: int) -> dict:
        return {
            "data": [
                {
                    "id": "s-1",
                    "title": "AAPL research",
                    "source": "api_server",
                    "model": "codex-local",
                    "message_count": 2,
                    "last_active": "2026-07-15T06:00:00Z",
                    "preview": "Review AAPL",
                    "parent_session_id": None,
                    "ended_at": None,
                }
            ],
            "limit": limit,
            "offset": offset,
            "has_more": False,
        }

    def session_detail(self, session_id: str) -> dict:
        return {
            "id": session_id,
            "title": "AAPL research",
            "source": "api_server",
            "model": "codex-local",
            "message_count": 2,
            "last_active": "2026-07-15T06:00:00Z",
            "preview": "Review AAPL",
            "parent_session_id": None,
            "ended_at": None,
        }

    def session_messages(self, session_id: str) -> dict:
        return {
            "session_id": session_id,
            "data": [
                {"id": "1", "role": "user", "content": "hello", "timestamp": None},
                {"id": "2", "role": "assistant", "content": "hi", "timestamp": None},
            ],
            "omitted_message_count": 0,
        }


class _NoSessionResourcesClient(_FakeHermesReadClient):
    def __init__(self) -> None:
        self.session_reads = 0

    def capabilities(self) -> dict:
        return {
            "model": "codex-local",
            "features": {"session_resources": False},
        }

    def list_sessions(self, *, limit: int, offset: int) -> dict:
        self.session_reads += 1
        raise AssertionError("session endpoint must not be called without capability")


def test_gateway_endpoints_fail_closed_when_integration_disabled() -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(enabled=False),
    )
    with TestClient(create_app(settings=settings)) as client:
        gateway = client.get("/api/hermes/gateway")
        sessions = client.get("/api/hermes/sessions")

    assert gateway.status_code == 200
    assert gateway.json()["read_status"] == "unavailable"
    assert gateway.json()["connected"] is False
    assert gateway.json()["chat_write_ready"] is False
    assert "integration_disabled" in gateway.json()["blockers"]
    assert "hermes_gateway_disabled" in gateway.json()["upstream_blockers"]
    assert "local_mutation_disabled" in gateway.json()["platform_delivery_blockers"]
    assert sessions.status_code == 200
    assert sessions.json()["read_status"] == "unavailable"
    assert sessions.json()["sessions"] == []


def test_gateway_endpoints_expose_only_sanitized_read_models() -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        # api_key_file must stay None: BaseSettings loads QS_HERMES_GATEWAY_* from
        # a developer's .env even under explicit kwarg construction, and a real key
        # file would let the default durable-capability probe reach the live
        # gateway — defeating this test's hermetic "probe unavailable" contract.
        hermes_gateway=HermesGatewaySettings(enabled=True, api_key_file=None),
    )
    app = create_app(settings=settings, bind_address="127.0.0.1")
    app.dependency_overrides[get_hermes_api_read_client] = _FakeHermesReadClient

    with TestClient(app, base_url="http://127.0.0.1") as client:
        gateway = client.get("/api/hermes/gateway")
        sessions = client.get("/api/hermes/sessions?limit=5&offset=0")
        detail = client.get("/api/hermes/sessions/s-1")
        messages = client.get("/api/hermes/sessions/s-1/messages")

    assert gateway.status_code == 200
    assert gateway.json()["read_status"] == "available"
    assert gateway.json()["connected"] is True
    assert gateway.json()["chat_write_ready"] is False
    assert "active_release_stamp_missing" in gateway.json()["blockers"]
    # The read-client override proves this endpoint's session surface only. The
    # durable release gate owns an independent capability probe and must remain
    # unavailable in this hermetic test.
    assert "hermes_durable_capability_unavailable" in gateway.json()["upstream_blockers"]
    assert gateway.json()["platform_delivery_blockers"]
    assert set(gateway.json()["upstream_blockers"]).issubset(gateway.json()["blockers"])
    assert set(gateway.json()["platform_delivery_blockers"]).issubset(gateway.json()["blockers"])
    assert sessions.json()["sessions"][0]["id"] == "s-1"
    assert detail.json()["session"]["title"] == "AAPL research"
    assert detail.json()["fork_context"] == {
        "eligible": False,
        "source_channel": None,
        "reason_code": "source_session_not_external",
    }
    assert messages.json()["messages"][1]["content"] == "hi"
    raw = json_bytes = messages.content + gateway.content
    assert b"authorization" not in raw.lower()
    assert b"api_key" not in raw.lower()
    assert json_bytes


def test_gateway_query_bounds_are_enforced_without_calling_upstream() -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(enabled=True),
    )
    app = create_app(settings=settings, bind_address="127.0.0.1")
    app.dependency_overrides[get_hermes_api_read_client] = _FakeHermesReadClient
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/hermes/sessions?limit=0").status_code == 422
        assert client.get("/api/hermes/sessions?limit=201").status_code == 422
        assert client.get("/api/hermes/sessions?offset=-1").status_code == 422


@pytest.mark.parametrize("bind_address", ["0.0.0.0", "::", "192.168.1.25"])
def test_gateway_read_integration_rejects_non_loopback_platform_bind(
    bind_address: str,
) -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(enabled=True),
    )

    with pytest.raises(ValueError, match="loopback"):
        create_app(
            settings=settings,
            bind_address=bind_address,
            bind_public_confirmed=True,
        )


def test_disabled_gateway_ignores_invalid_endpoint_configuration() -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(
            enabled=False,
            base_url="http://localhost:8642",
        ),
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/api/hermes/gateway")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"


def test_enabled_gateway_rejects_invalid_endpoint_at_startup() -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(
            enabled=True,
            base_url="http://localhost:8642",
        ),
    )

    with pytest.raises(ValueError, match="invalid_endpoint"):
        create_app(settings=settings, bind_address="127.0.0.1")


@pytest.mark.parametrize("session_id", ["x" * 257, "parent..child", "C:drive"])
def test_gateway_session_routes_reject_unsafe_ids_before_echoing(
    session_id: str,
) -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(enabled=False),
    )

    with TestClient(create_app(settings=settings)) as client:
        response = client.get(f"/api/hermes/sessions/{session_id}/messages")

    assert response.status_code == 422


def test_enabled_gateway_requires_explicit_bind_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QS_API_BIND_ADDRESS", raising=False)
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(enabled=True),
    )

    with pytest.raises(ValueError, match="explicit loopback bind"):
        create_app(settings=settings)


def test_gateway_request_rejects_non_loopback_actual_server_scope() -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(enabled=True),
    )
    app = create_app(settings=settings, bind_address="127.0.0.1")
    app.dependency_overrides[get_hermes_api_read_client] = _FakeHermesReadClient

    with TestClient(app, base_url="http://192.168.1.25") as client:
        response = client.get("/api/hermes/sessions")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "platform_socket_not_loopback"


def test_session_route_refuses_upstream_without_session_resources_capability() -> None:
    settings = Settings(
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        hermes_gateway=HermesGatewaySettings(enabled=True),
    )
    app = create_app(settings=settings, bind_address="127.0.0.1")
    upstream = _NoSessionResourcesClient()
    app.dependency_overrides[get_hermes_api_read_client] = lambda: upstream

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/hermes/sessions")

    assert response.status_code == 200
    assert response.json()["read_status"] == "unavailable"
    assert response.json()["warnings"][0]["code"] == "session_resources_unavailable"
    assert upstream.session_reads == 0
