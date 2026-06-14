import pandas as pd
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, Settings
from quant_system.data.schema import normalize_ohlcv_dataframe


def _fake_tiingo_frame() -> pd.DataFrame:
    rows = []
    base_dates = [
        pd.Timestamp("2024-01-02", tz="UTC"),
        pd.Timestamp("2024-01-03", tz="UTC"),
        pd.Timestamp("2024-01-04", tz="UTC"),
        pd.Timestamp("2024-01-05", tz="UTC"),
        pd.Timestamp("2024-01-08", tz="UTC"),
    ]
    for index, timestamp in enumerate(base_dates):
        rows.extend(
            [
                {
                    "symbol": "SPY",
                    "timestamp": timestamp,
                    "open": 470.0 + index,
                    "high": 471.0 + index,
                    "low": 469.0 + index,
                    "close": 470.5 + index,
                    "volume": 1000 + (index * 10),
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(days=1),
                },
                {
                    "symbol": "QQQ",
                    "timestamp": timestamp,
                    "open": 400.0 + (index * 2),
                    "high": 401.0 + (index * 2),
                    "low": 399.0 + (index * 2),
                    "close": 400.5 + (index * 2),
                    "volume": 2000 + (index * 20),
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(days=1),
                },
            ]
        )
    return normalize_ohlcv_dataframe(
        pd.DataFrame(rows),
        provider="tiingo",
        interval="1d",
    )


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
            "provider": "sample",
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


def test_factor_run_does_not_create_per_run_duckdb(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/factors/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "sample",
            "lookback": 3,
        },
    )

    assert response.status_code == 200
    assert list(tmp_path.rglob("*.duckdb")) == []


def test_factor_run_records_single_symbol_warning(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    run_response = client.post(
        "/api/factors/run",
        json={
            "symbols": ["NVDA"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "sample",
            "lookback": 3,
            "quantiles": 3,
        },
    )

    assert run_response.status_code == 200
    payload = run_response.json()
    assert any("single symbol" in warning.lower() for warning in payload["warnings"])

    detail_response = client.get(f"/api/factors/{payload['run_id']}")
    assert detail_response.status_code == 200
    metadata = detail_response.json()["metadata"]
    assert metadata["warnings"] == payload["warnings"]


def test_factor_detail_404_for_unknown_run(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/factors/does-not-exist")

    assert response.status_code == 404
    assert response.json()["safety"]["paper_trading"] is True


def test_factor_runs_list_returns_latest_run_first(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    first = client.post(
        "/api/factors/run",
        json={
            "symbols": ["SPY"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "lookback": 3,
        },
    )
    second = client.post(
        "/api/factors/run",
        json={
            "symbols": ["QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "lookback": 5,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get("/api/factors/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"][0]["id"] == second.json()["run_id"]


def test_factor_run_uses_tiingo_when_requested(tmp_path, monkeypatch) -> None:
    settings = Settings(
        api_keys=ApiKeySettings(tiingo_api_token=SecretStr("test-tiingo-token"))
    )

    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        return _fake_tiingo_frame()

    monkeypatch.setattr(
        "quant_system.data.provider_factory.TiingoEODProvider.fetch_ohlcv",
        fake_fetch,
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/factors/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-08",
            "provider": "tiingo",
            "lookback": 3,
            "quantiles": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "tiingo"
    assert payload["signal_count"] > 0


def test_factor_lab_dashboard_returns_cross_sectional_and_timing_engines(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(
        "/api/factors/lab",
        params={
            "provider": "sample",
            "universe_id": "etf",
            "symbol": "QQQ",
            "start": "2024-01-02",
            "end": "2024-03-29",
            "lookback": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["benchmark_symbol"] == "QQQ"
    assert payload["universe"]["id"] == "etf"
    assert payload["guardrails"]["exploratory_only"] is True
    assert payload["guardrails"]["walk_forward"]["enabled"] is True
    assert payload["guardrails"]["leakage_audit"]["status"] == "basic_passed"
    assert payload["cache"]["path"]

    cross_rows = payload["cross_sectional"]["rows"]
    timing_rows = payload["timing"]["rows"]
    factor_ids = {item["factor_id"] for item in payload["factors"]}
    assert factor_ids
    assert factor_ids.issubset({row["factor_id"] for row in cross_rows})
    assert factor_ids.issubset({row["factor_id"] for row in timing_rows})
    assert all("coverage" in row for row in cross_rows)
    assert all(
        "sharpe" in row and "max_drawdown" in row and "win_rate" in row
        for row in timing_rows
    )


def test_factor_lab_dashboard_reuses_cached_result(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))
    params = {
        "provider": "sample",
        "universe_id": "etf",
        "symbol": "QQQ",
        "benchmark_symbol": "QQQ",
        "start": "2024-01-02",
        "end": "2024-03-29",
        "lookback": 3,
    }

    refreshed = client.get("/api/factors/lab", params={**params, "force_refresh": True})
    cached = client.get("/api/factors/lab", params=params)

    assert refreshed.status_code == 200
    assert cached.status_code == 200
    assert refreshed.json()["cache"]["status"] == "recomputed"
    assert cached.json()["cache"]["status"] == "cached"
