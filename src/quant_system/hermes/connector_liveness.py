"""Durable single-active liveness authority for the Hermes connector daemon.

The authority deliberately owns no connector work.  It never calls Hermes, a
provider, or a trading path.  A live daemon holds one PostgreSQL session-level
advisory lock while a generation row records its mode, content-addressed
runtime identity, and heartbeat.  The lock is released by PostgreSQL when the
connection/process dies; the durable row then fails closed by age and can be
replaced by the next lock holder.
"""

from __future__ import annotations

import re
import threading
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import psycopg

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

CONNECTOR_LIVENESS_SCHEMA_VERSION = 1
SUPERVISED_DISPATCH_MODE = "supervised_dispatch"
RECONCILE_ONLY_MODE = "reconcile_only"

ConnectorMode = Literal["supervised_dispatch", "reconcile_only"]
ConnectorStatus = Literal["active", "stopped", "stale"]

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_MODES = frozenset({SUPERVISED_DISPATCH_MODE, RECONCILE_ONLY_MODE})
_LOCK_PREFIX = "quant_system:agent_v02_connector:"
_DEFAULT_STOP_REASON = "connector_context_closed"

_WORKER_COLUMNS = """
    generation_token::text,
    workspace_id,
    worker_id,
    mode,
    runtime_digest,
    status,
    started_at,
    heartbeat_at,
    stopped_at,
    stop_reason
"""


