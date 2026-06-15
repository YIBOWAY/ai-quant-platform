from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import OptionsRadarSettings, Settings
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.models import OptionsScreenerConfig
from quant_system.options.radar import OptionsRadarConfig, run_options_radar
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.sample_provider import SampleOptionsProvider
from quant_system.options.universe import UniverseEntry
from quant_system.options.vix_data import load_vix_history


def _write_sample_snapshot(root: Path, run_date: str = "2026-05-03") -> None:
    report = run_options_radar(
        provider=SampleOptionsProvider(),
        universe=[
            UniverseEntry("SPY", "SPDR S&P 500 ETF", "ETF", "US", "both"),
            UniverseEntry("QQQ", "Invesco QQQ", "ETF", "US", "nasdaq100"),
        ],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=7,
                max_dte=60,
                max_delta=0.8,
                min_open_interest=1,
                min_avg_daily_volume=1,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            top_per_ticker=1,
            universe_top_n=2,
        ),
        iv_history_dir=root / "iv_history",
        earnings_calendar=EarningsCalendar({}),
        run_date=run_date,
    )
    RadarSnapshotStore(root).write(report)


def test_api_options_daily_scan_lists_dates_and_returns_snapshot(tmp_path: Path) -> None:
    _write_sample_snapshot(tmp_path)
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    dates_response = client.get("/api/options/daily-scan/dates")
    snapshot_response = client.get(
        "/api/options/daily-scan",
        params={"date": "2026-05-03", "strategy": "sell_put", "top": 1},
    )

    assert dates_response.status_code == 200
    assert dates_response.json()["dates"] == ["2026-05-03"]
    assert snapshot_response.status_code == 200
    payload = snapshot_response.json()
    assert payload["run_date"] == "2026-05-03"
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["strategy"] == "sell_put"
    assert payload["safety"]["live_trading_enabled"] is False


def test_api_options_daily_scan_defaults_to_latest_date(tmp_path: Path) -> None:
    _write_sample_snapshot(tmp_path, "2026-05-02")
    _write_sample_snapshot(tmp_path, "2026-05-03")
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan")

    assert response.status_code == 200
    assert response.json()["run_date"] == "2026-05-03"


def test_api_options_daily_scan_status_reports_daily_task_file(tmp_path: Path) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    missing = client.get("/api/options/daily-scan/status")
    assert missing.status_code == 200
    assert missing.json()["exists"] is False
    assert missing.json()["status"] is None

    status = {
        "status": "completed",
        "run_date": "2026-06-15",
        "provider": "futu",
        "strategies": ["sell_put", "covered_call"],
        "started_at": "2026-06-15T09:00:00+00:00",
        "finished_at": "2026-06-15T09:02:00+00:00",
        "steps": {"scan": {"candidate_count": 12}},
    }
    (tmp_path / "daily_task_status.json").write_text(
        json.dumps(status),
        encoding="utf-8",
    )

    response = client.get("/api/options/daily-scan/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["exists"] is True
    assert payload["status_path"].endswith("daily_task_status.json")
    assert payload["status"] == status


def test_api_startup_schedules_options_radar_catchup_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api import server as api_server

    run_date = "2026-06-15"
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path,
            provider="sample",
            startup_catchup_enabled=True,
        )
    )
    scheduled: list[tuple[Settings, str]] = []

    class FakeThread:
        def __init__(self, *, target, args, daemon) -> None:
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self) -> None:
            scheduled.append(self.args)

    monkeypatch.setattr(api_server, "_options_radar_startup_catchup_run_date", lambda: run_date)
    monkeypatch.setattr(api_server, "_run_options_radar_startup_catchup", lambda *_args: None)
    monkeypatch.setattr(api_server.threading, "Thread", FakeThread)

    with TestClient(create_app(settings=settings, output_dir=tmp_path)):
        pass

    assert scheduled == [(settings, run_date)]


def test_api_startup_skips_options_radar_catchup_when_snapshot_is_current(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api import server as api_server

    run_date = datetime.now(UTC).date().isoformat()
    _write_sample_snapshot(tmp_path, run_date)
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path,
            provider="sample",
            startup_catchup_enabled=True,
        )
    )

    class FakeThread:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("startup catch-up should not be scheduled")

    monkeypatch.setattr(api_server.threading, "Thread", FakeThread)

    with TestClient(create_app(settings=settings, output_dir=tmp_path)):
        pass


