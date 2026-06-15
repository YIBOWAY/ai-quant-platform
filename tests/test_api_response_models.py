from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_read_only_market_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/health": "HealthResponse",
        "/api/symbols": "SymbolsResponse",
        "/api/ohlcv": "OHLCVResponse",
        "/api/benchmark": "BenchmarkResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "data_provider" in components["HealthResponse"]["properties"]
    assert "futu_opend" in components["HealthResponse"]["properties"]
    assert "database" in components["HealthResponse"]["properties"]
    assert "source" in components["OHLCVResponse"]["properties"]
    assert "source" in components["BenchmarkResponse"]["properties"]
