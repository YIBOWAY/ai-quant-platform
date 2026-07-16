from __future__ import annotations

import socket
from typing import Any

from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.health import HealthResponse
from quant_system.hermes.command_ledger import command_ledger_schema_version
from quant_system.hermes.workflow_binding import workflow_binding_schema_version

router = APIRouter()


def _probe_opend(host: str, port: int) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return {"host": host, "port": port, "reachable": True, "error": None}
    except OSError as exc:
        return {
            "host": host,
            "port": port,
            "reachable": False,
            "error": f"{exc.__class__.__name__}: {exc}",
        }


@router.get("/health", response_model=HealthResponse)
def health(settings: SettingsDep) -> dict[str, Any]:
    token = settings.api_keys.tiingo_api_token
    token_present = bool(token and token.get_secret_value().strip())
    futu_status: dict[str, Any] = {"enabled": settings.futu.enabled}
    if settings.futu.enabled:
        futu_status.update(_probe_opend(settings.futu.host, settings.futu.port))
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.environment,
        "data_provider": {
            "configured_default": settings.data.default_data_provider,
            "tiingo_token_present": token_present,
        },
        "futu_opend": futu_status,
        "database": _database_status(settings),
        "hermes_command_ledger": _hermes_command_ledger_status(settings),
    }


def _database_status(settings: SettingsDep) -> dict[str, Any]:
    status: dict[str, Any] = {"enabled": settings.database.enabled}
    if not settings.database.enabled:
        return status
    try:
        from quant_system.storage.database import get_database

        database = get_database(settings)
        if database is None:
            status.update(reachable=False, error="database url not configured")
        else:
            reachable = database.healthy()
            status.update(
                reachable=reachable,
                error=None if reachable else database.last_error() or "connection failed",
            )
    except Exception as exc:  # noqa: BLE001 - health must not raise
        status.update(reachable=False, error=f"{exc.__class__.__name__}: {exc}")
    return status


def _hermes_command_ledger_status(settings: SettingsDep) -> dict[str, Any]:
    version = command_ledger_schema_version(settings)
    binding_version = workflow_binding_schema_version(settings)
    return {
        "database_configured": settings.database.enabled and settings.database.url is not None,
        "schema_ready": version is not None,
        "schema_version": version,
        "workflow_binding_schema_ready": binding_version is not None,
        "workflow_binding_schema_version": binding_version,
        # No authenticated same-origin + CSRF BFF mutation exists in Slice 3B.
        "mutation_enabled": False,
    }