class ConnectorLivenessError(RuntimeError):
    """Base exception with a stable machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConnectorLivenessValidationError(ConnectorLivenessError):
    def __init__(self, message: str) -> None:
        super().__init__("connector_liveness_validation", message)


class ConnectorLivenessUnavailable(ConnectorLivenessError):
    def __init__(self, message: str) -> None:
        super().__init__("connector_liveness_unavailable", message)


class ConnectorLivenessConflict(ConnectorLivenessError):
    def __init__(self, message: str) -> None:
        super().__init__("connector_liveness_already_held", message)


class ConnectorLivenessLeaseLost(ConnectorLivenessError):
    def __init__(self, message: str) -> None:
        super().__init__("connector_liveness_lease_lost", message)


@dataclass(frozen=True)
class ConnectorWorkerRecord:
    generation_token: str
    workspace_id: str
    worker_id: str
    mode: ConnectorMode
    runtime_digest: str
    status: ConnectorStatus
    started_at: datetime
    heartbeat_at: datetime
    stopped_at: datetime | None
    stop_reason: str | None


@dataclass(frozen=True)
class ConnectorLivenessProbe:
    ready: bool
    reason: str
    generation_token: str | None
    worker_id: str | None
    mode: str | None
    runtime_digest: str | None
    status: str | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    heartbeat_age_seconds: float | None
    session_lock_held: bool


def _validate_identifier(value: str, field: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ConnectorLivenessValidationError(f"{field} must be a bounded identifier")
    return value


def _validate_digest(value: str, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ConnectorLivenessValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _validate_mode(value: str) -> ConnectorMode:
    if value not in _MODES:
        raise ConnectorLivenessValidationError("mode must be supervised_dispatch or reconcile_only")
    return value  # type: ignore[return-value]


def _validate_timestamp(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ConnectorLivenessValidationError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _validate_max_age(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConnectorLivenessValidationError("max_heartbeat_age_seconds must be numeric")
    normalized = float(value)
    if normalized <= 0 or normalized > 3600:
        raise ConnectorLivenessValidationError("max_heartbeat_age_seconds must be in (0, 3600]")
    return normalized


def _validate_reason(value: str) -> str:
    if type(value) is not str:
        raise ConnectorLivenessValidationError("stop reason must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ConnectorLivenessValidationError(
            "stop reason must be nonempty and no longer than 500 characters"
        )
    return normalized


def _validate_generation(value: str) -> str:
    try:
        parsed = UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ConnectorLivenessValidationError("generation_token must be a UUID") from exc
    if str(parsed) != value:
        raise ConnectorLivenessValidationError(
            "generation_token must be a canonical lowercase UUID"
        )
    return value


def _lock_name(workspace_id: str) -> str:
    return f"{_LOCK_PREFIX}{workspace_id}"


def _record_from_row(row: tuple[object, ...]) -> ConnectorWorkerRecord:
    return ConnectorWorkerRecord(
        generation_token=str(row[0]),
        workspace_id=str(row[1]),
        worker_id=str(row[2]),
        mode=str(row[3]),  # type: ignore[arg-type]
        runtime_digest=str(row[4]).strip(),
        status=str(row[5]),  # type: ignore[arg-type]
        started_at=row[6],  # type: ignore[arg-type]
        heartbeat_at=row[7],  # type: ignore[arg-type]
        stopped_at=row[8],  # type: ignore[arg-type]
        stop_reason=None if row[9] is None else str(row[9]),
    )


def _empty_probe(reason: str) -> ConnectorLivenessProbe:
    return ConnectorLivenessProbe(
        ready=False,
        reason=reason,
        generation_token=None,
        worker_id=None,
        mode=None,
        runtime_digest=None,
        status=None,
        started_at=None,
        heartbeat_at=None,
        heartbeat_age_seconds=None,
        session_lock_held=False,
    )


def evaluate_connector_liveness(
    record: ConnectorWorkerRecord | None,
    *,
    expected_runtime_digest: str,
    now: datetime,
    max_heartbeat_age_seconds: float,
    session_lock_held: bool,
) -> ConnectorLivenessProbe:
    """Evaluate one exact gate observation without touching external systems."""

    expected_digest = _validate_digest(
        expected_runtime_digest,
        "expected_runtime_digest",
    )
    observed_at = _validate_timestamp(now, "now")
    max_age = _validate_max_age(max_heartbeat_age_seconds)
    if record is None:
        return _empty_probe("connector_generation_missing")

    heartbeat_at = _validate_timestamp(record.heartbeat_at, "heartbeat_at")
    heartbeat_age = (observed_at - heartbeat_at).total_seconds()
    common = {
        "generation_token": record.generation_token,
        "worker_id": record.worker_id,
        "mode": record.mode,
        "runtime_digest": record.runtime_digest,
        "status": record.status,
        "started_at": _validate_timestamp(record.started_at, "started_at"),
        "heartbeat_at": heartbeat_at,
        "heartbeat_age_seconds": heartbeat_age,
        "session_lock_held": bool(session_lock_held),
    }
    if record.status != "active":
        return ConnectorLivenessProbe(
            ready=False,
            reason="connector_not_active",
            **common,
        )
    if record.mode != SUPERVISED_DISPATCH_MODE:
        return ConnectorLivenessProbe(
            ready=False,
            reason="connector_mode_not_supervised",
            **common,
        )
    if record.runtime_digest != expected_digest:
        return ConnectorLivenessProbe(
            ready=False,
            reason="connector_runtime_digest_mismatch",
            **common,
        )
    if heartbeat_age < 0:
        return ConnectorLivenessProbe(
            ready=False,
            reason="connector_heartbeat_in_future",
            **common,
        )
    if heartbeat_age > max_age:
        return ConnectorLivenessProbe(
            ready=False,
            reason="connector_heartbeat_stale",
            **common,
        )
    if not session_lock_held:
        return ConnectorLivenessProbe(
            ready=False,
            reason="connector_session_lock_missing",
            **common,
        )
    return ConnectorLivenessProbe(ready=True, reason="ready", **common)


def connector_liveness_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    """Verify the exact durable table/index/trigger/RLS schema contract."""

    tables = (
        "agent_v02_connector_liveness_meta",
        "agent_v02_connector_workers",
    )
    relation_row = conn.execute(
        """
        SELECT count(*) = %s
        FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
        """,
        (len(tables), SCHEMA, list(tables)),
    ).fetchone()
    if relation_row != (True,):
        return False
    version = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_connector_liveness_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if version != (CONNECTOR_LIVENESS_SCHEMA_VERSION,):
        return False
    index_row = conn.execute(
        """
        SELECT count(*) = 1
        FROM pg_index index_row
        JOIN pg_class index_relation
          ON index_relation.oid = index_row.indexrelid
        JOIN pg_namespace namespace
          ON namespace.oid = index_relation.relnamespace
        WHERE namespace.nspname = %s
          AND index_relation.relname =
              'uq_agent_v02_connector_one_active_workspace'
          AND index_row.indisunique
          AND index_row.indpred IS NOT NULL
        """,
        (SCHEMA,),
    ).fetchone()
    if index_row != (True,):
        return False
    trigger_row = conn.execute(
        """
        SELECT count(*) = 1 AND bool_and(trigger.tgenabled = 'A')
        FROM pg_trigger trigger
        JOIN pg_class relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = 'agent_v02_connector_workers'
          AND trigger.tgname = 'trg_agent_v02_connector_worker_guard'
          AND NOT trigger.tgisinternal
        """,
        (SCHEMA,),
    ).fetchone()
    if trigger_row != (True,):
        return False
    security_row = conn.execute(
        """
        SELECT
            relation.relrowsecurity,
            relation.relforcerowsecurity,
            pg_get_userbyid(relation.relowner)
        FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = 'agent_v02_connector_workers'
        """,
        (SCHEMA,),
    ).fetchone()
    return security_row == (True, True, "quant_migrator")


def connector_liveness_runtime_security_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    """Require the constrained runtime login and exact least-privilege grants."""

    if not connector_liveness_schema_is_ready_on_connection(conn):
        return False
    principal = conn.execute(
        """
        SELECT
            EXISTS (
                SELECT 1
                FROM pg_roles
                WHERE rolname = session_user
                  AND rolcanlogin
                  AND NOT rolsuper
                  AND NOT rolbypassrls
                  AND NOT rolcreatedb
                  AND NOT rolcreaterole
                  AND NOT rolreplication
            ),
            current_user = session_user,
            pg_has_role(session_user, 'quant_runtime', 'MEMBER'),
            NOT pg_has_role(session_user, 'quant_migrator', 'MEMBER'),
            has_schema_privilege(session_user, %s, 'USAGE'),
            NOT has_schema_privilege(session_user, %s, 'CREATE')
        """,
        (SCHEMA, SCHEMA),
    ).fetchone()
    if principal is None or not all(bool(value) for value in principal):
        return False
    privileges = conn.execute(
        """
        SELECT
            has_table_privilege(
                session_user,
                %s,
                'SELECT,INSERT,UPDATE'
            ),
            NOT has_table_privilege(
                session_user,
                %s,
                'DELETE,TRUNCATE'
            ),
            has_table_privilege(
                session_user,
                %s,
                'SELECT'
            ),
            NOT has_table_privilege(
                session_user,
                %s,
                'INSERT,UPDATE,DELETE,TRUNCATE'
            )
        """,
        (
            f"{SCHEMA}.agent_v02_connector_workers",
            f"{SCHEMA}.agent_v02_connector_workers",
            f"{SCHEMA}.agent_v02_connector_liveness_meta",
            f"{SCHEMA}.agent_v02_connector_liveness_meta",
        ),
    ).fetchone()
    if privileges != (True, True, True, True):
        return False
    policies = conn.execute(
        """
        SELECT
            policy.polname,
            policy.polcmd,
            pg_get_expr(policy.polqual, policy.polrelid),
            pg_get_expr(policy.polwithcheck, policy.polrelid),
            ARRAY(
                SELECT role.rolname::text
                FROM unnest(policy.polroles) AS policy_role(role_oid)
                JOIN pg_roles role ON role.oid = policy_role.role_oid
                ORDER BY role.rolname::text
            )
        FROM pg_policy policy
        JOIN pg_class relation ON relation.oid = policy.polrelid
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = 'agent_v02_connector_workers'
          AND policy.polname = ANY(%s)
        """,
        (SCHEMA, ["v4r_root_scope", "v4r_migrator_all"]),
    ).fetchall()
    if {str(row[0]) for row in policies} != {
        "v4r_root_scope",
        "v4r_migrator_all",
    }:
        return False
    root_expression = "(owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid)"
    for policy_name, command, using, with_check, roles in policies:
        if str(command) != "*":
            return False
        normalized_using = " ".join(str(using).split())
        normalized_check = " ".join(str(with_check).split())
        normalized_roles = tuple(str(role) for role in roles)
        if policy_name == "v4r_root_scope":
            if (
                normalized_using != root_expression
                or normalized_check != root_expression
                or normalized_roles != ("quant_readonly", "quant_runtime")
            ):
                return False
        elif (
            normalized_using != "true"
            or normalized_check != "true"
            or normalized_roles != ("quant_migrator",)
        ):
            return False
    return True


class ConnectorLivenessLease:
    """One session-lock-backed connector generation.

    Keep this object open for the complete daemon lifetime.  ``heartbeat`` and
    ``stop`` are generation-CAS updates.  Closing the underlying connection
    releases the single-active advisory lock even after a process failure.
    """

    def __init__(
        self,
        *,
        authority: ConnectorLivenessAuthority,
        connection_manager: AbstractContextManager[psycopg.Connection],
        connection: psycopg.Connection,
        record: ConnectorWorkerRecord,
    ) -> None:
        self._authority = authority
        self._connection_manager = connection_manager
        self._connection = connection
        self._record = record
        self._mutex = threading.RLock()
        self._closed = False

    @property
    def record(self) -> ConnectorWorkerRecord:
        return self._record

    @property
    def generation_token(self) -> str:
        return self._record.generation_token

    def heartbeat(self, *, now: datetime) -> ConnectorWorkerRecord:
        heartbeat_at = _validate_timestamp(now, "now")
        with self._mutex:
            if self._closed:
                raise ConnectorLivenessLeaseLost("connector liveness lease connection is closed")
            if heartbeat_at < self._record.heartbeat_at:
                raise ConnectorLivenessValidationError("heartbeat cannot move backwards")
            try:
                record = self._authority._heartbeat_on_connection(
                    self._connection,
                    workspace_id=self._record.workspace_id,
                    worker_id=self._record.worker_id,
                    generation_token=self._record.generation_token,
                    now=heartbeat_at,
                )
            except psycopg.Error as exc:
                self._abandon_connection()
                raise ConnectorLivenessLeaseLost(
                    "connector liveness heartbeat lost its PostgreSQL session"
                ) from exc
            self._record = record
            return record

    def stop(
        self,
        *,
        now: datetime | None = None,
        reason: str = _DEFAULT_STOP_REASON,
    ) -> ConnectorWorkerRecord:
        stopped_at = _validate_timestamp(now or datetime.now(UTC), "now")
        stop_reason = _validate_reason(reason)
        with self._mutex:
            if self._closed:
                return self._record
            result: ConnectorWorkerRecord | None = None
            primary_error: BaseException | None = None
            try:
                row = self._connection.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_connector_workers
                    SET status = 'stopped',
                        stopped_at = GREATEST(%s, heartbeat_at),
                        stop_reason = %s
                    WHERE workspace_id = %s
                      AND worker_id = %s
                      AND generation_token = %s::uuid
                      AND status = 'active'
                    RETURNING {_WORKER_COLUMNS}
                    """,
                    (
                        stopped_at,
                        stop_reason,
                        self._record.workspace_id,
                        self._record.worker_id,
                        self._record.generation_token,
                    ),
                ).fetchone()
                if row is None:
                    raise ConnectorLivenessLeaseLost("connector generation is no longer active")
                result = _record_from_row(row)
                self._record = result
            except BaseException as exc:
                primary_error = exc
            finally:
                cleanup_error = self._release_connection()
            if primary_error is not None:
                if isinstance(primary_error, psycopg.Error):
                    raise ConnectorLivenessLeaseLost(
                        "connector stop lost its PostgreSQL session"
                    ) from primary_error
                raise primary_error
            if cleanup_error is not None:
                raise ConnectorLivenessLeaseLost(
                    "connector stopped but its session lock cleanup failed"
                ) from cleanup_error
            assert result is not None
            return result

    def _release_connection(self) -> BaseException | None:
        cleanup_error: BaseException | None = None
        try:
            if not self._connection.closed:
                unlocked = self._connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    (_lock_name(self._record.workspace_id),),
                ).fetchone()
                if unlocked != (True,):
                    cleanup_error = RuntimeError("connector session advisory lock was not held")
        except BaseException as exc:
            cleanup_error = exc
        try:
            self._connection_manager.__exit__(None, None, None)
        except BaseException as exc:
            if cleanup_error is None:
                cleanup_error = exc
        self._closed = True
        return cleanup_error

    def _abandon_connection(self) -> None:
        if self._closed:
            return
        try:
            self._connection_manager.__exit__(None, None, None)
        finally:
            self._closed = True

    def _disconnect_without_receipt_for_test(self) -> None:
        """Emulate process loss; deliberately private and test-only."""

        with self._mutex:
            self._abandon_connection()

    def __enter__(self) -> ConnectorLivenessLease:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        del exc, traceback
        reason = (
            _DEFAULT_STOP_REASON
            if exc_type is None
            else f"connector_context_error:{exc_type.__name__}"[:500]
        )
        self.stop(reason=reason)


