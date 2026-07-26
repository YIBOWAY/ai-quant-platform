from __future__ import annotations

import socket
from typing import Any

from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.health import HealthResponse
from quant_system.hermes.composer_readiness import authority_readiness

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
    ready = authority_readiness(settings)
    return {
        "database_configured": settings.database.enabled and settings.database.url is not None,
        "schema_ready": bool(ready["command_ledger_schema_ready"]),
        "schema_version": ready["command_ledger_schema_version"],
        "workflow_binding_schema_ready": bool(ready["workflow_binding_schema_ready"]),
        "workflow_binding_schema_version": ready["workflow_binding_schema_version"],
        "session_registry_schema_ready": bool(ready["session_registry_schema_ready"]),
        "session_registry_schema_version": ready["session_registry_schema_version"],
        # Ordinary create/fork/turn authorities (ledger + session registry).
        "agent_workspace_authorities_ready": bool(ready["ready"]),
        # Research prepare binding (ledger + session + 006 workflow binding).
        "research_binding_ready": bool(ready["research_binding_ready"]),
        "mutation_enabled": bool(ready["mutation_enabled"]),
        "composer_write_ready": bool(ready["composer_write_ready"]),
        "chat_write_ready": bool(ready["chat_write_ready"]),
        "admission_mode": ready["admission_mode"],
        "admission_workspace_id": ready["admission_workspace_id"],
        "configured_release_workspace_id": (ready["configured_release_workspace_id"]),
        "candidate_admission_id": ready["candidate_admission_id"],
        "candidate_admission_digest": ready["candidate_admission_digest"],
        "connector_liveness_ready": bool(ready["connector_liveness_ready"]),
        "connector_liveness_reason": ready["connector_liveness_reason"],
        "connector_worker_id": ready["connector_worker_id"],
        "connector_mode": ready["connector_mode"],
        "connector_heartbeat_age_seconds": (ready["connector_heartbeat_age_seconds"]),
        # Durable PostgreSQL ReleaseAuthority observation. These raw
        # identities remain visible while writes are fail-closed so operators
        # can distinguish "no cutover" from unrelated composer blockers.
        "release_authorized": bool(ready["release_authorized"]),
        "release_stamp_id": ready["release_stamp_id"],
        "public_cutover_id": ready["public_cutover_id"],
        "release_event_cursor": ready["release_event_cursor"],
    }
