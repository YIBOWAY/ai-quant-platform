from __future__ import annotations

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


def test_api_options_daily_scan_missing_date_returns_404(tmp_path: Path) -> None:
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=tmp_path))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get("/api/options/daily-scan", params={"date": "2026-05-03"})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_radar_snapshot"
    assert response.json()["safety"]["dry_run"] is True
