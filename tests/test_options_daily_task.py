from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from quant_system.options.daily_task import (
    OptionsDailyTaskDependencies,
    OptionsDailyTaskRequest,
    run_options_daily_task,
)
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.models import OptionsScreenerConfig
from quant_system.options.radar import OptionsRadarReport
from quant_system.options.universe import UniverseEntry


def test_daily_task_persists_running_progress_and_terminal_status(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.options import daily_task

    output_dir = tmp_path / "scans"
    output_dir.mkdir()
    (output_dir / "daily_task_status.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "target_session": "2026-08-23",
                "queued_at": "2026-08-24T01:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    request = OptionsDailyTaskRequest(
        provider="futu",
        top=2,
        strategies=("sell_put", "covered_call"),
        run_date="2026-08-24",
        universe_source="existing",
        earnings_source="public",
        vix_source="public",
        universe_path=tmp_path / "curated.csv",
        earnings_path=tmp_path / "earnings.csv",
        vix_path=tmp_path / "vix.csv",
        output_dir=output_dir,
        iv_history_dir=output_dir / "iv_history",
        trigger="scheduled",
    )
    settings = SimpleNamespace(
        options_radar=SimpleNamespace(
            output_dir=tmp_path / "canonical",
            curated_universe_path=tmp_path / "canonical.csv",
            risk_free_rate=0.0387,
            equity_risk_premium=0.04,
        )
    )
    universe = [
        UniverseEntry("SPY", "SPY", "ETF", "US", "core_etf"),
        UniverseEntry("QQQ", "QQQ", "ETF", "US", "core_etf"),
    ]
    persisted: list[dict[str, object]] = []
    real_write = daily_task.write_options_daily_task_status

    def capture_status(root: Path, payload: dict[str, object]) -> Path:
        persisted.append(dict(payload))
        return real_write(root, payload)

    radar_kwargs: dict[str, object] = {}

    def fake_run_radar(**kwargs) -> OptionsRadarReport:
        radar_kwargs.update(kwargs)
        callback = kwargs["progress_callback"]
        callback(1, 2)
        callback(2, 2)
        return OptionsRadarReport(
            run_date="2026-08-24",
            started_at="2026-08-25T02:00:00Z",
            finished_at="2026-08-25T02:02:00Z",
            universe_size=2,
            expected_universe_size=2,
            scanned_tickers=1,
            failed_tickers=[("QQQ", "FutuProviderError:rate_limited")],
            candidates=[],
            provider="futu",
            as_of="2026-08-24T20:00:00Z",
            status="empty",
            risk_free_rate=0.0387,
            shortfall_count=20,
            shortfall_reasons={"ticker_scan_failed": 1},
        )

    monkeypatch.setattr(daily_task, "write_options_daily_task_status", capture_status)
    dependencies = OptionsDailyTaskDependencies(
        load_universe=lambda _path, **_kwargs: universe,
        refresh_universe=lambda *_args, **_kwargs: {},
        refresh_earnings=lambda **_kwargs: {
            "kind": "earnings",
            "status": "refreshed",
            "row_count": 2,
        },
        refresh_vix=lambda *_args, **_kwargs: {
            "kind": "vix",
            "status": "refreshed",
            "row_count": 400,
        },
        refresh_dividends=lambda *_args, **_kwargs: {
            "kind": "dividends",
            "status": "refreshed",
            "row_count": 2,
        },
        load_dividend_events=lambda _path: {"SPY": (None, 0.0)},
        build_provider=lambda *_args, **_kwargs: object(),
        build_screen_config=lambda _settings: OptionsScreenerConfig(),
        load_market_regime=lambda *_args, **_kwargs: None,
        load_earnings_calendar=lambda _path: EarningsCalendar({}),
        run_radar=fake_run_radar,
        write_snapshot=lambda _output_dir, _report: (
            output_dir / "2026-08-24.jsonl",
            output_dir / "2026-08-24_meta.json",
        ),
    )

    result = run_options_daily_task(
        settings=settings,
        request=request,
        dependencies=dependencies,
    )

    assert result.status == "completed_with_warnings"
    assert result.status_path == output_dir / "daily_task_status.json"
    assert [item["current_step"] for item in persisted] == [
        "universe",
        "earnings",
        "dividends",
        "vix",
        "scan",
        "scan",
        "scan",
        "completed",
    ]
    assert persisted[-1]["steps"]["dividends"] == {
        "kind": "dividends",
        "status": "refreshed",
        "row_count": 2,
    }
    assert radar_kwargs["dividend_events"] == {"SPY": (None, 0.0)}
    radar_config = radar_kwargs["config"]
    assert radar_config.equity_risk_premium == 0.04
    assert persisted[-1]["terminal"] is True
    assert persisted[-1]["scanned_tickers"] == 2
    assert persisted[-1]["successful_tickers"] == 1
    assert persisted[-1]["total_tickers"] == 2
    assert persisted[-1]["target_session"] == "2026-08-24"
    assert persisted[-1]["trigger"] == "scheduled"
    assert persisted[-1]["queued_at"] != "2026-08-24T01:00:00Z"
    assert all(
        item["strategies"] == ["sell_put", "covered_call"] for item in persisted
    )


def test_daily_task_failure_is_terminal_and_names_the_failed_step(tmp_path: Path) -> None:
    output_dir = tmp_path / "scans"
    request = OptionsDailyTaskRequest(
        provider="futu",
        top=1,
        strategies=("sell_put",),
        run_date="2026-08-24",
        universe_source="existing",
        earnings_source="public",
        vix_source="public",
        universe_path=tmp_path / "curated.csv",
        earnings_path=tmp_path / "earnings.csv",
        vix_path=tmp_path / "vix.csv",
        output_dir=output_dir,
        iv_history_dir=output_dir / "iv_history",
        trigger="manual",
    )
    settings = SimpleNamespace(
        options_radar=SimpleNamespace(
            output_dir=tmp_path / "canonical",
            curated_universe_path=tmp_path / "canonical.csv",
            risk_free_rate=0.0387,
            equity_risk_premium=0.04,
        )
    )
    universe = [UniverseEntry("SPY", "SPY", "ETF", "US", "core_etf")]
    dependencies = OptionsDailyTaskDependencies(
        load_universe=lambda _path, **_kwargs: universe,
        refresh_universe=lambda *_args, **_kwargs: {},
        refresh_earnings=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("earnings service unavailable")
        ),
        refresh_vix=lambda *_args, **_kwargs: {},
        refresh_dividends=lambda *_args, **_kwargs: {"status": "refreshed"},
        load_dividend_events=lambda _path: {},
        build_provider=lambda *_args, **_kwargs: object(),
        build_screen_config=lambda _settings: OptionsScreenerConfig(),
        load_market_regime=lambda *_args, **_kwargs: None,
        load_earnings_calendar=lambda _path: EarningsCalendar({}),
        run_radar=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("scan must not start")
        ),
        write_snapshot=lambda *_args: (_ for _ in ()).throw(
            AssertionError("snapshot must not be written")
        ),
    )

    with pytest.raises(RuntimeError, match="earnings service unavailable"):
        run_options_daily_task(
            settings=settings,
            request=request,
            dependencies=dependencies,
        )

    status = json.loads(
        (output_dir / "daily_task_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert status["terminal"] is True
    assert status["current_step"] == "failed"
    assert status["failed_step"] == "earnings"
    assert status["error"] == "RuntimeError: earnings service unavailable"


def test_daily_task_rejects_canonical_custom_iv_history_before_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.options import daily_task

    output_dir = tmp_path / "canonical"
    request = OptionsDailyTaskRequest(
        provider="futu",
        top=34,
        strategies=("sell_put", "covered_call"),
        run_date="2026-08-24",
        universe_source="existing",
        earnings_source="public",
        vix_source="public",
        universe_path=tmp_path / "curated.csv",
        earnings_path=tmp_path / "earnings.csv",
        vix_path=tmp_path / "vix.csv",
        output_dir=output_dir,
        iv_history_dir=tmp_path / "different-lock-root" / "iv_history",
        trigger="scheduled",
    )
    settings = SimpleNamespace(
        options_radar=SimpleNamespace(
            output_dir=output_dir,
            curated_universe_path=request.universe_path,
            risk_free_rate=0.0387,
        )
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid canonical IV authority acquired a lock")

    monkeypatch.setattr(daily_task, "options_radar_scan_lock", forbidden)

    with pytest.raises(ValueError, match="canonical_options_iv_history_required"):
        run_options_daily_task(settings=settings, request=request)

    assert not output_dir.exists()


def test_daily_task_does_not_complete_empty_report_without_quote_watermark(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "scans"
    request = OptionsDailyTaskRequest(
        provider="futu",
        top=1,
        strategies=("sell_put",),
        run_date="2026-08-24",
        universe_source="existing",
        earnings_source="public",
        vix_source="public",
        universe_path=tmp_path / "curated.csv",
        earnings_path=tmp_path / "earnings.csv",
        vix_path=tmp_path / "vix.csv",
        output_dir=output_dir,
        iv_history_dir=output_dir / "iv_history",
        trigger="scheduled",
    )
    settings = SimpleNamespace(
        options_radar=SimpleNamespace(
            output_dir=tmp_path / "canonical",
            curated_universe_path=tmp_path / "canonical.csv",
            risk_free_rate=0.0387,
            equity_risk_premium=0.04,
        )
    )
    universe = [UniverseEntry("SPY", "SPY", "ETF", "US", "core_etf")]
    report = OptionsRadarReport(
        run_date="2026-08-24",
        started_at="2026-08-25T02:00:00Z",
        finished_at="2026-08-25T02:02:00Z",
        universe_size=1,
        expected_universe_size=1,
        scanned_tickers=1,
        failed_tickers=[],
        candidates=[],
        provider="futu",
        as_of=None,
        status="empty",
        risk_free_rate=0.0387,
        shortfall_count=20,
        shortfall_reasons={"eligible_contracts_below_limit": 20},
    )
    dependencies = OptionsDailyTaskDependencies(
        load_universe=lambda _path, **_kwargs: universe,
        refresh_universe=lambda *_args, **_kwargs: {},
        refresh_earnings=lambda **_kwargs: {"status": "refreshed"},
        refresh_vix=lambda *_args, **_kwargs: {"status": "refreshed"},
        refresh_dividends=lambda *_args, **_kwargs: {"status": "refreshed"},
        load_dividend_events=lambda _path: {},
        build_provider=lambda *_args, **_kwargs: object(),
        build_screen_config=lambda _settings: OptionsScreenerConfig(),
        load_market_regime=lambda *_args, **_kwargs: None,
        load_earnings_calendar=lambda _path: EarningsCalendar({}),
        run_radar=lambda **_kwargs: report,
        write_snapshot=lambda *_args: (_ for _ in ()).throw(
            AssertionError("invalid empty report must not be persisted")
        ),
    )

    with pytest.raises(ValueError, match="options_scan_quote_watermark_required"):
        run_options_daily_task(
            settings=settings,
            request=request,
            dependencies=dependencies,
        )

    status = json.loads(
        (output_dir / "daily_task_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert status["failed_step"] == "scan"


def test_daily_task_dividends_failure_names_the_dividends_step(tmp_path: Path) -> None:
    output_dir = tmp_path / "scans"
    request = OptionsDailyTaskRequest(
        provider="futu",
        top=1,
        strategies=("sell_put",),
        run_date="2026-08-24",
        universe_source="existing",
        earnings_source="public",
        vix_source="public",
        universe_path=tmp_path / "curated.csv",
        earnings_path=tmp_path / "earnings.csv",
        vix_path=tmp_path / "vix.csv",
        output_dir=output_dir,
        iv_history_dir=output_dir / "iv_history",
        trigger="manual",
        dividends_path=tmp_path / "dividends.csv",
    )
    settings = SimpleNamespace(
        options_radar=SimpleNamespace(
            output_dir=tmp_path / "canonical",
            curated_universe_path=tmp_path / "canonical.csv",
            risk_free_rate=0.0387,
            equity_risk_premium=0.04,
        )
    )
    universe = [UniverseEntry("SPY", "SPY", "ETF", "US", "core_etf")]
    dependencies = OptionsDailyTaskDependencies(
        load_universe=lambda _path, **_kwargs: universe,
        refresh_universe=lambda *_args, **_kwargs: {},
        refresh_earnings=lambda **_kwargs: {"status": "refreshed"},
        refresh_vix=lambda *_args, **_kwargs: {},
        refresh_dividends=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("dividend service unavailable")
        ),
        load_dividend_events=lambda _path: {},
        build_provider=lambda *_args, **_kwargs: object(),
        build_screen_config=lambda _settings: OptionsScreenerConfig(),
        load_market_regime=lambda *_args, **_kwargs: None,
        load_earnings_calendar=lambda _path: EarningsCalendar({}),
        run_radar=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("scan must not start")
        ),
        write_snapshot=lambda *_args: (_ for _ in ()).throw(
            AssertionError("snapshot must not be written")
        ),
    )

    with pytest.raises(RuntimeError, match="dividend service unavailable"):
        run_options_daily_task(
            settings=settings,
            request=request,
            dependencies=dependencies,
        )

    status = json.loads(
        (output_dir / "daily_task_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert status["failed_step"] == "dividends"


def test_daily_task_rejects_sample_dividend_source_for_futu(tmp_path: Path) -> None:
    output_dir = tmp_path / "scans"
    request = OptionsDailyTaskRequest(
        provider="futu",
        top=1,
        strategies=("sell_put",),
        run_date="2026-08-24",
        universe_source="existing",
        earnings_source="public",
        vix_source="public",
        universe_path=tmp_path / "curated.csv",
        earnings_path=tmp_path / "earnings.csv",
        vix_path=tmp_path / "vix.csv",
        output_dir=output_dir,
        iv_history_dir=output_dir / "iv_history",
        trigger="manual",
        dividend_source="sample",
        dividends_path=tmp_path / "dividends.csv",
    )
    settings = SimpleNamespace(
        options_radar=SimpleNamespace(
            output_dir=tmp_path / "canonical",
            curated_universe_path=tmp_path / "canonical.csv",
            risk_free_rate=0.0387,
            equity_risk_premium=0.04,
        )
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sample dividend source must not reach any refresh")

    dependencies = OptionsDailyTaskDependencies(
        load_universe=forbidden,
        refresh_universe=forbidden,
        refresh_earnings=forbidden,
        refresh_vix=forbidden,
        refresh_dividends=forbidden,
        load_dividend_events=forbidden,
        build_provider=forbidden,
        build_screen_config=forbidden,
        load_market_regime=forbidden,
        load_earnings_calendar=forbidden,
        run_radar=forbidden,
        write_snapshot=forbidden,
    )

    with pytest.raises(ValueError, match="sample_options_input_withdrawn"):
        run_options_daily_task(
            settings=settings,
            request=request,
            dependencies=dependencies,
        )

    status = json.loads(
        (output_dir / "daily_task_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "failed"
    assert status["failed_step"] == "universe"
