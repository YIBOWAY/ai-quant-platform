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
    # L2b-M1: sessions remain id strings; commands are public objects.
    # Older clients that only need ids can read command_id from each object.
    sessions: tuple[str, ...]
    tasks: tuple[str, ...]
    attempts: tuple[str, ...]
    commands: tuple[dict[str, object], ...]
    runs: tuple[str, ...]
    results: tuple[str, ...]
    # L5a/V7a/V7d: Hermes command-approval challenges from hermetic authority
    # (pending + recent decided). Empty is honest; never invent Gate 1/2/3 rows.
    approvals: tuple[dict[str, object], ...]
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
            "commands": [dict(item) for item in self.commands],
            "runs": list(self.runs),
            "results": list(self.results),
            "approvals": [dict(item) for item in self.approvals],
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
    # V7d: optional approvals projection on follow pages so L4b spine can
    # refresh without inventing a private poll. None → omit from public dict
    # (BC for callers that only care about command events).
    approvals: tuple[dict[str, object], ...] | None = None
    authority_health: Mapping[str, str] | None = None

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "events": list(self.events),
            "after_cursor": self.after_cursor,
            "next_cursor": self.next_cursor,
            "resync_required": self.resync_required,
            "recovery_action": self.recovery_action,
            "mutation_enabled": self.mutation_enabled,
        }
        if self.approvals is not None:
            payload["approvals"] = [dict(item) for item in self.approvals]
        if self.authority_health is not None:
            payload["authority_health"] = dict(self.authority_health)
        return payload


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
        payload = dict(payload)
        # Settings-driven public flag (LocalMutationSettings) is authoritative.
        # in_process_mutation_gate mirrors the workspace constructor override used
        # by hermetic saga tests / BFF injection.
        payload["mutation_enabled"] = bool(
            payload.get("mutation_enabled") or self._mutation_enabled
        )
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
                mutation_enabled=self._mutation_enabled,
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
        mutation_on = bool(self._mutation_enabled or ready.get("mutation_enabled"))
        composer_on = bool(ready.get("composer_write_ready") or ready.get("chat_write_ready"))
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
            "mutation": "enabled" if mutation_on else "disabled",
            "composer": "enabled" if composer_on else "disabled",
            # V7a: hermetic in-process command-approval authority may hold
            # pending challenges. Empty is still honest when none are seeded.
            "command_approval": "ready",
            # L5b: Task/Attempt/Run/result authority projectors not wired —
            # empty tuples stay empty; never invent HQA rows from commands.
            "task": "unavailable",
            "attempt": "unavailable",
            "run": "unavailable",
            "result": "unavailable",
        }

        sessions: list[str] = []
        commands: list[dict[str, object]] = []
        cursor = 0

        if ready["ready"]:
            sessions, commands, cursor = self._collect_workspace_projection(
                workspace_id
            )

        # V7a/V7d: project pending + recent decided command-approval challenges
        # from hermetic authority. Never invent Gate 1/2/3 or candidate approvals.
        from quant_system.hermes.approval_observe import project_workspace_approvals

        # Empty approvals[] is honest; health stays "ready" because the
        # hermetic in-process authority is mounted (not a live Hermes HTTP path).
        approvals = tuple(project_workspace_approvals(workspace_id))

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
            approvals=approvals,
            authority_health=health,
            mutation_enabled=mutation_on,
            observed_at=observed_at,
        )

    def follow(
        self,
        actor: ActorRef | Mapping[str, Any] | str,
        workspace: WorkspaceRef | Mapping[str, Any] | str,
        after: WorkspaceCursor | int | None = None,
        *,
        limit: int = 100,
    ) -> EventPage:
        owner = self._resolve_actor(actor)
        workspace_id = self._resolve_workspace_id(workspace)
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
        mutation_on = bool(self._mutation_enabled or ready.get("mutation_enabled"))
        if not ready["ready"]:
            # Fail closed: client must resnapshot rather than invent events.
            return EventPage(
                events=(),
                after_cursor=after_value,
                next_cursor=None,
                resync_required=True,
                recovery_action=_RECOVERY_RESNAPSHOT,
                mutation_enabled=mutation_on,
            )

        # L2b-M1: poll page over workspace-scoped hermes_command_events.
        # Cursor is the global event_id sequence (monotonic, durable).
        page_limit = limit if type(limit) is int and 1 <= limit <= 200 else 100
        after_cursor = 0 if after_value is None else after_value
        try:
            events, next_cursor, resync = self._collect_workspace_events(
                workspace_id,
                after_cursor=after_cursor,
                limit=page_limit,
            )
        except (DatabaseUnavailable, Exception):
            return EventPage(
                events=(),
                after_cursor=after_value,
                next_cursor=None,
                resync_required=True,
                recovery_action=_RECOVERY_RESNAPSHOT,
                mutation_enabled=mutation_on,
            )
        if resync:
            return EventPage(
                events=(),
                after_cursor=after_value,
                next_cursor=None,
                resync_required=True,
                recovery_action=_RECOVERY_RESNAPSHOT,
                mutation_enabled=mutation_on,
            )
        # V7d: attach current approvals projection so follow/SSE spine stays
        # honest without a dual private poll. Empty remains honest.
        from quant_system.hermes.approval_observe import project_workspace_approvals

        approvals = tuple(project_workspace_approvals(workspace_id))
        return EventPage(
            events=tuple(events),
            after_cursor=after_value,
            next_cursor=next_cursor,
            resync_required=False,
            recovery_action=None,
            mutation_enabled=mutation_on,
            approvals=approvals,
            authority_health={"command_approval": "ready"},
        )

    def _workspace_session_ids(self, conn: Any, workspace_id: str) -> list[str]:
        from quant_system.storage.database import SCHEMA

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
        return [str(row[0]) for row in rows]

    def _collect_workspace_projection(
        self, workspace_id: str
    ) -> tuple[list[str], list[dict[str, object]], int]:
        """Best-effort read of sessions + command objects + durable event cursor.

        Never raises for missing rows; authority outage surfaces as empty
        projection with health already marked unavailable by the caller when
        readiness is false. Here readiness is true.
        """
        from quant_system.hermes.submission_saga import control_plane_session_id
        from quant_system.hermes.workspace_observe import project_command_public
        from quant_system.storage.database import SCHEMA

        sessions: list[str] = []
        commands: list[dict[str, object]] = []
        cursor = 0
        database = get_database(self._settings)
        if database is None:
            return sessions, commands, cursor
        try:
            with database.connect() as conn:
                sessions = self._workspace_session_ids(conn, workspace_id)
                control = control_plane_session_id(workspace_id)
                session_filter = list(sessions) if sessions else []
                cmd_rows = conn.execute(
                    f"""
                    SELECT
                        command_id,
                        kind,
                        state,
                        version,
                        client_request_id,
                        platform_session_id,
                        hermes_session_id,
                        hermes_run_id,
                        last_error_code,
                        attempt_count,
                        updated_at,
                        created_at
                    FROM {SCHEMA}.hermes_commands
                    WHERE owner_user_id = %s
                      AND (
                        platform_session_id = %s
                        OR platform_session_id = ANY(%s)
                      )
                    ORDER BY created_at ASC
                    LIMIT 200
                    """,
                    (ROOT_USER_ID, control, session_filter or [""]),
                ).fetchall()
                for row in cmd_rows:
                    commands.append(
                        project_command_public(
                            {
                                "command_id": row[0],
                                "kind": row[1],
                                "state": row[2],
                                "version": row[3],
                                "client_request_id": row[4],
                                "platform_session_id": row[5],
                                "hermes_session_id": row[6],
                                "hermes_run_id": row[7],
                                "last_error_code": row[8],
                                "attempt_count": row[9],
                                "updated_at": row[10],
                                "created_at": row[11],
                            }
                        )
                    )
                # Durable cursor = max event_id among workspace-scoped commands
                # (control-plane session + registered workspace sessions).
                head = conn.execute(
                    f"""
                    SELECT COALESCE(MAX(e.event_id), 0)
                    FROM {SCHEMA}.hermes_command_events AS e
                    INNER JOIN {SCHEMA}.hermes_commands AS c
                      ON c.command_id = e.command_id
                    WHERE c.owner_user_id = %s
                      AND (
                        c.platform_session_id = %s
                        OR c.platform_session_id = ANY(%s)
                      )
                    """,
                    (ROOT_USER_ID, control, session_filter or [""]),
                ).fetchone()
                cursor = int(head[0]) if head is not None else 0
        except (DatabaseUnavailable, Exception):
            # Snapshot stays available with empty projection; health already set.
            return [], [], 0
        return sessions, commands, cursor

    def _collect_workspace_events(
        self,
        workspace_id: str,
        *,
        after_cursor: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], int | None, bool]:
        """Return (events, next_cursor, resync_required)."""
        from quant_system.hermes.submission_saga import control_plane_session_id
        from quant_system.hermes.workspace_observe import (
            follow_resync_required,
            project_event_public,
        )
        from quant_system.storage.database import SCHEMA

        database = get_database(self._settings)
        if database is None:
            return [], None, True
        with database.connect() as conn:
            sessions = self._workspace_session_ids(conn, workspace_id)
            control = control_plane_session_id(workspace_id)
            session_filter = list(sessions) if sessions else []
            head_row = conn.execute(
                f"""
                SELECT COALESCE(MAX(e.event_id), 0)
                FROM {SCHEMA}.hermes_command_events AS e
                INNER JOIN {SCHEMA}.hermes_commands AS c
                  ON c.command_id = e.command_id
                WHERE c.owner_user_id = %s
                  AND (
                    c.platform_session_id = %s
                    OR c.platform_session_id = ANY(%s)
                  )
                """,
                (ROOT_USER_ID, control, session_filter or [""]),
            ).fetchone()
            head_event_id = int(head_row[0]) if head_row is not None else 0
            if follow_resync_required(
                after_cursor=after_cursor, head_event_id=head_event_id
            ):
                return [], None, True
            rows = conn.execute(
                f"""
                SELECT
                    e.event_id,
                    e.command_id,
                    e.command_version,
                    e.event_type,
                    e.from_state,
                    e.to_state,
                    e.hermes_session_id,
                    e.hermes_run_id,
                    e.error_code,
                    e.occurred_at,
                    c.client_request_id,
                    c.kind,
                    c.platform_session_id
                FROM {SCHEMA}.hermes_command_events AS e
                INNER JOIN {SCHEMA}.hermes_commands AS c
                  ON c.command_id = e.command_id
                WHERE c.owner_user_id = %s
                  AND (
                    c.platform_session_id = %s
                    OR c.platform_session_id = ANY(%s)
                  )
                  AND e.event_id > %s
                ORDER BY e.event_id ASC
                LIMIT %s
                """,
                (
                    ROOT_USER_ID,
                    control,
                    session_filter or [""],
                    after_cursor,
                    limit,
                ),
            ).fetchall()
        events: list[dict[str, object]] = []
        next_cursor = after_cursor
        for row in rows:
            event_id = int(row[0])
            next_cursor = event_id
            events.append(
                project_event_public(
                    {
                        "event_id": event_id,
                        "command_id": row[1],
                        "command_version": row[2],
                        "event_type": row[3],
                        "from_state": row[4],
                        "to_state": row[5],
                        "hermes_session_id": row[6],
                        "hermes_run_id": row[7],
                        "error_code": row[8],
                        "occurred_at": row[9],
                    },
                    command={
                        "client_request_id": row[10],
                        "kind": row[11],
                        "platform_session_id": row[12],
                    },
                )
            )
        # Idle poll: keep cursor at after when no new events.
        if not events:
            next_cursor = after_cursor
        return events, next_cursor, False

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
