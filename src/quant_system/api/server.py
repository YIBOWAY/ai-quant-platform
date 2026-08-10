from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quant_system.api.bootstrap import build_services
from quant_system.api.routes import (
    agent,
    asia_radar,
    backtest,
    benchmark,
    brief,
    data,
    experiments,
    factors,
    health,
    hermes,
    local_session,
    market_cross_section,
    market_data,
    news,
    options,
    options_radar,
    paper,
    prediction_market,
    replications,
    runs,
    safety,
    strategies,
    universes,
    workspace,
)
from quant_system.api.routes import (
    settings as settings_routes,
)
from quant_system.api.safety.middleware import attach_safety_footer, validate_bind_address
from quant_system.config.settings import Settings
from quant_system.hermes.gateway_client import HermesApiReadClient, HermesApiReadError
from quant_system.logging.setup import configure_logging
from quant_system.options.data_refresh import (
    refresh_earnings_calendar,
    refresh_options_universe,
    refresh_vix_history,
)
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.scan_lock import OptionsRadarScanLocked, options_radar_scan_lock

logger = logging.getLogger(__name__)


def _init_run_index(active_settings: Settings, api_runs_dir: Path) -> None:
    """Best-effort PostgreSQL run-index backfill for an already-ready schema.

    Never raises: a database failure must not block API startup. With the DB
    disabled or unreachable this is a no-op and every endpoint uses the
    filesystem as before. Schema changes are an explicit operator action;
    startup never applies migrations, including when the legacy
    ``auto_migrate`` setting is true.
    """
    if not active_settings.database.enabled:
        return
    try:
        from quant_system.storage.database import get_database
        from quant_system.storage.runs_repository import sync_filesystem_to_index

        database = get_database(active_settings)
        if database is None:
            return
        sync_filesystem_to_index(api_runs_dir, active_settings)
    except Exception as exc:  # noqa: BLE001 - startup must survive DB problems
        logger.warning("run-index init skipped (filesystem fallback active): %s", exc)


def _start_run_index_init(active_settings: Settings, api_runs_dir: Path) -> None:
    if not active_settings.database.enabled:
        return
    thread = threading.Thread(
        target=_init_run_index,
        args=(active_settings, api_runs_dir),
        name="quant-system-run-index-init",
        daemon=True,
    )
    thread.start()


def _reconcile_orphaned_backtest_jobs(backtest_job_runner) -> None:
    try:
        recovered = backtest_job_runner.reconcile_orphaned_jobs()
    except Exception as exc:  # noqa: BLE001 - startup must continue serving
        logger.warning("backtest job reconciliation skipped: %s", exc)
        return
    if recovered:
        logger.info("reconciled %s orphaned backtest job(s)", recovered)


