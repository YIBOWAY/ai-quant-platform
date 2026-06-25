import json
import time
from pathlib import Path
from threading import Event

import pandas as pd
from fastapi.testclient import TestClient
from pydantic import SecretStr

from quant_system.api.server import create_app
from quant_system.backtest.pipeline import BacktestCancelledError
from quant_system.config.settings import ApiKeySettings, BacktestJobSettings, DataSettings, Settings
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


def _wait_for_job_status(client: TestClient, run_id: str, statuses: set[str]) -> dict:
    for _ in range(100):
        response = client.get(f"/api/backtests/jobs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in statuses:
            return payload
        time.sleep(0.05)
    raise AssertionError(f"async backtest {run_id} did not reach {statuses}")


def test_backtest_run_accepts_async_job_when_enabled(tmp_path, monkeypatch) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))
    release = Event()

    def slow_backtest(*args, **kwargs):
        release.wait(timeout=2)
        raise RuntimeError("released test job")

    monkeypatch.setattr("quant_system.api.jobs.backtest_jobs.execute_backtest", slow_backtest)
    try:
        with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
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

            assert response.status_code == 202
            payload = response.json()
            assert payload["kind"] == "backtest"
            assert payload["status"] == "queued"
            assert payload["run_id"].startswith("backtest-")
            assert payload["poll_url"] == f"/api/backtests/jobs/{payload['run_id']}"
            metadata_path = (
                tmp_path / "api_runs" / "backtests" / payload["run_id"] / "metadata.json"
            )
            assert json.loads(metadata_path.read_text(encoding="utf-8"))["status"] in {
                "queued",
                "running",
            }
    finally:
        release.set()


def test_backtest_async_job_polling_reaches_completed(tmp_path) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))
    with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
        response = client.post(
            "/api/backtests/run",
            json={
                "symbols": ["SPY", "QQQ"],
                "start": "2024-01-02",
                "end": "2024-01-12",
                "provider": "sample",
                "lookback": 3,
                "top_n": 1,
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]

        payload = _wait_for_job_status(client, run_id, {"completed"})

        assert payload["run_id"] == run_id
        assert payload["result_url"] == f"/api/backtests/{run_id}"
        detail = client.get(f"/api/backtests/{run_id}")
        assert detail.status_code == 200


def test_backtest_async_job_can_cancel_queued_job(tmp_path, monkeypatch) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True, max_workers=1))
    release = Event()

    def blocking_backtest(*args, **kwargs):
        release.wait(timeout=2)
        raise RuntimeError("blocker released")

    monkeypatch.setattr("quant_system.api.jobs.backtest_jobs.execute_backtest", blocking_backtest)
    try:
        with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
            first = client.post(
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
            first_run_id = first.json()["run_id"]
            _wait_for_job_status(client, first_run_id, {"running"})

            second = client.post(
                "/api/backtests/run",
                json={
                    "symbols": ["IWM", "DIA"],
                    "start": "2024-01-02",
                    "end": "2024-02-15",
                    "provider": "sample",
                    "lookback": 3,
                    "top_n": 1,
                },
            )
            run_id = second.json()["run_id"]

            cancel = client.post(f"/api/backtests/jobs/{run_id}/cancel")

            assert cancel.status_code == 200
            assert cancel.json()["status"] == "cancelled"
            assert client.get(f"/api/backtests/jobs/{run_id}").json()["status"] == "cancelled"
    finally:
        release.set()


def test_backtest_async_job_can_cancel_running_job(tmp_path, monkeypatch) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))
    started = Event()

    def cancellable_backtest(*args, **kwargs):
        cancel_event = kwargs["cancel_event"]
        started.set()
        for _ in range(100):
            if cancel_event.is_set():
                raise BacktestCancelledError("test cancellation observed")
            time.sleep(0.01)
        raise AssertionError("cancel_event was not set")

    monkeypatch.setattr(
        "quant_system.api.jobs.backtest_jobs.execute_backtest",
        cancellable_backtest,
    )
    with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
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
        run_id = response.json()["run_id"]
        assert started.wait(timeout=2)
        _wait_for_job_status(client, run_id, {"running"})

        cancel = client.post(f"/api/backtests/jobs/{run_id}/cancel")

        assert cancel.status_code == 200
        assert cancel.json()["status"] == "cancelling"
        payload = _wait_for_job_status(client, run_id, {"cancelled"})
        assert payload["status"] == "cancelled"


def test_backtest_async_job_records_failure_and_survives_restart(tmp_path, monkeypatch) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))

    def fail_backtest(*args, **kwargs):
        raise ValueError("bad async request")

    monkeypatch.setattr("quant_system.api.jobs.backtest_jobs.execute_backtest", fail_backtest)
    with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
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
        run_id = response.json()["run_id"]
        _wait_for_job_status(client, run_id, {"failed"})

    recovered = TestClient(create_app(settings=settings, output_dir=tmp_path))
    poll = recovered.get(f"/api/backtests/jobs/{run_id}")

    assert poll.status_code == 200
    payload = poll.json()
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "invalid_backtest_request"
    assert "bad async request" in payload["error"]["message"]


