from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, DataSettings, Settings
from quant_system.data.schema import normalize_ohlcv_dataframe


def _isolated_data_settings(tmp_path) -> DataSettings:
    return DataSettings(
        data_dir=tmp_path / "data",
        parquet_dir=tmp_path / "parquet",
        duckdb_path=tmp_path / "quant_system.duckdb",
        reports_dir=tmp_path / "reports",
    )


def _fake_tiingo_frame() -> pd.DataFrame:
    rows = []
    base_dates = [
        pd.Timestamp("2024-01-02", tz="UTC"),
        pd.Timestamp("2024-01-03", tz="UTC"),
        pd.Timestamp("2024-01-04", tz="UTC"),
        pd.Timestamp("2024-01-05", tz="UTC"),
        pd.Timestamp("2024-01-08", tz="UTC"),
        pd.Timestamp("2024-01-09", tz="UTC"),
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
                    "close": 470.8 + index,
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
                    "close": 400.9 + (index * 2),
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


def test_backtest_run_list_and_detail(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    run_response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "sample",
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
    assert detail["benchmark"]["symbol"] == "SPY"
    assert detail["benchmark"]["source"] == "sample"
    assert detail["benchmark"]["equity_curve"]
    assert detail["benchmark"]["equity_curve"][0]["equity"] == 1.0
    assert detail["benchmark"]["metrics"]["total_return"] is not None
    timings = detail["metadata"]["timings_ms"]
    assert set(timings) == {"data_fetch", "engine", "persist", "total"}
    assert all(isinstance(value, int | float) for value in timings.values())
    assert all(value >= 0 for value in timings.values())
    assert Path(
        tmp_path,
        "api_runs",
        "backtests",
        run_id,
        "backtests",
        "benchmark_curve.parquet",
    ).exists()
    assert "benchmark_curve" in detail["metadata"]["paths"]
    assert detail["orders"]


def test_backtest_run_does_not_create_per_run_duckdb(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "sample",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    assert list(tmp_path.rglob("*.duckdb")) == []


def test_backtest_run_rejects_explicit_unavailable_provider(tmp_path) -> None:
    settings = Settings(api_keys=ApiKeySettings(tiingo_api_token=None))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "tiingo",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_unavailable"
    assert not (tmp_path / "api_runs" / "backtests").exists()


def test_backtest_run_rejects_explicit_provider_fetch_failure(
    tmp_path,
    monkeypatch,
) -> None:
    settings = Settings(
        data=_isolated_data_settings(tmp_path),
        api_keys=ApiKeySettings(tiingo_api_token=SecretStr("test-tiingo-token"))
    )

    def fail_fetch(self, symbols, *, start, end, interval="1d"):
        raise RuntimeError("tiingo offline")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.TiingoEODProvider.fetch_ohlcv",
        fail_fetch,
    )
    client = TestClient(
        create_app(settings=settings, output_dir=tmp_path),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "tiingo",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "provider_unavailable"
    assert not (tmp_path / "api_runs" / "backtests").exists()


def test_backtest_run_records_single_symbol_no_trade_warning(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["META"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "sample",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    warnings = [warning.lower() for warning in payload["warnings"]]
    assert any("single symbol" in warning for warning in warnings)
    assert any("no simulated trades" in warning for warning in warnings)
    assert payload["trade_count"] == 0


def test_backtest_run_rejects_sector_cap_without_sector_map(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "sample",
            "lookback": 3,
            "top_n": 1,
            "sector_cap": 0.5,
        },
    )

    assert response.status_code == 422
    assert "sector_map" in response.text


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


def test_benchmark_rejects_unknown_explicit_provider(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get(
        "/api/benchmark",
        params={
            "symbol": "SPY",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "polygon",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "provider_unavailable"
    assert payload["detail"]["provider"] == "polygon"


def test_backtest_detail_404_for_unknown_run(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/backtests/does-not-exist")

    assert response.status_code == 404
    assert response.json()["safety"]["live_trading_enabled"] is False


def test_backtest_list_returns_latest_run_first(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    first = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "lookback": 3,
            "top_n": 1,
        },
    )
    second = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "lookback": 5,
            "top_n": 1,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get("/api/backtests")

    assert response.status_code == 200
    payload = response.json()
    assert payload["backtests"][0]["id"] == second.json()["run_id"]


def test_backtest_run_uses_tiingo_when_requested(tmp_path, monkeypatch) -> None:
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
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-09",
            "provider": "tiingo",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "tiingo"
    assert payload["metrics"]["total_return"] is not None


def test_backtest_run_accepts_strategy_universe_factors_and_benchmark(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "universe_id": "etf",
            "start": "2024-01-02",
            "end": "2024-02-15",
            "provider": "sample",
            "strategy_id": "cross_sectional_top_n",
            "factor_ids": ["momentum", "volatility"],
            "weights": {"momentum": 1.0, "volatility": 0.5},
            "benchmark_symbol": "SPY",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    request = payload["request"]
    assert request["benchmark_symbol"] == "SPY"
    assert request["strategy_id"] == "cross_sectional_top_n"
    assert request["universe_id"] == "etf"
    assert request["factor_ids"] == ["momentum", "volatility"]
    assert request["weights"] == {"momentum": 1.0, "volatility": 0.5}
    assert "QQQ" in request["symbols"]
    assert payload["metrics"]["total_return"] is not None


def test_backtest_run_metadata_records_persisted_benchmark(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "benchmark_symbol": "QQQ",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["benchmark"]["symbol"] == "QQQ"
    assert payload["benchmark"]["source"] == "sample"
    assert payload["benchmark"]["metrics"]["total_return"] is not None
    assert payload["paths"]["benchmark_curve"].endswith("benchmark_curve.parquet")


def test_backtest_benchmark_symbol_is_not_added_to_trading_universe(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "benchmark_symbol": "SPY",
            "lookback": 3,
            "top_n": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["symbols"] == ["QQQ"]
    detail = client.get(f"/api/backtests/{payload['run_id']}").json()
    position_symbols = {
        str(row["symbol"]).upper()
        for row in detail["positions"]
        if "symbol" in row
    }
    assert "SPY" not in position_symbols


def test_backtest_run_accepts_order_execution_constraints(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/backtests/run",
        json={
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "sample",
            "benchmark_symbol": "SPY",
            "lookback": 3,
            "top_n": 1,
            "initial_cash": 1050,
            "min_order_value": 250,
            "whole_share_orders": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request"]["min_order_value"] == 250
    assert payload["request"]["whole_share_orders"] is True

    detail = client.get(f"/api/backtests/{payload['run_id']}").json()
    assert detail["orders"]
    for row in detail["orders"]:
        assert float(row["quantity"]).is_integer()
