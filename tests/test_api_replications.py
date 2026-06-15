from __future__ import annotations

import json

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
    assert payload["run_id"].startswith("replication-")
    run_dir = tmp_path / "api_runs" / "replications" / payload["run_id"]
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert metadata["run_id"] == payload["run_id"]
    assert metadata["result_type"] == "replication"
    assert metadata["paths"]["result"] == str(run_dir / "result.json")
    assert result["run_id"] == payload["run_id"]
    assert result["metrics"]["observation_months"] == payload["metrics"]["observation_months"]
    detail_response = client.get(
        f"/api/replications/reversal-momentum/{payload['run_id']}"
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["run_id"] == payload["run_id"]
    assert detail_payload["metadata"]["run_id"] == payload["run_id"]
    assert (
        detail_payload["result"]["metrics"]["observation_months"]
        == payload["metrics"]["observation_months"]
    )
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


def test_reversal_momentum_replication_detail_404_for_unknown_run(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/replications/reversal-momentum/replication-missing")

    assert response.status_code == 404
