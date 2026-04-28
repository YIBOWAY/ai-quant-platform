from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
    paper,
    prediction_market,
)
from quant_system.api.routes import (
    settings as settings_routes,
)
from quant_system.api.safety.middleware import attach_safety_footer, validate_bind_address
from quant_system.config.settings import Settings


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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.services = services
        services["api_runs_dir"].mkdir(parents=True, exist_ok=True)
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
    app.include_router(factors.router, prefix="/api", tags=["factors"])
    app.include_router(backtest.router, prefix="/api", tags=["backtests"])
    app.include_router(benchmark.router, prefix="/api", tags=["benchmark"])
    app.include_router(experiments.router, prefix="/api", tags=["experiments"])
    app.include_router(paper.router, prefix="/api", tags=["paper"])
    app.include_router(agent.router, prefix="/api", tags=["agent"])
    app.include_router(prediction_market.router, prefix="/api", tags=["prediction-market"])
    return app