def test_backtest_async_job_recovers_stale_running_metadata(tmp_path) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))
    app = create_app(settings=settings, output_dir=tmp_path)
    run_id = "backtest-20240101T000000Z-stalejob"
    run_dir = tmp_path / "api_runs" / "backtests" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps({"run_id": run_id, "kind": "backtest", "status": "running"}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.get(f"/api/backtests/jobs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "job_recovered_after_restart"



def test_backtest_async_job_recovers_stale_running_metadata_when_jobs_disabled(tmp_path) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=False))
    run_id = "backtest-20240101T000000Z-stalejob"
    run_dir = tmp_path / "api_runs" / "backtests" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps({"run_id": run_id, "kind": "backtest", "status": "running"}),
        encoding="utf-8",
    )

    with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
        response = client.get(f"/api/backtests/jobs/{run_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "job_recovered_after_restart"

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



def test_backtest_list_excludes_active_async_jobs(tmp_path, monkeypatch) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))
    release = Event()

    def slow_backtest(*args, **kwargs):
        release.wait(timeout=2)
        raise RuntimeError("released test job")

    monkeypatch.setattr("quant_system.api.jobs.backtest_jobs.execute_backtest", slow_backtest)
    try:
        with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
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
            run_id = response.json()["run_id"]
            _wait_for_job_status(client, run_id, {"queued", "running"})

            list_response = client.get("/api/backtests")

            assert list_response.status_code == 200
            assert run_id not in {item["id"] for item in list_response.json()["backtests"]}
    finally:
        release.set()


def test_backtest_detail_accepts_legacy_metadata_without_status(tmp_path) -> None:
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
    metadata_path = tmp_path / "api_runs" / "backtests" / run_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.pop("status")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    detail_response = client.get(f"/api/backtests/{run_id}")

    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == run_id


def test_backtest_cancellation_does_not_mask_real_failure(tmp_path, monkeypatch) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))
    started = Event()

    def failing_after_cancel(*args, **kwargs):
        cancel_event = kwargs["cancel_event"]
        started.set()
        assert cancel_event.wait(timeout=2)
        raise RuntimeError("disk write failed")

    monkeypatch.setattr(
        "quant_system.api.jobs.backtest_jobs.execute_backtest",
        failing_after_cancel,
    )
    with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
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
        run_id = response.json()["run_id"]
        assert started.wait(timeout=2)
        _wait_for_job_status(client, run_id, {"running"})

        cancel = client.post(f"/api/backtests/jobs/{run_id}/cancel")

        assert cancel.status_code == 200
        payload = _wait_for_job_status(client, run_id, {"failed", "cancelled"})
        assert payload["status"] == "failed"
        assert payload["error"]["code"] == "backtest_job_failed"
        assert "disk write failed" in payload["error"]["message"]


def test_backtest_shutdown_waits_for_running_jobs_to_finish(tmp_path, monkeypatch) -> None:
    settings = Settings(backtest_jobs=BacktestJobSettings(enabled=True))
    started = Event()

    def cancellable_backtest(*args, **kwargs):
        cancel_event = kwargs["cancel_event"]
        started.set()
        assert cancel_event.wait(timeout=2)
        raise BacktestCancelledError("shutdown cancellation observed")

    monkeypatch.setattr(
        "quant_system.api.jobs.backtest_jobs.execute_backtest",
        cancellable_backtest,
    )
    with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
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
        run_id = response.json()["run_id"]
        assert started.wait(timeout=2)
        _wait_for_job_status(client, run_id, {"running"})

    metadata_path = tmp_path / "api_runs" / "backtests" / run_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "cancelled"


def test_backtest_shutdown_does_not_block_forever_on_non_cooperative_job(
    tmp_path,
    monkeypatch,
) -> None:
    settings = Settings(
        backtest_jobs=BacktestJobSettings(
            enabled=True,
            shutdown_timeout_seconds=0.05,
        )
    )
    started = Event()
    release = Event()

    def non_cooperative_backtest(*args, **kwargs):
        started.set()
        release.wait(timeout=2)
        raise RuntimeError("non-cooperative job released")

    monkeypatch.setattr(
        "quant_system.api.jobs.backtest_jobs.execute_backtest",
        non_cooperative_backtest,
    )
    started_at = time.perf_counter()
    try:
        with TestClient(create_app(settings=settings, output_dir=tmp_path)) as client:
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
            run_id = response.json()["run_id"]
            assert started.wait(timeout=2)
            _wait_for_job_status(client, run_id, {"running"})
    finally:
        release.set()
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.75
    metadata_path = tmp_path / "api_runs" / "backtests" / run_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "cancelled"
    assert metadata["error"]["code"] == "job_cancelled_on_shutdown_timeout"


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
