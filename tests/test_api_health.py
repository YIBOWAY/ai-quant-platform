import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_health_returns_safety_snapshot(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

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
        "mutation_enabled": False,
    }


def test_create_app_writes_runtime_log_file(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert (tmp_path / "_runtime" / "logs" / "backend.jsonl").exists()


def test_create_app_rejects_public_bind_without_confirmation(tmp_path) -> None:
    with pytest.raises(ValueError, match="0.0.0.0"):
        create_app(output_dir=tmp_path, bind_address="0.0.0.0")


def test_create_app_accepts_public_bind_when_confirmed(tmp_path) -> None:
    app = create_app(
        output_dir=tmp_path,
        bind_address="0.0.0.0",
        bind_public_confirmed=True,
    )
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["safety"]["bind_address"] == "0.0.0.0"
