from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quant_system.api.bootstrap import build_services
from quant_system.api.routes import (
    agent,
    backtest,
    benchmark,
    data,
    experiments,
    factors,
    health,
    market_data,
    options,
    options_radar,
    paper,
    prediction_market,
    replications,
    runs,
    strategies,
    universes,
)
from quant_system.api.routes import (
    settings as settings_routes,
)
from quant_system.api.safety.middleware import attach_safety_footer, validate_bind_address
from quant_system.config.settings import Settings
from quant_system.logging.setup import configure_logging
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.scan_lock import OptionsRadarScanLocked, options_radar_scan_lock

logger = logging.getLogger(__name__)


def _init_run_index(active_settings: Settings, api_runs_dir: Path) -> None:
    """Best-effort PostgreSQL run-index init: migrate + backfill existing files.

    Never raises: a database failure must not block API startup. With the DB
    disabled or unreachable this is a no-op and every endpoint uses the
    filesystem as before.
    """
    if not active_settings.database.enabled:
        return
    try:
        from quant_system.storage.database import get_database, run_migrations
        from quant_system.storage.runs_repository import sync_filesystem_to_index

        database = get_database(active_settings)
        if database is None:
            return
        if active_settings.database.auto_migrate:
            run_migrations(database)
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


def _options_radar_startup_catchup_run_date(now: datetime | None = None) -> str:
    active_date = (now or datetime.now(UTC)).date()
    while active_date.weekday() >= 5:
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
                        "failed_step": "scan",
                        "error": f"{type(exc).__name__}: {exc}",
                        "steps": {},
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
                        "scan": {
                            "status": "completed",
                            "run_date": result["run_date"],
                            "universe_size": result["universe_size"],
                            "scanned_tickers": result["scanned_tickers"],
                            "failed_tickers": len(result["failed_tickers"]),
                            "candidate_count": result["candidate_count"],
                            "data_path": result["data_path"],
                            "meta_path": result["meta_path"],
                        }
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


def create_app(
    *,
    settings: Settings | None = None,
    output_dir: str | Path | None = None,
    bind_address: str | None = None,
    bind_public_confirmed: bool | None = None,
) -> FastAPI:
    active_bind_address = bind_address or os.getenv("QS_API_BIND_ADDRESS", "127.0.0.1")
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
        bind_address=active_bind_address,
    )
    active_settings: Settings = services["settings"]
    configure_logging(
        active_settings.log_level,
        log_dir=services["output_dir"] / "_runtime" / "logs",
    )
    logger.info("api app configured")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services
        services["api_runs_dir"].mkdir(parents=True, exist_ok=True)
        _start_run_index_init(active_settings, services["api_runs_dir"])
        _start_options_radar_startup_catchup(active_settings)
        yield

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
    app.include_router(settings_routes.router, prefix="/api", tags=["settings"])
    app.include_router(data.router, prefix="/api", tags=["data"])
    app.include_router(market_data.router, prefix="/api", tags=["market-data"])
    app.include_router(options.router, prefix="/api", tags=["options"])
    app.include_router(options_radar.router, prefix="/api", tags=["options-radar"])
    app.include_router(factors.router, prefix="/api", tags=["factors"])
    app.include_router(backtest.router, prefix="/api", tags=["backtests"])
    app.include_router(benchmark.router, prefix="/api", tags=["benchmark"])
    app.include_router(experiments.router, prefix="/api", tags=["experiments"])
    app.include_router(paper.router, prefix="/api", tags=["paper"])
    app.include_router(agent.router, prefix="/api", tags=["agent"])
    app.include_router(prediction_market.router, prefix="/api", tags=["prediction-market"])
    app.include_router(replications.router, prefix="/api", tags=["replications"])
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    app.include_router(strategies.router, prefix="/api", tags=["strategies"])
    app.include_router(universes.router, prefix="/api", tags=["universes"])
    return app
