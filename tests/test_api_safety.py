from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import reload_settings


def test_every_json_response_has_safety_footer(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    for path in ["/api/health", "/api/settings", "/api/factors", "/api/orders/submit"]:
        response = client.get(path)
        payload = response.json()
        assert "safety" in payload
        assert payload["safety"]["live_trading_enabled"] is False


def test_settings_masks_secret_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_TIINGO_API_TOKEN", "super-secret-token")
    reload_settings()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/settings")

    assert response.status_code == 200
    payload_text = response.text
    assert "super-secret-token" not in payload_text
    assert payload_text.count("***") >= 1


def test_forbidden_order_submit_route_does_not_exist(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post("/api/orders/submit", json={})

    assert response.status_code == 404
    assert response.json()["safety"]["dry_run"] is True
