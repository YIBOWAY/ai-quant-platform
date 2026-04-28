from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_symbols_returns_sample_symbols_when_no_local_cache(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/symbols")

    assert response.status_code == 200
    payload = response.json()
    assert {"SPY", "QQQ"}.issubset(set(payload["symbols"]))
    assert payload["source"] == "sample"
    assert payload["safety"]["live_trading_enabled"] is False


def test_ohlcv_returns_sample_timeseries(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(
        "/api/ohlcv",
        params={"symbol": "SPY", "start": "2024-01-02", "end": "2024-01-08"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "SPY"
    assert payload["rows"]
    assert {"timestamp", "open", "high", "low", "close", "volume"}.issubset(
        payload["rows"][0]
    )


def test_ohlcv_rejects_missing_symbol(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/ohlcv", params={"start": "2024-01-02", "end": "2024-01-08"})

    assert response.status_code == 422
    assert response.json()["safety"]["dry_run"] is True
