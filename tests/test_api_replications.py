from __future__ import annotations

from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_reversal_momentum_replication_api_runs_with_sample_data(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/replications/reversal-momentum/run",
        json={
            "symbols": ["SPY", "QQQ", "IWM", "DIA"],
            "start": "2023-01-01",
            "end": "2025-12-31",
            "provider": "sample",
            "top_n": 1,
            "initial_cash": 1.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "sample"
    assert payload["paper"]["doi"] == "10.1093/rfs/hhaf057"
    assert payload["metrics"]["observation_months"] > 0
    assert payload["equity_curve"]
    assert payload["safety"]["live_trading_enabled"] is False


def test_reversal_momentum_replication_api_validates_symbols(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/replications/reversal-momentum/run",
        json={
            "symbols": ["SPY"],
            "start": "2023-01-01",
            "end": "2025-12-31",
            "provider": "sample",
        },
    )

    assert response.status_code == 422
