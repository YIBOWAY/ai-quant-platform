from pathlib import Path

from fastapi.testclient import TestClient

import quant_system.api.routes.prediction_market as prediction_market_routes
from quant_system.api.server import create_app
from quant_system.prediction_market.data.polymarket_readonly import PolymarketProviderError


def test_prediction_market_markets_returns_sample_data(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/prediction-market/markets")

    assert response.status_code == 200
    payload = response.json()
    assert payload["markets"]
    assert payload["order_books"]
    assert payload["safety"]["dry_run"] is True


def test_prediction_market_markets_accepts_provider_param(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/prediction-market/markets", params={"provider": "sample"})

    assert response.status_code == 200
    assert response.json()["provider"] == "sample"


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
    assert "credential" in response.json()["detail"].lower()


def test_prediction_market_rejects_generic_credential_request(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/prediction-market/scan",
        json={"extra": {"api_key": "not-allowed"}},
    )

    assert response.status_code == 400
    assert "credential" in response.json()["detail"].lower()


def test_prediction_market_backtest_writes_report_and_charts(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/prediction-market/backtest",
        json={"provider": "sample", "min_edge_bps": 200, "fee_bps": 0},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"]
    assert payload["metrics"]["opportunity_count"] >= 1
    assert payload["chart_index"]["charts"]
    assert payload["report_path"].endswith("report.md")

    detail = client.get(f"/api/prediction-market/results/{payload['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["result"]["metrics"]["opportunity_count"] >= 1


def test_prediction_market_provider_error_maps_to_frontend_readable_response(
    tmp_path,
    monkeypatch,
) -> None:
    class FailingProvider:
        def list_markets(self, limit=50):
            raise PolymarketProviderError("provider_timeout", "read-only timeout")

        def get_order_books(self, market_id: str):
            return []

    monkeypatch.setattr(
        prediction_market_routes,
        "build_prediction_market_provider",
        lambda settings, requested=None: (FailingProvider(), "polymarket"),
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/prediction-market/markets", params={"provider": "polymarket"})

    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "provider_timeout"
    assert "Traceback" not in str(response.json())


def test_prediction_market_dry_arbitrage_rejects_live_api_key_request(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/prediction-market/dry-arbitrage",
        json={"polymarket_api_key": "secret"},
    )

    assert response.status_code == 400
    assert "credential" in response.json()["detail"].lower()
