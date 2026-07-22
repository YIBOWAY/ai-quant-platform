"""L2b-Observe-M1: pure public projection for workspace snapshot/follow.

Maps ledger command rows and append-only command events into browser-safe
dicts. No I/O, no HQA import, no prompt/payload bodies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

# Terminal / lifecycle states the browser poller cares about.
_TERMINAL_STATES = frozenset(
    {
        "delivered",
        "cancelled",
        "failed",
        "rejected",
        "timed_out",
        "outcome_unknown",
    }
)

# Raw ledger event_type → public follow type (command.<state-ish>).
# Prefer to_state when present; this table covers known event_type labels.
_EVENT_TYPE_PUBLIC = {
    "command_created": "command.queued",
    "command_leased": "command.leased",
    "lease_heartbeat": "command.lease_heartbeat",
    "dispatch_started": "command.dispatch_started",
    "command_delivered": "command.delivered",
    "dispatch_timed_out": "command.timed_out",
    "dispatch_rejected": "command.rejected",
    "outcome_reconciled_delivered": "command.delivered",
    "lease_expired_requeued": "command.queued",
    "lease_expired_outcome_unknown": "command.outcome_unknown",
    "command_cancelled": "command.cancelled",
    "command_failed": "command.failed",
    "command_rejected": "command.rejected",
    "command_timed_out": "command.timed_out",
    "command_outcome_unknown": "command.outcome_unknown",
}


def _dt_public(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _uuid_text(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def public_event_type(*, event_type: str, to_state: str | None) -> str:
    """Stable browser event name. Prefer explicit map, else command.<to_state>."""
    mapped = _EVENT_TYPE_PUBLIC.get(event_type)
    if mapped is not None:
        return mapped
    if type(to_state) is str and to_state:
        return f"command.{to_state}"
    return f"command.event"


def project_command_public(row: Mapping[str, Any]) -> dict[str, object]:
    """Browser-safe command projection (no payload body)."""
    command_id = row["command_id"]
    return {
        "command_id": _uuid_text(command_id),
        "kind": str(row["kind"]),
        "state": str(row["state"]),
        "version": int(row["version"]),
        "client_request_id": str(row["client_request_id"]),
        "client_action_id": str(row["client_request_id"]),
        "platform_session_id": str(row["platform_session_id"]),
        "hermes_session_id": (
            None
            if row.get("hermes_session_id") is None
            else str(row["hermes_session_id"])
        ),
        "hermes_run_id": (
            None if row.get("hermes_run_id") is None else str(row["hermes_run_id"])
        ),
        "last_error_code": (
            None
            if row.get("last_error_code") is None
            else str(row["last_error_code"])
        ),
        "attempt_count": int(row.get("attempt_count") or 0),
        "updated_at": _dt_public(row.get("updated_at")),  # type: ignore[arg-type]
        "created_at": _dt_public(row.get("created_at")),  # type: ignore[arg-type]
    }


def project_event_public(
    event: Mapping[str, Any],
    *,
    command: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Browser-safe follow event. Joins command identity when provided."""
    to_state = event.get("to_state")
    to_state_s = None if to_state is None else str(to_state)
    event_type = str(event["event_type"])
    command_id = event["command_id"]
    client_request_id = None
    kind = None
    platform_session_id = None
    if command is not None:
        client_request_id = str(command["client_request_id"])
        kind = str(command["kind"])
        platform_session_id = str(command["platform_session_id"])
    payload: dict[str, object] = {
        "event_id": int(event["event_id"]),
        "type": public_event_type(event_type=event_type, to_state=to_state_s),
        "event_type": event_type,
        "command_id": _uuid_text(command_id),
        "command_version": int(event["command_version"]),
        "client_request_id": client_request_id,
        "client_action_id": client_request_id,
        "kind": kind,
        "platform_session_id": platform_session_id,
        "from_state": (
            None if event.get("from_state") is None else str(event["from_state"])
        ),
        "state": to_state_s,
        "hermes_session_id": (
            None
            if event.get("hermes_session_id") is None
            else str(event["hermes_session_id"])
        ),
        "hermes_run_id": (
            None if event.get("hermes_run_id") is None else str(event["hermes_run_id"])
        ),
        "error_code": (
            None if event.get("error_code") is None else str(event["error_code"])
        ),
        "occurred_at": _dt_public(event.get("occurred_at")),  # type: ignore[arg-type]
    }
    return payload


def is_terminal_command_state(state: str | None) -> bool:
    return type(state) is str and state in _TERMINAL_STATES


def follow_resync_required(*, after_cursor: int, head_event_id: int) -> bool:
    """Cursor ahead of known head → client must resnapshot (no silent holes)."""
    if after_cursor < 0:
        return True
    # after == head is idle (empty page); after > head is unknown future.
    return after_cursor > head_event_id


__all__ = [
    "follow_resync_required",
    "is_terminal_command_state",
    "project_command_public",
    "project_event_public",
    "public_event_type",
]