def _start_backtest_job_reconciliation(backtest_job_runner) -> threading.Thread:
    thread = threading.Thread(
        target=_reconcile_orphaned_backtest_jobs,
        args=(backtest_job_runner,),
        name="quant-system-backtest-job-reconcile",
        daemon=True,
    )
    thread.start()
    return thread


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    active = date(year, month, 1)
    while active.weekday() != weekday:
        active += timedelta(days=1)
    return active + timedelta(days=7 * (occurrence - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    active = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    while active.weekday() != weekday:
        active -= timedelta(days=1)
    return active


def _observed_fixed_holiday(year: int, month: int, day: int) -> date:
    holiday = date(year, month, day)
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _easter_date(year: int) -> date:
    # Anonymous Gregorian computus, valid for modern NYSE holiday calculations.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    month = (h + correction - 7 * m + 114) // 31
    day = ((h + correction - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _regular_us_market_holidays(year: int) -> set[date]:
    holidays = {
        _observed_fixed_holiday(year, 1, 1),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_date(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed_fixed_holiday(year, 7, 4),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed_fixed_holiday(year, 12, 25),
    }
    if year >= 2022:
        holidays.add(_observed_fixed_holiday(year, 6, 19))
    return holidays


def _is_regular_us_market_holiday(active_date: date) -> bool:
    years = (active_date.year - 1, active_date.year, active_date.year + 1)
    return any(active_date in _regular_us_market_holidays(year) for year in years)


def _is_us_market_session(active_date: date) -> bool:
    return active_date.weekday() < 5 and not _is_regular_us_market_holiday(active_date)


def _options_radar_startup_catchup_run_date(now: datetime | None = None) -> str:
    active_date = (now or datetime.now(UTC)).date()
    while not _is_us_market_session(active_date):
        active_date -= timedelta(days=1)
    return active_date.isoformat()


def _start_options_radar_startup_catchup(active_settings: Settings) -> None:
    radar_settings = active_settings.options_radar
    if not radar_settings.enabled or not radar_settings.startup_catchup_enabled:
        return
    run_date = _options_radar_startup_catchup_run_date()
    latest = RadarSnapshotStore(radar_settings.output_dir).latest_date()
    if latest == run_date:
        return
    thread = threading.Thread(
        target=_run_options_radar_startup_catchup,
        args=(active_settings, run_date),
        daemon=True,
    )
    thread.start()


def _run_options_radar_startup_catchup(active_settings: Settings, run_date: str) -> None:
    radar_settings = active_settings.options_radar
    provider = radar_settings.provider
    strategies = ["sell_put", "covered_call"]
    try:
        with options_radar_scan_lock(radar_settings.output_dir):
            started_at = datetime.now(UTC).isoformat()
            task_date = date.fromisoformat(run_date)
            refresh_source = "sample" if provider == "sample" else "public"
            steps: dict[str, dict] = {}
            current_step = "universe"
            _write_options_radar_startup_status(
                radar_settings.output_dir,
                {
                    "status": "running",
                    "source": "startup_catchup",
                    "run_date": run_date,
                    "provider": provider,
                    "strategies": strategies,
                    "started_at": started_at,
                    "steps": {},
                },
            )
            try:
                steps["universe"] = refresh_options_universe(
                    radar_settings.universe_path,
                    source=refresh_source,
                )
                current_step = "earnings"
                steps["earnings"] = refresh_earnings_calendar(
                    universe_path=radar_settings.universe_path,
                    output_path=radar_settings.earnings_calendar_path,
                    source=refresh_source,
                    top=radar_settings.universe_top_n,
                    today=task_date,
                )
                current_step = "vix"
                steps["vix"] = refresh_vix_history(
                    radar_settings.vix_history_path,
                    source=refresh_source,
                    lookback_days=400,
                    end=task_date,
                )
                current_step = "scan"
                result = options_radar._options_daily_scan_run_unlocked(
                    active_settings,
                    {
                        "provider": provider,
                        "top": radar_settings.universe_top_n,
                        "strategies": strategies,
                        "run_date": run_date,
                    },
                )
            except Exception as exc:  # noqa: BLE001 - startup catch-up must not kill API
                _write_options_radar_startup_status(
                    radar_settings.output_dir,
                    {
                        "status": "failed",
                        "source": "startup_catchup",
                        "run_date": run_date,
                        "provider": provider,
                        "strategies": strategies,
                        "started_at": started_at,
                        "finished_at": datetime.now(UTC).isoformat(),
                        "failed_step": current_step,
                        "error": f"{type(exc).__name__}: {exc}",
                        "steps": steps,
                    },
                )
                logger.warning("options radar startup catch-up failed: %s", exc)
                return

            _write_options_radar_startup_status(
                radar_settings.output_dir,
                {
                    "status": "completed",
                    "source": "startup_catchup",
                    "run_date": result["run_date"],
                    "provider": provider,
                    "strategies": strategies,
                    "started_at": started_at,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "steps": {
                        **steps,
                        "scan": {
                            "status": "completed",
                            "run_date": result["run_date"],
                            "universe_size": result["universe_size"],
                            "scanned_tickers": result["scanned_tickers"],
                            "failed_tickers": len(result["failed_tickers"]),
                            "candidate_count": result["candidate_count"],
                            "data_path": result["data_path"],
                            "meta_path": result["meta_path"],
                        },
                    },
                },
            )
    except OptionsRadarScanLocked as exc:
        logger.info("options radar startup catch-up skipped: %s", exc)
        return


def _write_options_radar_startup_status(output_dir: Path, payload: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "daily_task_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _start_paper_account_pending_order_processor(
    active_settings: Settings,
    api_runs_dir: Path,
) -> tuple[threading.Event, threading.Thread] | None:
    paper_settings = active_settings.paper_account
    if not paper_settings.auto_process_pending_orders_enabled:
        return None
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_run_paper_account_pending_order_processor,
        args=(active_settings, api_runs_dir, stop_event),
        name="quant-system-paper-pending-orders",
        daemon=True,
    )
    thread.start()
    return stop_event, thread


def _run_paper_account_pending_order_processor(
    active_settings: Settings,
    api_runs_dir: Path,
    stop_event: threading.Event,
) -> None:
    interval = active_settings.paper_account.auto_process_interval_seconds
    while not stop_event.is_set():
        try:
            outcomes = paper.process_pending_account_orders_once(
                api_runs_dir,
                active_settings,
            )
            if outcomes:
                filled = sum(1 for outcome in outcomes if outcome.status == "filled")
                pending = sum(1 for outcome in outcomes if outcome.status == "pending")
                logger.info(
                    "paper pending-order auto-check processed %s order(s): %s filled, %s pending",
                    len(outcomes),
                    filled,
                    pending,
                )
        except Exception as exc:  # noqa: BLE001 - background worker must not kill API
            logger.warning("paper pending-order auto-check skipped: %s", exc)
        if stop_event.wait(interval):
            break


def _validate_hermes_gateway_startup(
    *,
    settings: Settings,
    bind_address: str,
    bind_address_explicit: bool,
) -> None:
    if not settings.hermes_gateway.enabled:
        return
    if not bind_address_explicit:
        raise ValueError(
            "Hermes gateway read integration requires an explicit loopback bind declaration"
        )
    if bind_address not in {"127.0.0.1", "::1"}:
        raise ValueError("Hermes gateway read integration requires a loopback platform bind")
    try:
        HermesApiReadClient(settings.hermes_gateway)
    except HermesApiReadError as exc:
        raise ValueError(f"Invalid Hermes gateway configuration: {exc.code}") from exc


def create_app(
    *,
    settings: Settings | None = None,
    output_dir: str | Path | None = None,
    agent_output_dir: str | Path | None = None,
    bind_address: str | None = None,
    bind_public_confirmed: bool | None = None,
) -> FastAPI:
    env_bind_address = os.getenv("QS_API_BIND_ADDRESS")
    bind_address_explicit = bind_address is not None or bool(env_bind_address)
    active_bind_address = bind_address or env_bind_address or "127.0.0.1"
    active_bind_public_confirmed = (
        bind_public_confirmed
        if bind_public_confirmed is not None
        else os.getenv("QS_API_BIND_PUBLIC_CONFIRMED") == "I_UNDERSTAND"
    )
    validate_bind_address(
        bind_address=active_bind_address,
        bind_public_confirmed=active_bind_public_confirmed,
    )
    services = build_services(
        settings=settings,
        output_dir=output_dir,
        agent_output_dir=agent_output_dir,
        bind_address=active_bind_address,
    )
    active_settings: Settings = services["settings"]
    _validate_hermes_gateway_startup(
        settings=active_settings,
        bind_address=active_bind_address,
        bind_address_explicit=bind_address_explicit,
    )
    configure_logging(
        active_settings.log_level,
        log_dir=services["output_dir"] / "_runtime" / "logs",
    )
    logger.info("api app configured")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services
        services["api_runs_dir"].mkdir(parents=True, exist_ok=True)
        backtest_job_runner = services["backtest_job_runner"]
        backtest_reconcile_thread = _start_backtest_job_reconciliation(backtest_job_runner)
        _start_run_index_init(active_settings, services["api_runs_dir"])
        _start_options_radar_startup_catchup(active_settings)
        pending_order_processor = _start_paper_account_pending_order_processor(
            active_settings,
            services["api_runs_dir"],
        )
        try:
            yield
        finally:
            backtest_reconcile_thread.join(timeout=1.0)
            backtest_job_runner.shutdown(wait=True, cancel_futures=True)
            news.close_aihot_clients()
            if pending_order_processor is not None:
                stop_event, thread = pending_order_processor
                stop_event.set()
                thread.join(timeout=1.0)

    app = FastAPI(
        title="AI Quant Platform API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=active_settings.api_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.middleware("http")(attach_safety_footer)
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(asia_radar.router, prefix="/api", tags=["asia-radar"])
    app.include_router(
        market_cross_section.router, prefix="/api", tags=["market-cross-section"]
    )
    app.include_router(safety.router, prefix="/api", tags=["safety"])
    app.include_router(local_session.router, prefix="/api", tags=["auth"])
    app.include_router(workspace.router, prefix="/api", tags=["workspace"])
    app.include_router(hermes.router, prefix="/api", tags=["hermes"])
    app.include_router(settings_routes.router, prefix="/api", tags=["settings"])
    app.include_router(data.router, prefix="/api", tags=["data"])
    app.include_router(market_data.router, prefix="/api", tags=["market-data"])
    app.include_router(news.router, prefix="/api", tags=["news"])
    app.include_router(options.router, prefix="/api", tags=["options"])
    app.include_router(options_radar.router, prefix="/api", tags=["options-radar"])
    app.include_router(factors.router, prefix="/api", tags=["factors"])
    app.include_router(backtest.router, prefix="/api", tags=["backtests"])
    app.include_router(benchmark.router, prefix="/api", tags=["benchmark"])
    app.include_router(experiments.router, prefix="/api", tags=["experiments"])
    app.include_router(paper.router, prefix="/api", tags=["paper"])
    app.include_router(agent.router, prefix="/api", tags=["agent"])
    app.include_router(brief.router, prefix="/api", tags=["brief"])
    app.include_router(prediction_market.router, prefix="/api", tags=["prediction-market"])
    app.include_router(replications.router, prefix="/api", tags=["replications"])
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    app.include_router(strategies.router, prefix="/api", tags=["strategies"])
    app.include_router(universes.router, prefix="/api", tags=["universes"])
    return app
