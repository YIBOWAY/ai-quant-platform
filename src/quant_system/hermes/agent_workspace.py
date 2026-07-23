"""Platform AgentWorkspace application module (V4).

Deep application surface for act / snapshot / follow. FastAPI routes stay thin
transport adapters and must not re-implement the recovery state machine.

Public browser mutation stays OFF: default ``mutation_enabled=False`` yields
``unavailable`` receipts with zero PostgreSQL writes for create/fork/turn.
Hermetic tests may pass ``mutation_enabled=True`` to exercise the crash-safe
submission saga against the isolated database only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
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
from quant_system.storage.database import get_database

# HQA-aligned public recovery codes (strings only; no HQA import).
_RECOVERY_RESNAPSHOT = "resnapshot_workspace"
_MANAGED_PROVISION_STATES = frozenset({"pending", "leased", "retryable", "ready", "failed"})


def _public_datetime(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValueError("managed session timestamps must be datetime values")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def project_managed_session_public(
    row: Mapping[str, Any],
) -> dict[str, object]:
    """Return bounded browser metadata for one durable managed Session.

    This is an observation of the platform registry, not a claim that a
    reserved Hermes Session already exists.  ``web_writable`` becomes true
    only after the provisioner has bound an exact Hermes receipt and advanced
    the durable row to ``ready``.
    """

    platform_session_id = str(row["platform_session_id"])
    hermes_session_id = str(row["hermes_session_id"])
    provision_state = str(row["provision_state"])
    if provision_state not in _MANAGED_PROVISION_STATES:
        raise ValueError("invalid managed session provision_state")
    parent = row.get("parent_platform_session_id")
    last_error = row.get("provision_last_error_code")
    return {
        "platform_session_id": platform_session_id,
        "session_ref": f"session:{platform_session_id}",
        "hermes_session_id": hermes_session_id,
        "provision_state": provision_state,
        "web_writable": provision_state == "ready",
        "attempt_count": max(0, int(row.get("provision_attempt_count") or 0)),
        "lease_until": _public_datetime(row.get("provision_lease_until")),
        "retry_at": _public_datetime(row.get("provision_next_attempt_at")),
        "last_error_code": (None if last_error is None else str(last_error)[:200]),
        "provisioned_at": _public_datetime(row.get("provisioned_at")),
        "parent_session_ref": (None if parent is None else f"session:{str(parent)}"),
        "fork_point": (None if row.get("fork_point") is None else str(row["fork_point"])[:200]),
        "created_at": _public_datetime(row.get("created_at")),
        "updated_at": _public_datetime(row.get("updated_at")),
    }


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
    # Durable provisioning facts for Web-managed sessions.  ``sessions`` stays
    # as the backwards-compatible id list; this projection carries honest
    # pending/leased/retryable/ready/failed state and exact Hermes identity.
    managed_sessions: tuple[dict[str, object], ...]
    tasks: tuple[str, ...]
    attempts: tuple[str, ...]
    commands: tuple[dict[str, object], ...]
    runs: tuple[str, ...]
    # V7f: typed result projections (objects). Empty honest; never bare invented Task rows.
    results: tuple[dict[str, object], ...]
    # L5a/V7a/V7d: Hermes command-approval challenges from hermetic authority
    # (pending + recent decided). Empty is honest; never invent Gate 1/2/3 rows.
    approvals: tuple[dict[str, object], ...]
    # V7e: Domain Gate 1/2/3 surfaces — separate from command-approval.
    gates: tuple[dict[str, object], ...]
    # V8-M5: hermetic canary grants (separate namespace; empty honest).
    canary_grants: tuple[dict[str, object], ...]
    public_cutovers: tuple[dict[str, object], ...]
    authority_health: Mapping[str, str]
    mutation_enabled: bool
    observed_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "workspace": {"workspace_id": self.workspace_id},
            "owner_user_id": self.owner_user_id,
            "snapshot_workspace_cursor": self.snapshot_workspace_cursor,
            "sessions": list(self.sessions),
            "managed_sessions": [dict(item) for item in self.managed_sessions],
            "tasks": list(self.tasks),
            "attempts": list(self.attempts),
            "commands": [dict(item) for item in self.commands],
            "runs": list(self.runs),
            "results": [dict(item) if isinstance(item, dict) else item for item in self.results],
            "approvals": [dict(item) for item in self.approvals],
            "gates": [dict(item) for item in self.gates],
            "canary_grants": [dict(item) for item in self.canary_grants],
            "public_cutovers": [dict(item) for item in self.public_cutovers],
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
    # V7e: optional gates projection (separate namespace from approvals).
    gates: tuple[dict[str, object], ...] | None = None
    # V8-M5: optional canary grants projection (never public-write).
    canary_grants: tuple[dict[str, object], ...] | None = None
    # V8-M6: optional public cutovers projection (G7/G8).
    public_cutovers: tuple[dict[str, object], ...] | None = None
    # V7f: optional typed results projection (separate from gates/approvals).
    results: tuple[dict[str, object], ...] | None = None
    # V7g-A-M1: optional Task/Attempt/Run id lists on follow (same as snapshot).
    tasks: tuple[str, ...] | None = None
    attempts: tuple[str, ...] | None = None
    runs: tuple[str, ...] | None = None
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
        if self.gates is not None:
            payload["gates"] = [dict(item) for item in self.gates]
        if self.canary_grants is not None:
            payload["canary_grants"] = [dict(item) for item in self.canary_grants]
        if self.public_cutovers is not None:
            payload["public_cutovers"] = [dict(item) for item in self.public_cutovers]
        if self.results is not None:
            payload["results"] = [dict(item) for item in self.results]
        if self.tasks is not None:
            payload["tasks"] = list(self.tasks)
        if self.attempts is not None:
            payload["attempts"] = list(self.attempts)
        if self.runs is not None:
            payload["runs"] = list(self.runs)
        if self.authority_health is not None:
            payload["authority_health"] = dict(self.authority_health)
        return payload


class PlatformAgentWorkspace:
    """Root-owner AgentWorkspace backed by durable production authorities.

    V7/V8 process-local authorities are contract-test adapters only.  They are
    mounted solely when ``hermetic_authorities=True`` is passed explicitly;
    the production BFF factory leaves that test-only switch off.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        mutation_enabled: bool = False,
        hermetic_authorities: bool = False,
    ) -> None:
        self._settings = settings
        # Public path hard-defaults False. Tests may flip these independently.
        self._mutation_enabled = bool(mutation_enabled)
        self._hermetic_authorities = bool(hermetic_authorities)

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
                raise SubmissionSagaError("validation", str(exc) or "validation") from exc
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
                allow_hermetic_authorities=self._hermetic_authorities,
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
        observed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        mutation_on = bool(self._mutation_enabled or ready.get("mutation_enabled"))
        composer_on = bool(ready.get("composer_write_ready") or ready.get("chat_write_ready"))
        process_authority_state = "hermetic" if self._hermetic_authorities else "unavailable"
        health: dict[str, str] = {
            "database": "ready" if ready["ready"] else "unavailable",
            "command_ledger": ("ready" if ready["command_ledger_schema_ready"] else "unavailable"),
            "session_registry": (
                "ready" if ready["session_registry_schema_ready"] else "unavailable"
            ),
            "workflow_binding": (
                "ready" if ready.get("workflow_binding_schema_ready") else "unavailable"
            ),
            "research_binding": ("ready" if ready.get("research_binding_ready") else "unavailable"),
            "hermes_gateway": "dark",
            "provider": "dark",
            "mutation": "enabled" if mutation_on else "disabled",
            "composer": "enabled" if composer_on else "disabled",
            # These V7/V8 projections are restart-volatile test adapters, never
            # production authority.  "hermetic" is deliberately not "ready".
            "command_approval": process_authority_state,
            "gate_1": process_authority_state,
            "gate_2": process_authority_state,
            "gate_3": process_authority_state,
            "task": process_authority_state,
            "attempt": process_authority_state,
            "run": process_authority_state,
            "result": process_authority_state,
            "canary_grant": process_authority_state,
            "public_cutover": process_authority_state,
        }

        sessions: list[str] = []
        managed_sessions: list[dict[str, object]] = []
        commands: list[dict[str, object]] = []
        cursor = 0

        if ready["ready"]:
            (
                sessions,
                managed_sessions,
                commands,
                cursor,
                projection_available,
            ) = self._collect_workspace_projection(workspace_id)
            if not projection_available:
                for authority_name in (
                    "database",
                    "command_ledger",
                    "session_registry",
                    "workflow_binding",
                    "research_binding",
                ):
                    health[authority_name] = "unavailable"

        process_projection = self._authority_spine_projections(workspace_id)

        return WorkspaceSnapshot(
            workspace_id=workspace_id,
            owner_user_id=str(owner),
            snapshot_workspace_cursor=cursor,
            sessions=tuple(sessions),
            managed_sessions=tuple(managed_sessions),
            tasks=process_projection["tasks"],  # type: ignore[arg-type]
            attempts=process_projection["attempts"],  # type: ignore[arg-type]
            commands=tuple(commands),
            runs=process_projection["runs"],  # type: ignore[arg-type]
            results=process_projection["results"],  # type: ignore[arg-type]
            approvals=process_projection["approvals"],  # type: ignore[arg-type]
            gates=process_projection["gates"],  # type: ignore[arg-type]
            canary_grants=process_projection["canary_grants"],  # type: ignore[arg-type]
            public_cutovers=process_projection["public_cutovers"],  # type: ignore[arg-type]
            authority_health=health,
            mutation_enabled=mutation_on,
            observed_at=observed_at,
        )

    def _authority_spine_projections(self, workspace_id: str) -> dict[str, object]:
        """Project explicitly mounted V7/V8 contract-test authorities.

        With the production default, every restart-volatile projection is empty
        and reports unavailable.  Durable session/command rows remain on their
        separate PostgreSQL projection and are unaffected.
        """
        authority_names = (
            "command_approval",
            "gate_1",
            "gate_2",
            "gate_3",
            "result",
            "task",
            "attempt",
            "run",
            "canary_grant",
            "public_cutover",
        )
        if not self._hermetic_authorities:
            return {
                "approvals": (),
                "gates": (),
                "canary_grants": (),
                "public_cutovers": (),
                "results": (),
                "tasks": (),
                "attempts": (),
                "runs": (),
                "authority_health": {name: "unavailable" for name in authority_names},
            }

        from quant_system.hermes.approval_observe import project_workspace_approvals
        from quant_system.hermes.canary_observe import project_workspace_canary_grants
        from quant_system.hermes.gate_observe import project_workspace_gates
        from quant_system.hermes.public_cutover_observe import (
            project_workspace_public_cutovers,
        )
        from quant_system.hermes.result_observe import project_workspace_results
        from quant_system.hermes.vertical_observe import (
            attempt_ids_for_spine,
            run_ids_for_spine,
            task_ids_for_spine,
        )

        return {
            "approvals": tuple(project_workspace_approvals(workspace_id)),
            "gates": tuple(project_workspace_gates(workspace_id)),
            "canary_grants": tuple(project_workspace_canary_grants(workspace_id)),
            "public_cutovers": tuple(project_workspace_public_cutovers(workspace_id)),
            "results": tuple(project_workspace_results(workspace_id)),
            "tasks": tuple(task_ids_for_spine(workspace_id)),
            "attempts": tuple(attempt_ids_for_spine(workspace_id)),
            "runs": tuple(run_ids_for_spine(workspace_id)),
            "authority_health": {name: "hermetic" for name in authority_names},
        }

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
        # Explicit contract-test projections attach even when durable command
        # events require resync. Production defaults to empty/unavailable.
        proj = self._authority_spine_projections(workspace_id)
        supplemental_health = dict(proj["authority_health"])  # type: ignore[arg-type]

        def _set_database_health(available: bool) -> None:
            state = "ready" if available else "unavailable"
            supplemental_health.update(
                {
                    "database": state,
                    "command_ledger": (
                        state if ready.get("command_ledger_schema_ready") else "unavailable"
                    ),
                    "session_registry": (
                        state if ready.get("session_registry_schema_ready") else "unavailable"
                    ),
                    "workflow_binding": (
                        state if ready.get("workflow_binding_schema_ready") else "unavailable"
                    ),
                    "research_binding": (
                        state if ready.get("research_binding_ready") else "unavailable"
                    ),
                }
            )
            proj["authority_health"] = supplemental_health

        _set_database_health(bool(ready["ready"]))
        if not ready["ready"]:
            # Fail closed on command events: client must resnapshot rather than
            # invent lifecycle rows. Hermetic projections still ride along so
            # SSE fingerprint journals can emit approvals/gates/results/vertical.
            return EventPage(
                events=(),
                after_cursor=after_value,
                next_cursor=None,
                resync_required=True,
                recovery_action=_RECOVERY_RESNAPSHOT,
                mutation_enabled=mutation_on,
                approvals=proj["approvals"],  # type: ignore[arg-type]
                gates=proj["gates"],  # type: ignore[arg-type]
                canary_grants=proj["canary_grants"],  # type: ignore[arg-type]
                public_cutovers=proj["public_cutovers"],  # type: ignore[arg-type]
                results=proj["results"],  # type: ignore[arg-type]
                tasks=proj["tasks"],  # type: ignore[arg-type]
                attempts=proj["attempts"],  # type: ignore[arg-type]
                runs=proj["runs"],  # type: ignore[arg-type]
                authority_health=proj["authority_health"],  # type: ignore[arg-type]
            )

        # L2b-M1: poll page over workspace-scoped hermes_command_events.
        # Cursor is the global event_id sequence (monotonic, durable).
        page_limit = limit if type(limit) is int and 1 <= limit <= 200 else 100
        after_cursor = 0 if after_value is None else after_value
        try:
            events, next_cursor, resync, database_available = self._collect_workspace_events(
                workspace_id,
                after_cursor=after_cursor,
                limit=page_limit,
            )
            _set_database_health(database_available)
        except Exception:
            _set_database_health(False)
            return EventPage(
                events=(),
                after_cursor=after_value,
                next_cursor=None,
                resync_required=True,
                recovery_action=_RECOVERY_RESNAPSHOT,
                mutation_enabled=mutation_on,
                approvals=proj["approvals"],  # type: ignore[arg-type]
                gates=proj["gates"],  # type: ignore[arg-type]
                canary_grants=proj["canary_grants"],  # type: ignore[arg-type]
                public_cutovers=proj["public_cutovers"],  # type: ignore[arg-type]
                results=proj["results"],  # type: ignore[arg-type]
                tasks=proj["tasks"],  # type: ignore[arg-type]
                attempts=proj["attempts"],  # type: ignore[arg-type]
                runs=proj["runs"],  # type: ignore[arg-type]
                authority_health=proj["authority_health"],  # type: ignore[arg-type]
            )
        if resync:
            return EventPage(
                events=(),
                after_cursor=after_value,
                next_cursor=None,
                resync_required=True,
                recovery_action=_RECOVERY_RESNAPSHOT,
                mutation_enabled=mutation_on,
                approvals=proj["approvals"],  # type: ignore[arg-type]
                gates=proj["gates"],  # type: ignore[arg-type]
                canary_grants=proj["canary_grants"],  # type: ignore[arg-type]
                public_cutovers=proj["public_cutovers"],  # type: ignore[arg-type]
                results=proj["results"],  # type: ignore[arg-type]
                tasks=proj["tasks"],  # type: ignore[arg-type]
                attempts=proj["attempts"],  # type: ignore[arg-type]
                runs=proj["runs"],  # type: ignore[arg-type]
                authority_health=proj["authority_health"],  # type: ignore[arg-type]
            )
        return EventPage(
            events=tuple(events),
            after_cursor=after_value,
            next_cursor=next_cursor,
            resync_required=False,
            recovery_action=None,
            mutation_enabled=mutation_on,
            approvals=proj["approvals"],  # type: ignore[arg-type]
            gates=proj["gates"],  # type: ignore[arg-type]
            canary_grants=proj["canary_grants"],  # type: ignore[arg-type]
            public_cutovers=proj["public_cutovers"],  # type: ignore[arg-type]
            results=proj["results"],  # type: ignore[arg-type]
            tasks=proj["tasks"],  # type: ignore[arg-type]
            attempts=proj["attempts"],  # type: ignore[arg-type]
            runs=proj["runs"],  # type: ignore[arg-type]
            authority_health=proj["authority_health"],  # type: ignore[arg-type]
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
    ) -> tuple[
        list[str],
        list[dict[str, object]],
        list[dict[str, object]],
        int,
        bool,
    ]:
        """Read session/command projections and report database availability.

        The final boolean is true only when the read reached PostgreSQL.  The
        snapshot remains structurally available during an outage, while health
        distinguishes unavailable-empty from healthy-empty.
        """
        from quant_system.hermes.submission_saga import control_plane_session_id
        from quant_system.hermes.workspace_observe import project_command_public
        from quant_system.storage.database import SCHEMA

        sessions: list[str] = []
        managed_sessions: list[dict[str, object]] = []
        commands: list[dict[str, object]] = []
        cursor = 0
        database = get_database(self._settings)
        if database is None:
            return sessions, managed_sessions, commands, cursor, False
        try:
            with database.connect() as conn:
                sessions = self._workspace_session_ids(conn, workspace_id)
                managed_rows = conn.execute(
                    f"""
                    SELECT
                        platform_session_id,
                        hermes_session_id,
                        provision_state,
                        provision_attempt_count,
                        provision_lease_until,
                        provision_next_attempt_at,
                        provision_last_error_code,
                        provisioned_at,
                        parent_platform_session_id,
                        fork_point,
                        created_at,
                        updated_at
                    FROM {SCHEMA}.hermes_workspace_sessions
                    WHERE workspace_id = %s
                      AND owner_user_id = %s
                      AND kind = 'web_managed_session'
                    ORDER BY created_at ASC
                    LIMIT 200
                    """,
                    (workspace_id, ROOT_USER_ID),
                ).fetchall()
                managed_sessions = [
                    project_managed_session_public(
                        {
                            "platform_session_id": row[0],
                            "hermes_session_id": row[1],
                            "provision_state": row[2],
                            "provision_attempt_count": row[3],
                            "provision_lease_until": row[4],
                            "provision_next_attempt_at": row[5],
                            "provision_last_error_code": row[6],
                            "provisioned_at": row[7],
                            "parent_platform_session_id": row[8],
                            "fork_point": row[9],
                            "created_at": row[10],
                            "updated_at": row[11],
                        }
                    )
                    for row in managed_rows
                ]
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
        except Exception:
            return [], [], [], 0, False
        return sessions, managed_sessions, commands, cursor, True

    def _collect_workspace_events(
        self,
        workspace_id: str,
        *,
        after_cursor: int,
        limit: int,
    ) -> tuple[list[dict[str, object]], int | None, bool, bool]:
        """Return events, cursor, resync flag and database availability."""
        from quant_system.hermes.submission_saga import control_plane_session_id
        from quant_system.hermes.workspace_observe import (
            follow_resync_required,
            project_event_public,
        )
        from quant_system.storage.database import SCHEMA

        database = get_database(self._settings)
        if database is None:
            return [], None, True, False
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
            if follow_resync_required(after_cursor=after_cursor, head_event_id=head_event_id):
                return [], None, True, True
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
        return events, next_cursor, False, True

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
    hermetic_authorities: bool = False,
) -> PlatformAgentWorkspace:
    """Build a workspace; the production BFF leaves hermetic authorities off."""
    return PlatformAgentWorkspace(
        settings,
        mutation_enabled=mutation_enabled,
        hermetic_authorities=hermetic_authorities,
    )


__all__ = [
    "ActorRef",
    "EventPage",
    "PlatformAgentWorkspace",
    "WorkspaceCursor",
    "WorkspaceSnapshot",
    "build_platform_agent_workspace",
]
