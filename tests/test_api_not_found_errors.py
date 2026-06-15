import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app


@pytest.mark.parametrize(
    ("path", "resource", "missing_id"),
    [
        ("/api/backtests/missing-run", "backtest", "missing-run"),
        ("/api/factors/missing-run", "factor_run", "missing-run"),
        ("/api/experiments/missing-run", "experiment", "missing-run"),
        ("/api/paper/missing-run", "paper_run", "missing-run"),
        ("/api/agent/candidates/missing-run", "agent_candidate", "missing-run"),
        (
            "/api/replications/reversal-momentum/replication-missing",
            "reversal_momentum_replication",
            "replication-missing",
        ),
        (
            "/api/prediction-market/results/missing-run",
            "prediction_market_result",
            "missing-run",
        ),
        (
            "/api/prediction-market/timeseries-backtest/missing-run",
            "prediction_market_timeseries_result",
            "missing-run",
        ),
    ],
)
def test_detail_not_found_errors_use_standard_detail(
    tmp_path,
    path: str,
    resource: str,
    missing_id: str,
) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(path)

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "not_found"
    assert detail["resource"] == resource
    assert detail["id"] == missing_id
    assert "not found" in detail["message"].lower()
