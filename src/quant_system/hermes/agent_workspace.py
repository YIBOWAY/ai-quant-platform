"""Platform AgentWorkspace application module (V4).

Deep application surface for act / snapshot / follow. FastAPI routes stay thin
transport adapters and must not re-implement the recovery state machine.

Public browser mutation stays OFF: default ``mutation_enabled=False`` yields
``unavailable`` receipts with zero PostgreSQL writes for create/fork/turn.
Hermetic tests may pass ``mutation_enabled=True`` to exercise the crash-safe
submission saga against the isolated database only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from quant_system.config.settings import Settings
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    UserActionV1,
    WorkspaceRef,
    action_to_document,
    parse_user_action_v1,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.submission_saga import (
    ActionReceipt,
    SubmissionSagaError,
    authorities_ready,
    submit_action,
)
from quant_system.storage.database import DatabaseUnavailable, get_database

# HQA-aligned public recovery codes (strings only; no HQA import).
_RECOVERY_RESNAPSHOT = "resnapshot_workspace"


@dataclass(frozen=True)
class ActorRef:
    owner_user_id: str

    def __post_init__(self) -> None:
        if type(self.owner_user_id) is not str or not self.owner_user_id:
            raise ValueError("owner_user_id must be a non-empty string")
        try:
            UUID(self.owner_user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("owner_user_id must be a UUID string") from exc


@dataclass(frozen=True)
class WorkspaceCursor:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int or not 0 <= self.value <= (2**63 - 1):
            raise ValueError("workspace cursor must be a non-negative 63-bit integer")


@dataclass(frozen=True)
class WorkspaceSnapshot:
    workspace_id: str
    owner_user_id: str
    snapshot_workspace_cursor: int
    sessions: tuple[str, ...]
    tasks: tuple[str, ...]
    attempts: tuple[str, ...]
    commands: tuple[str, ...]
    runs: tuple[str, ...]
    results: tuple[str, ...]
    authority_health: Mapping[str, str]
    mutation_enabled: bool
    observed_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "workspace": {"workspace_id": self.workspace_id},
            "owner_user_id": self.owner_user_id,
            "snapshot_workspace_cursor": self.snapshot_workspace_cursor,
            "sessions": list(self.sessions),
            "tasks": list(self.tasks),
            "attempts": list(self.attempts),
            "commands": list(self.commands),
            "runs": list(self.runs),
            "results": list(self.results),
            "authority_health": dict(self.authority_health),
            "mutation_enabled": self.mutation_enabled,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class EventPage:
    events: tuple[dict[str, object], ...]
    after_cursor: int | None
    next_cursor: int | None
    resync_required: bool
    recovery_action: str | None
    mutation_enabled: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "events": list(self.events),
            "after_cursor": self.after_cursor,
            "next_cursor": self.next_cursor,
            "resync_required": self.resync_required,
            "recovery_action": self.recovery_action,
            "mutation_enabled": self.mutation_enabled,
        }


class PlatformAgentWorkspace:
    """Root-owner AgentWorkspace backed by PG authorities (V4 skeleton)."""

    def __init__(
        self,
        settings: Settings,
        *,
        mutation_enabled: bool = False,
    ) -> None:
        self._settings = settings
        # Public path hard-defaults False. Tests may flip True in-process only.
        self._mutation_enabled = bool(mutation_enabled)

    @property
    def mutation_enabled(self) -> bool:
        return self._mutation_enabled

    def authorities(self) -> dict[str, object]:
        payload = authorities_ready(self._settings)
        # Always advertise public mutation OFF even when hermetic tests enable
        # the in-process write gate for saga coverage.
        payload = dict(payload)
        payload["mutation_enabled"] = False
        payload["in_process_mutation_gate"] = self._mutation_enabled
        return payload

    def act(
        self,
        actor: ActorRef | Mapping[str, Any] | str,
        action: UserActionV1 | Mapping[str, Any],
    ) -> ActionReceipt:
        owner = self._resolve_actor(actor)
        if owner != ROOT_USER_ID:
            # Fail closed before any authority I/O.
            try:
                if isinstance(action, Mapping):
                    parsed = parse_user_action_v1(dict(action))
                else:
                    parsed = parse_user_action_v1(action_to_document(action))
            except (AgentWorkspaceActionError, TypeError, ValueError) as exc:
                raise SubmissionSagaError(
                    "validation", str(exc) or "validation"
                ) from exc
            from quant_system.hermes.agent_workspace_actions import (
                canonical_action_digest,
            )

            return ActionReceipt(
                status="unavailable",
                client_action_id=parsed.client_action_id,
                action_digest=canonical_action_digest(parsed),
                workspace_id=parsed.workspace.workspace_id,
                reason_code="workspace_forbidden",
            )

        try:
            return submit_action(
                self._settings,
                action if not isinstance(action, Mapping) else dict(action),
                mutation_enabled=self._mutation_enabled,
                actor_owner_user_id=owner,
            )
        except SubmissionSagaError:
            raise

    def snapshot(
        self,
        actor: ActorRef | Mapping[str, Any] | str,
        workspace: WorkspaceRef | Mapping[str, Any] | str,
    ) -> WorkspaceSnapshot:
        owner = self._resolve_actor(actor)
        workspace_id = self._resolve_workspace_id(workspace)
        if owner != ROOT_USER_ID:
            raise SubmissionSagaError("forbidden", "workspace_forbidden")

        ready = authorities_ready(self._settings)
        observed_at = (
            datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        )
        health: dict[str, str] = {
            "command_ledger": (
                "ready" if ready["command_ledger_schema_ready"] else "unavailable"
            ),
            "session_registry": (
                "ready" if ready["session_registry_schema_ready"] else "unavailable"
            ),
            "workflow_binding": (
                "ready"
                if ready.get("workflow_binding_schema_ready")
                else "unavailable"
            ),
            "research_binding": (
                "ready" if ready.get("research_binding_ready") else "unavailable"
            ),
            "hermes_gateway": "dark",
            "provider": "dark",
            "mutation": "disabled",
            "composer": "disabled",
        }

        sessions: list[str] = []
        commands: list[str] = []
        cursor = 0

        if ready["ready"]:
            sessions, commands, cursor = self._collect_workspace_projection(
                workspace_id
            )

        return WorkspaceSnapshot(
            workspace_id=workspace_id,
            owner_user_id=str(owner),
            snapshot_workspace_cursor=cursor,
            sessions=tuple(sessions),
            tasks=(),
            attempts=(),
            commands=tuple(commands),
            runs=(),
            results=(),
            authority_health=health,
            mutation_enabled=False,
            observed_at=observed_at,
        )

    def follow(
        self,
        actor: ActorRef | Mapping[str, Any] | str,
        workspace: WorkspaceRef | Mapping[str, Any] | str,
        after: WorkspaceCursor | int | None = None,
    ) -> EventPage:
        owner = self._resolve_actor(actor)
        _ = self._resolve_workspace_id(workspace)
        if owner != ROOT_USER_ID:
            raise SubmissionSagaError("forbidden", "workspace_forbidden")

        after_value: int | None
        if after is None:
            after_value = None
        elif isinstance(after, WorkspaceCursor):
            after_value = after.value
        elif type(after) is int and 0 <= after <= (2**63 - 1):
            after_value = after
        else:
            raise SubmissionSagaError("validation", "invalid after cursor")

        ready = authorities_ready(self._settings)
        if not ready["ready"]:
            # Fail closed: client must resnapshot rather than invent events.
            return EventPage(
                events=(),
                after_cursor=after_value,
                next_cursor=None,
                resync_required=True,
                recovery_action=_RECOVERY_RESNAPSHOT,
                mutation_enabled=False,
            )

        # V4 skeleton: no durable workspace observation stream yet (V6).
        # Empty ordinary page keeps the cursor stable so clients can poll.
        return EventPage(
            events=(),
            after_cursor=after_value,
            next_cursor=after_value,
            resync_required=False,
            recovery_action=None,
            mutation_enabled=False,
        )

    def _collect_workspace_projection(
        self, workspace_id: str
    ) -> tuple[list[str], list[str], int]:
        """Best-effort read of sessions + control-plane commands for snapshot.

        Never raises for missing rows; authority outage surfaces as empty
        projection with health already marked unavailable by the caller when
        readiness is false. Here readiness is true.
        """
        from quant_system.hermes.submission_saga import control_plane_session_id
        from quant_system.storage.database import SCHEMA

        sessions: list[str] = []
        commands: list[str] = []
        cursor = 0
        database = get_database(self._settings)
        if database is None:
            return sessions, commands, cursor
        try:
            with database.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT platform_session_id
                    FROM {SCHEMA}.hermes_workspace_sessions
                    WHERE workspace_id = %s
                      AND owner_user_id = %s
                    ORDER BY created_at ASC
                    """,
                    (workspace_id, ROOT_USER_ID),
                ).fetchall()
                sessions = [str(row[0]) for row in rows]

                control = control_plane_session_id(workspace_id)
                cmd_rows = conn.execute(
                    f"""
                    SELECT command_id::text
                    FROM {SCHEMA}.hermes_commands
                    WHERE owner_user_id = %s
                      AND (
                        platform_session_id = %s
                        OR platform_session_id = ANY(%s)
                      )
                    ORDER BY created_at ASC
                    LIMIT 200
                    """,
                    (ROOT_USER_ID, control, sessions or [""]),
                ).fetchall()
                commands = [str(row[0]) for row in cmd_rows]
                cursor = len(sessions) + len(commands)
        except (DatabaseUnavailable, Exception):
            # Snapshot stays available with empty projection; health already set.
            return [], [], 0
        return sessions, commands, cursor

    @staticmethod
    def _resolve_actor(actor: ActorRef | Mapping[str, Any] | str) -> UUID:
        if isinstance(actor, ActorRef):
            raw = actor.owner_user_id
        elif isinstance(actor, Mapping):
            raw = actor.get("owner_user_id")
        elif isinstance(actor, str):
            raw = actor
        elif isinstance(actor, UUID):
            return actor
        else:
            raise SubmissionSagaError("validation", "invalid actor")
        try:
            return UUID(str(raw))
        except (TypeError, ValueError) as exc:
            raise SubmissionSagaError("validation", "invalid actor") from exc

    @staticmethod
    def _resolve_workspace_id(
        workspace: WorkspaceRef | Mapping[str, Any] | str,
    ) -> str:
        if isinstance(workspace, WorkspaceRef):
            return workspace.workspace_id
        if isinstance(workspace, Mapping):
            value = workspace.get("workspace_id")
        elif isinstance(workspace, str):
            value = workspace
        else:
            raise SubmissionSagaError("validation", "invalid workspace")
        if type(value) is not str or not value:
            raise SubmissionSagaError("validation", "invalid workspace")
        return value


def build_platform_agent_workspace(
    settings: Settings,
    *,
    mutation_enabled: bool = False,
) -> PlatformAgentWorkspace:
    """Factory used by routes/tests. Public callers must leave mutation off."""
    return PlatformAgentWorkspace(settings, mutation_enabled=mutation_enabled)


__all__ = [
    "ActorRef",
    "EventPage",
    "PlatformAgentWorkspace",
    "WorkspaceCursor",
    "WorkspaceSnapshot",
    "build_platform_agent_workspace",
]
