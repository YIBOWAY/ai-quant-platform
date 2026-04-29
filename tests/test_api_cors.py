from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_default_cors_allows_frontend_port_3001(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:3001",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3001"
