from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quant_system.api.bootstrap import build_services
from quant_system.api.routes import (
    agent,
    asia_radar,
    assistant_remote,
    backtest,
    benchmark,
    brief,
    collection,
    company_research,
    data,
    experiments,
    factor_scorecards,
    factors,
    health,
    hermes,
    local_session,
    market_assessment,
    market_cross_section,
    market_data,
    news,
    options,
    options_radar,
    paper,
    prediction_market,
    replications,
    research_evaluation,
    runs,
    safety,
    securities,
    strategies,
    strategy_library,
    strategy_studies,
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
            news.close_market_news_clients()
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
    app.include_router(market_cross_section.router, prefix="/api", tags=["market-cross-section"])
    app.include_router(market_assessment.router, prefix="/api", tags=["market-assessment"])
    app.include_router(company_research.router, prefix="/api", tags=["company-research"])
    app.include_router(securities.router, prefix="/api", tags=["securities"])
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
    app.include_router(factor_scorecards.router, prefix="/api", tags=["factor-scorecards"])
    app.include_router(backtest.router, prefix="/api", tags=["backtests"])
    app.include_router(benchmark.router, prefix="/api", tags=["benchmark"])
    app.include_router(experiments.router, prefix="/api", tags=["experiments"])
    app.include_router(paper.router, prefix="/api", tags=["paper"])
    app.include_router(assistant_remote.router, prefix="/api", tags=["assistant-remote"])
    app.include_router(agent.router, prefix="/api", tags=["agent"])
    app.include_router(brief.router, prefix="/api", tags=["brief"])
    app.include_router(prediction_market.router, prefix="/api", tags=["prediction-market"])
    app.include_router(replications.router, prefix="/api", tags=["replications"])
    app.include_router(runs.router, prefix="/api", tags=["runs"])
    app.include_router(strategies.router, prefix="/api", tags=["strategies"])
    app.include_router(collection.router, prefix="/api", tags=["collection"])
    app.include_router(research_evaluation.router, prefix="/api", tags=["research-evaluation"])
    app.include_router(strategy_studies.router, prefix="/api", tags=["strategy-studies"])
    app.include_router(strategy_library.router, prefix="/api", tags=["strategy-library"])
    app.include_router(universes.router, prefix="/api", tags=["universes"])
    return app
