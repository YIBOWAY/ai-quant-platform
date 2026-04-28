from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_factor_registry_list(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/factors")

    assert response.status_code == 200
    payload = response.json()
    factor_ids = {item["factor_id"] for item in payload["factors"]}
    assert {"momentum", "volatility", "liquidity", "rsi", "macd"}.issubset(factor_ids)


def test_factor_run_and_detail(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    run_response = client.post(
        "/api/factors/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "lookback": 3,
        },
    )

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["run_id"]
    assert run_payload["row_count"] > 0

    detail_response = client.get(f"/api/factors/{run_payload['run_id']}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["run_id"] == run_payload["run_id"]
    assert detail["factor_results"]
    assert detail["signals"]


def test_factor_detail_404_for_unknown_run(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/factors/does-not-exist")

    assert response.status_code == 404
    assert response.json()["safety"]["paper_trading"] is True