def test_options_radar_startup_catchup_writes_completed_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api import server as api_server

    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path,
            provider="sample",
            startup_catchup_enabled=True,
        )
    )

    def fake_scan(_settings: Settings, payload: dict) -> dict:
        assert payload["provider"] == "sample"
        assert payload["run_date"] == "2026-06-15"
        return {
            "run_date": "2026-06-15",
            "universe_size": 2,
            "scanned_tickers": 2,
            "failed_tickers": [],
            "candidate_count": 4,
            "data_path": str(tmp_path / "daily" / "2026-06-15.jsonl"),
            "meta_path": str(tmp_path / "daily" / "2026-06-15.meta.json"),
        }

    monkeypatch.setattr(api_server.options_radar, "options_daily_scan_run", fake_scan)

    api_server._run_options_radar_startup_catchup(settings, "2026-06-15")

    status = json.loads((tmp_path / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert status["source"] == "startup_catchup"
    assert status["steps"]["scan"]["candidate_count"] == 4


def test_options_radar_startup_catchup_writes_failed_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api import server as api_server

    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path,
            provider="sample",
            startup_catchup_enabled=True,
        )
    )

    def fake_scan(_settings: Settings, _payload: dict) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(api_server.options_radar, "options_daily_scan_run", fake_scan)

    api_server._run_options_radar_startup_catchup(settings, "2026-06-15")

    status = json.loads((tmp_path / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["source"] == "startup_catchup"
    assert status["failed_step"] == "scan"
    assert "RuntimeError: boom" in status["error"]


def test_api_options_daily_scan_run_writes_sample_snapshot(tmp_path: Path) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.post(
        "/api/options/daily-scan/run",
        json={
            "provider": "sample",
            "top": 1,
            "strategies": ["sell_put"],
            "run_date": "2099-01-03",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_date"] == "2099-01-03"
    assert payload["scanned_tickers"] == 1
    assert payload["candidate_count"] > 0
    assert payload["safety"]["live_trading_enabled"] is False

    dates_response = client.get("/api/options/daily-scan/dates")
    assert "2099-01-03" in dates_response.json()["dates"]


def test_api_options_daily_scan_symbol_returns_snapshot_candidates(tmp_path: Path) -> None:
    _write_sample_snapshot(tmp_path, "2099-01-04")
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/options/daily-scan/symbol/SPY",
        params={"date": "2099-01-04"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "SPY"
    assert payload["run_date"] == "2099-01-04"
    assert payload["candidates"]
    assert payload["candidates"][0]["ticker"] == "SPY"
    assert payload["safety"]["live_trading_enabled"] is False


def test_api_options_daily_scan_missing_date_returns_404(tmp_path: Path) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan", params={"date": "2026-05-03"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_radar_snapshot"
    assert response.json()["safety"]["dry_run"] is True


def test_api_options_refresh_inputs_writes_local_sample_files(tmp_path: Path) -> None:
    universe_path = tmp_path / "universe.csv"
    earnings_path = tmp_path / "earnings.csv"
    vix_path = tmp_path / "vix_history.csv"
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=tmp_path / "scans",
            universe_path=universe_path,
            earnings_calendar_path=earnings_path,
            vix_history_path=vix_path,
        )
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    universe_response = client.post(
        "/api/options/refresh/universe",
        json={"source": "sample"},
    )
    earnings_response = client.post(
        "/api/options/refresh/earnings",
        json={"source": "sample", "top": 2, "today": "2099-01-03"},
    )
    vix_response = client.post(
        "/api/options/refresh/vix",
        json={"source": "sample", "lookback_days": 10, "end": "2099-01-10"},
    )

    assert universe_response.status_code == 200
    assert universe_response.json()["kind"] == "universe"
    assert universe_response.json()["row_count"] >= 3
    assert universe_path.exists()

    assert earnings_response.status_code == 200
    assert earnings_response.json()["kind"] == "earnings"
    assert earnings_response.json()["row_count"] == 2
    assert earnings_path.exists()

    assert vix_response.status_code == 200
    assert vix_response.json()["kind"] == "vix"
    assert vix_response.json()["row_count"] == 10
    vix, vix3m = load_vix_history(vix_path)
    assert len(vix) == 10
    assert vix3m is not None
    assert vix_response.json()["safety"]["live_trading_enabled"] is False
