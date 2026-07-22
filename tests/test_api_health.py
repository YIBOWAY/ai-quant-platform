import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)


def _local_settings(*, gateway_enabled: bool = False) -> Settings:
    """Isolate health tests from developer .env gateway/read/mutation flags."""
    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=gateway_enabled),
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
    )


def test_health_returns_safety_snapshot(tmp_path) -> None:
    client = TestClient(
        create_app(
            settings=_local_settings(),
            output_dir=tmp_path,
            bind_address="127.0.0.1",
        )
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["safety"]["dry_run"] is True
    assert payload["safety"]["paper_trading"] is True
    assert payload["safety"]["live_trading_enabled"] is False
    assert payload["safety"]["kill_switch"] is True
    assert payload["safety"]["bind_address"] == "127.0.0.1"
    assert payload["hermes_command_ledger"] == {
        "database_configured": False,
        "schema_ready": False,
        "schema_version": None,
        "workflow_binding_schema_ready": False,
        "workflow_binding_schema_version": None,
        "session_registry_schema_ready": False,
        "session_registry_schema_version": None,
        "agent_workspace_authorities_ready": False,
        "runtime_security_ready": False,
        "write_authority_ready": False,
        "research_binding_schema_ready": False,
        "research_binding_ready": False,
        "dark_dispatch_schema_ready": False,
        "dark_dispatch_ready": False,
        "mutation_enabled": False,
        "local_chat_write_ready": False,
        "composer_write_ready": False,
        "public_chat_write_ready": False,
        "chat_write_ready": False,
    }


def test_create_app_writes_runtime_log_file(tmp_path) -> None:
    client = TestClient(
        create_app(
            settings=_local_settings(),
            output_dir=tmp_path,
            bind_address="127.0.0.1",
        )
    )

    response = client.get("/api/health")

    assert response.status_code == 200
    assert (tmp_path / "_runtime" / "logs" / "backend.jsonl").exists()


def test_create_app_rejects_public_bind_without_confirmation(tmp_path) -> None:
    with pytest.raises(ValueError, match="0.0.0.0"):
        create_app(
            settings=_local_settings(),
            output_dir=tmp_path,
            bind_address="0.0.0.0",
        )


def test_create_app_accepts_public_bind_when_confirmed(tmp_path) -> None:
    # Public bind is only meaningful when Hermes gateway read integration is off;
    # gateway mode still requires loopback even with public-bind confirmation.
    app = create_app(
        settings=_local_settings(gateway_enabled=False),
        output_dir=tmp_path,
        bind_address="0.0.0.0",
        bind_public_confirmed=True,
    )
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["safety"]["bind_address"] == "0.0.0.0"
