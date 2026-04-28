from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_prediction_market_markets_returns_sample_data(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/prediction-market/markets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["markets"]
    assert payload["order_books"]
    assert payload["safety"]["dry_run"] is True


def test_prediction_market_scan_and_dry_arbitrage(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    scan_response = client.post("/api/prediction-market/scan", json={})
    assert scan_response.status_code == 200
    assert scan_response.json()["candidates"]

    dry_response = client.post("/api/prediction-market/dry-arbitrage", json={})
    assert dry_response.status_code == 200
    payload = dry_response.json()
    assert payload["proposed_trades"]
    assert all(item["dry_run"] is True for item in payload["proposed_trades"])
    assert list(Path(tmp_path, "api_runs", "prediction_market", "proposals").glob("*.json"))
    assert not Path(tmp_path, "api_runs", "prediction_market", "orders").exists()


def test_prediction_market_rejects_live_api_key_request(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/prediction-market/scan",
        json={"polymarket_api_key": "secret"},
    )

    assert response.status_code == 400
    assert "Polymarket API key" in response.json()["detail"]


def test_prediction_market_dry_arbitrage_rejects_live_api_key_request(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/prediction-market/dry-arbitrage",
        json={"polymarket_api_key": "secret"},
    )

    assert response.status_code == 400
    assert "Polymarket API key" in response.json()["detail"]