class ConnectorLivenessAuthority:
    """PostgreSQL authority for connector generation liveness."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
    ) -> None:
        self._settings = settings
        self._database_override = database

    def _database(self) -> Database:
        database = self._database_override or get_database(self._settings)
        if database is None:
            raise ConnectorLivenessUnavailable("connector liveness requires PostgreSQL")
        return database

    def acquire(
        self,
        *,
        workspace_id: str,
        worker_id: str,
        mode: str,
        runtime_digest: str,
        now: datetime | None = None,
        generation_token: str | None = None,
    ) -> ConnectorLivenessLease:
        """Acquire the single-active session lock and start one generation."""

        workspace = _validate_identifier(workspace_id, "workspace_id")
        worker = _validate_identifier(worker_id, "worker_id")
        connector_mode = _validate_mode(mode)
        digest = _validate_digest(runtime_digest, "runtime_digest")
        started_at = _validate_timestamp(now or datetime.now(UTC), "now")
        generation = _validate_generation(generation_token or str(uuid4()))
        manager = self._database().connect()
        try:
            conn = manager.__enter__()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ConnectorLivenessUnavailable(
                "connector liveness PostgreSQL connection is unavailable"
            ) from exc
        lock_acquired = False
        try:
            lock_row = conn.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                (_lock_name(workspace),),
            ).fetchone()
            lock_acquired = lock_row == (True,)
            if not lock_acquired:
                raise ConnectorLivenessConflict(
                    "another connector generation holds the workspace lock"
                )
            with conn.transaction():
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_connector_workers
                    SET status = 'stale',
                        stopped_at = GREATEST(%s, heartbeat_at),
                        stop_reason = 'replaced_after_session_lock_release'
                    WHERE workspace_id = %s
                      AND status = 'active'
                    """,
                    (started_at, workspace),
                )
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_connector_workers (
                        generation_token,
                        owner_user_id,
                        workspace_id,
                        worker_id,
                        mode,
                        runtime_digest,
                        status,
                        started_at,
                        heartbeat_at
                    )
                    VALUES (
                        %s::uuid,
                        %s::uuid,
                        %s,
                        %s,
                        %s,
                        %s,
                        'active',
                        %s,
                        %s
                    )
                    RETURNING {_WORKER_COLUMNS}
                    """,
                    (
                        generation,
                        ROOT_USER_ID,
                        workspace,
                        worker,
                        connector_mode,
                        digest,
                        started_at,
                        started_at,
                    ),
                ).fetchone()
            if row is None:
                raise ConnectorLivenessUnavailable("connector generation insert returned no row")
            return ConnectorLivenessLease(
                authority=self,
                connection_manager=manager,
                connection=conn,
                record=_record_from_row(row),
            )
        except ConnectorLivenessConflict:
            manager.__exit__(None, None, None)
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            if lock_acquired:
                with suppress(psycopg.Error):
                    conn.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                        (_lock_name(workspace),),
                    )
            manager.__exit__(None, None, None)
            raise ConnectorLivenessUnavailable(
                "connector liveness generation could not start"
            ) from exc
        except BaseException:
            if lock_acquired:
                with suppress(psycopg.Error):
                    conn.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                        (_lock_name(workspace),),
                    )
            manager.__exit__(None, None, None)
            raise

    @staticmethod
    def _heartbeat_on_connection(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        worker_id: str,
        generation_token: str,
        now: datetime,
    ) -> ConnectorWorkerRecord:
        row = conn.execute(
            f"""
            UPDATE {SCHEMA}.agent_v02_connector_workers
            SET heartbeat_at = %s
            WHERE workspace_id = %s
              AND worker_id = %s
              AND generation_token = %s::uuid
              AND status = 'active'
              AND heartbeat_at <= %s
            RETURNING {_WORKER_COLUMNS}
            """,
            (
                now,
                workspace_id,
                worker_id,
                generation_token,
                now,
            ),
        ).fetchone()
        if row is None:
            raise ConnectorLivenessLeaseLost("connector heartbeat generation CAS failed")
        return _record_from_row(row)

    def _heartbeat_generation(
        self,
        *,
        workspace_id: str,
        worker_id: str,
        generation_token: str,
        now: datetime,
    ) -> ConnectorWorkerRecord:
        """Generation-CAS helper retained for recovery tests and diagnostics."""

        workspace = _validate_identifier(workspace_id, "workspace_id")
        worker = _validate_identifier(worker_id, "worker_id")
        generation = _validate_generation(generation_token)
        heartbeat_at = _validate_timestamp(now, "now")
        try:
            with self._database().connect() as conn:
                return self._heartbeat_on_connection(
                    conn,
                    workspace_id=workspace,
                    worker_id=worker,
                    generation_token=generation,
                    now=heartbeat_at,
                )
        except ConnectorLivenessLeaseLost:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ConnectorLivenessUnavailable(
                "connector heartbeat PostgreSQL update is unavailable"
            ) from exc

    def probe(
        self,
        *,
        workspace_id: str,
        expected_runtime_digest: str,
        now: datetime | None = None,
        max_heartbeat_age_seconds: float = 30,
    ) -> ConnectorLivenessProbe:
        """Read one fail-closed gate observation, including the session lock."""

        workspace = _validate_identifier(workspace_id, "workspace_id")
        digest = _validate_digest(
            expected_runtime_digest,
            "expected_runtime_digest",
        )
        observed_at = _validate_timestamp(now or datetime.now(UTC), "now")
        max_age = _validate_max_age(max_heartbeat_age_seconds)
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_WORKER_COLUMNS}
                    FROM {SCHEMA}.agent_v02_connector_workers
                    WHERE workspace_id = %s
                    ORDER BY
                        (status = 'active') DESC,
                        started_at DESC,
                        generation_token DESC
                    LIMIT 1
                    """,
                    (workspace,),
                ).fetchone()
                lock_probe = conn.execute(
                    "SELECT pg_try_advisory_lock_shared(hashtextextended(%s, 0))",
                    (_lock_name(workspace),),
                ).fetchone()
                shared_acquired = lock_probe == (True,)
                if shared_acquired:
                    unlocked = conn.execute(
                        "SELECT pg_advisory_unlock_shared(hashtextextended(%s, 0))",
                        (_lock_name(workspace),),
                    ).fetchone()
                    if unlocked != (True,):
                        raise ConnectorLivenessUnavailable(
                            "connector gate probe could not release its shared lock"
                        )
        except ConnectorLivenessUnavailable:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ConnectorLivenessUnavailable(
                "connector liveness gate probe is unavailable"
            ) from exc
        record = None if row is None else _record_from_row(row)
        return evaluate_connector_liveness(
            record,
            expected_runtime_digest=digest,
            now=observed_at,
            max_heartbeat_age_seconds=max_age,
            session_lock_held=not shared_acquired,
        )


__all__ = [
    "CONNECTOR_LIVENESS_SCHEMA_VERSION",
    "RECONCILE_ONLY_MODE",
    "SUPERVISED_DISPATCH_MODE",
    "ConnectorLivenessAuthority",
    "ConnectorLivenessConflict",
    "ConnectorLivenessError",
    "ConnectorLivenessLease",
    "ConnectorLivenessLeaseLost",
    "ConnectorLivenessProbe",
    "ConnectorLivenessUnavailable",
    "ConnectorLivenessValidationError",
    "ConnectorWorkerRecord",
    "connector_liveness_runtime_security_is_ready_on_connection",
    "connector_liveness_schema_is_ready_on_connection",
    "evaluate_connector_liveness",
]
