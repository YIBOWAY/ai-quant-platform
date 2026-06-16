from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings


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


def test_configured_cors_allows_alternate_e2e_frontend_port(tmp_path) -> None:
    client = TestClient(
        create_app(
            settings=Settings(api_cors_origins=["http://127.0.0.1:3002"]),
            output_dir=tmp_path,
        )
    )

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:3002",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3002"
