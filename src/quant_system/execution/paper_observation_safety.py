"""Minimal provider-free safety input for already-hung paper observations."""

from __future__ import annotations

import re

import psycopg

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

_WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def observe_paper_emergency_stop(
    settings: Settings,
    *,
    workspace_id: str,
) -> dict[str, object]:
    """Read only the retained emergency-stop fact; unavailable means stopped."""
    if _WORKSPACE_RE.fullmatch(workspace_id) is None:
        raise ValueError("paper_observation_workspace_invalid")
    database = get_database(settings)
    if database is None:
        return {
            "active": True,
            "reason": "paper_observation_authority_unavailable",
            "created_at": None,
        }
    try:
        with database.connect() as connection:
            row = connection.execute(
                f"""
                SELECT enabled, reason, created_at
                FROM {SCHEMA}.d34_execution_authority_events
                WHERE owner_user_id = %s AND workspace_id = %s
                  AND event_type = 'emergency_stop'
                ORDER BY event_seq DESC LIMIT 1
                """,
                (ROOT_USER_ID, workspace_id),
            ).fetchone()
    except (DatabaseUnavailable, psycopg.Error):
        return {
            "active": True,
            "reason": "paper_observation_authority_unavailable",
            "created_at": None,
        }
    if row is None:
        return {"active": False, "reason": None, "created_at": None}
    return {
        "active": bool(row[0]),
        "reason": str(row[1]) if row[1] is not None else None,
        "created_at": row[2],
    }


def resolve_paper_observation_policy_context(
    settings: Settings,
    *,
    workspace_id: str,
) -> dict[str, object]:
    emergency = observe_paper_emergency_stop(settings, workspace_id=workspace_id)
    unavailable = emergency.get("reason") == "paper_observation_authority_unavailable"
    return {
        "contract": "hqa.paper_observation_policy_context/v1",
        "workspace_id": workspace_id,
        "paper_execution_enabled": False,
        "emergency_stop": emergency.get("active") is True,
        "authority_available": not unavailable,
        "mandate_active": False,
        "mandate_paper_execution_allowed": False,
        "blockers": ["paper_observation_authority_unavailable"] if unavailable else [],
    }


__all__ = [
    "observe_paper_emergency_stop",
    "resolve_paper_observation_policy_context",
]
