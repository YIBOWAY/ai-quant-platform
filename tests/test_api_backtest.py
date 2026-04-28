from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_backtest_run_list_and_detail(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    run_response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert run_response.status_code == 200
    run_id = run_response.json()["run_id"]

    list_response = client.get("/api/backtests")
    assert list_response.status_code == 200
    assert run_id in {item["id"] for item in list_response.json()["backtests"]}

    detail_response = client.get(f"/api/backtests/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["metrics"]["total_return"] is not None
    assert detail["equity_curve"]
    assert detail["orders"]


def test_benchmark_returns_equity_curve(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(
        "/api/benchmark",
        params={"symbol": "SPY", "start": "2024-01-02", "end": "2024-01-12"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "SPY"
    assert payload["equity_curve"]
    assert payload["equity_curve"][0]["equity"] == 1.0
    assert payload["metrics"]["total_return"] > 0


def test_backtest_detail_404_for_unknown_run(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/backtests/does-not-exist")

    assert response.status_code == 404
    assert response.json()["safety"]["live_trading_enabled"] is False
