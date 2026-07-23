"""PostgreSQL operator release authority for Agent v0.2.

The authority is deliberately smaller than the release workflow around it:

* it freezes exact Platform/HQA/Hermes runtime identities, the live database
  schema fingerprint, and an external evidence digest;
* it derives the release/cutover digests itself (there is no caller-supplied
  ``build_digest`` escape hatch);
* it serializes writes per workspace and freezes the first action receipt;
* it exposes append-only events with a durable cursor for health/SSE consumers.

This module does not decide whether the current runtimes still match the stamp.
That independent comparison belongs to :mod:`effective_release_gate`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import psycopg

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
    schema_fingerprint,
)

RELEASE_AUTHORITY_SCHEMA_VERSION = 1
RELEASE_ROUTE = "/hermes"
ReleaseStatus = Literal["active", "closed"]
CutoverStatus = Literal["open", "closed"]

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_OPERATIONS = frozenset(
    {
        "release.open",
        "release.close",
        "public_cutover.open",
        "public_cutover.close",
    }
)

_STAMP_COLUMNS = """
    stamp_id,
    workspace_id,
    route,
    platform_runtime_digest,
    hqa_runtime_digest,
    hermes_runtime_digest,
    database_schema_fingerprint,
    evidence_digest,
    release_digest,
    status,
    opened_at,
    closed_at,
    close_reason
"""
_CUTOVER_COLUMNS = """
    cutover_id,
    stamp_id,
    workspace_id,
    route,
    release_digest,
    cutover_digest,
    status,
    opened_at,
    closed_at,
    close_reason
"""


class ReleaseAuthorityError(RuntimeError):
    """Base error carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ReleaseAuthorityUnavailable(ReleaseAuthorityError):
    def __init__(self, message: str) -> None:
        super().__init__("release_authority_unavailable", message)


class ReleaseAuthorityValidationError(ReleaseAuthorityError):
    def __init__(self, message: str) -> None:
        super().__init__("release_authority_validation", message)


class ReleaseAuthorityConflict(ReleaseAuthorityError):
    def __init__(self, message: str) -> None:
        super().__init__("release_authority_conflict", message)


class ReleaseAuthorityNotFound(ReleaseAuthorityError):
    def __init__(self, message: str) -> None:
        super().__init__("release_authority_not_found", message)


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ReleaseAuthorityValidationError(
            f"{field} must be a bounded identifier"
        )
    return value


def _validate_digest(value: str, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ReleaseAuthorityValidationError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _validate_note(value: str, field: str) -> str:
    if type(value) is not str:
        raise ReleaseAuthorityValidationError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ReleaseAuthorityValidationError(
            f"{field} must be a nonempty note no longer than 500 characters"
        )
    return normalized


def _validate_route(value: str) -> str:
    if value != RELEASE_ROUTE:
        raise ReleaseAuthorityValidationError("route must be exactly /hermes")
    return value


def _validate_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReleaseAuthorityValidationError("now must be timezone-aware")
    return value.astimezone(UTC)


def _canonical_timestamp(value: datetime) -> str:
    return _validate_now(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical_digest(payload: Mapping[str, object]) -> str:
    raw = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def canonical_release_action_digest(
    operation: str,
    payload: Mapping[str, object],
) -> str:
    """Digest an exact operator action without its transport idempotency key."""

    if operation not in _OPERATIONS:
        raise ReleaseAuthorityValidationError("unsupported release operation")
    return _canonical_digest({"operation": operation, "payload": dict(payload)})


def canonical_release_stamp_digest(
    *,
    stamp_id: str,
    workspace_id: str,
    route: str,
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
    hermes_runtime_digest: str,
    database_schema_fingerprint: str,
    evidence_digest: str,
    opened_at: datetime,
) -> str:
    return _canonical_digest(
        {
            "database_schema_fingerprint": database_schema_fingerprint,
            "evidence_digest": evidence_digest,
            "hermes_runtime_digest": hermes_runtime_digest,
            "hqa_runtime_digest": hqa_runtime_digest,
            "opened_at": _canonical_timestamp(opened_at),
            "platform_runtime_digest": platform_runtime_digest,
            "route": route,
            "stamp_id": stamp_id,
            "workspace_id": workspace_id,
        }
    )


def canonical_public_cutover_digest(
    *,
    cutover_id: str,
    stamp_id: str,
    workspace_id: str,
    route: str,
    release_digest: str,
    opened_at: datetime,
) -> str:
    return _canonical_digest(
        {
            "cutover_id": cutover_id,
            "opened_at": _canonical_timestamp(opened_at),
            "release_digest": release_digest,
            "route": route,
            "stamp_id": stamp_id,
            "workspace_id": workspace_id,
        }
    )


@dataclass(frozen=True)
class CreateReleaseStampRequest:
    workspace_id: str
    route: str
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str
    evidence_digest: str
    note: str
    client_action_id: str
    action_digest: str


@dataclass(frozen=True)
class CloseReleaseStampRequest:
    workspace_id: str
    stamp_id: str
    expected_release_digest: str
    reason: str
    client_action_id: str
    action_digest: str


@dataclass(frozen=True)
class CreatePublicCutoverRequest:
    workspace_id: str
    stamp_id: str
    expected_release_digest: str
    route: str
    note: str
    client_action_id: str
    action_digest: str


@dataclass(frozen=True)
class ClosePublicCutoverRequest:
    workspace_id: str
    cutover_id: str
    expected_cutover_digest: str
    reason: str
    client_action_id: str
    action_digest: str


@dataclass(frozen=True)
class ReleaseStampRecord:
    stamp_id: str
    workspace_id: str
    route: str
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str
    database_schema_fingerprint: str
    evidence_digest: str
    release_digest: str
    status: ReleaseStatus
    opened_at: datetime
    closed_at: datetime | None
    close_reason: str | None


@dataclass(frozen=True)
class PublicCutoverRecord:
    cutover_id: str
    stamp_id: str
    workspace_id: str
    route: str
    release_digest: str
    cutover_digest: str
    status: CutoverStatus
    opened_at: datetime
    closed_at: datetime | None
    close_reason: str | None


@dataclass(frozen=True)
class ReleaseAuthorityReceipt:
    operation: str
    workspace_id: str
    client_action_id: str
    action_digest: str
    resource_id: str
    resource_digest: str
    status: str
    event_cursor: int
    occurred_at: datetime
    idempotent_replay: bool = False

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "action_digest": self.action_digest,
            "client_action_id": self.client_action_id,
            "event_cursor": self.event_cursor,
            "idempotent_replay": False,
            "occurred_at": _canonical_timestamp(self.occurred_at),
            "operation": self.operation,
            "resource_digest": self.resource_digest,
            "resource_id": self.resource_id,
            "status": self.status,
            "workspace_id": self.workspace_id,
        }


@dataclass(frozen=True)
class ReleaseAuthorityEvent:
    cursor: int
    event_id: str
    workspace_id: str
    stamp_id: str | None
    cutover_id: str | None
    event_type: str
    event_data: dict[str, object]
    occurred_at: datetime


def _stamp_from_row(row: tuple[object, ...]) -> ReleaseStampRecord:
    return ReleaseStampRecord(
        stamp_id=str(row[0]),
        workspace_id=str(row[1]),
        route=str(row[2]),
        platform_runtime_digest=str(row[3]),
        hqa_runtime_digest=str(row[4]),
        hermes_runtime_digest=str(row[5]),
        database_schema_fingerprint=str(row[6]),
        evidence_digest=str(row[7]),
        release_digest=str(row[8]),
        status=str(row[9]),  # type: ignore[arg-type]
        opened_at=row[10],  # type: ignore[arg-type]
        closed_at=row[11],  # type: ignore[arg-type]
        close_reason=str(row[12]) if row[12] is not None else None,
    )


def _cutover_from_row(row: tuple[object, ...]) -> PublicCutoverRecord:
    return PublicCutoverRecord(
        cutover_id=str(row[0]),
        stamp_id=str(row[1]),
        workspace_id=str(row[2]),
        route=str(row[3]),
        release_digest=str(row[4]),
        cutover_digest=str(row[5]),
        status=str(row[6]),  # type: ignore[arg-type]
        opened_at=row[7],  # type: ignore[arg-type]
        closed_at=row[8],  # type: ignore[arg-type]
        close_reason=str(row[9]) if row[9] is not None else None,
    )


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return _validate_now(value)
    if not isinstance(value, str):
        raise ReleaseAuthorityUnavailable("stored receipt timestamp is invalid")
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return _validate_now(datetime.fromisoformat(raw))
    except ValueError as exc:
        raise ReleaseAuthorityUnavailable(
            "stored receipt timestamp is invalid"
        ) from exc


def _receipt_from_dict(
    payload: Mapping[str, object],
    *,
    replay: bool,
) -> ReleaseAuthorityReceipt:
    try:
        return ReleaseAuthorityReceipt(
            operation=str(payload["operation"]),
            workspace_id=str(payload["workspace_id"]),
            client_action_id=str(payload["client_action_id"]),
            action_digest=str(payload["action_digest"]),
            resource_id=str(payload["resource_id"]),
            resource_digest=str(payload["resource_digest"]),
            status=str(payload["status"]),
            event_cursor=int(payload["event_cursor"]),
            occurred_at=_parse_timestamp(payload["occurred_at"]),
            idempotent_replay=replay,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ReleaseAuthorityUnavailable("stored action receipt is invalid") from exc


def release_authority_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    tables = (
        "agent_v02_release_authority_meta",
        "agent_v02_release_stamps",
        "agent_v02_public_cutovers",
        "agent_v02_release_events",
        "agent_v02_release_actions",
    )
    row = conn.execute(
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
    if row is None or row[0] is not True:
        return False
    version = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_release_authority_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if version != (RELEASE_AUTHORITY_SCHEMA_VERSION,):
        return False
    indexes = conn.execute(
        """
        SELECT count(*) = 2
        FROM pg_index index_row
        JOIN pg_class index_relation
          ON index_relation.oid = index_row.indexrelid
        JOIN pg_namespace namespace
          ON namespace.oid = index_relation.relnamespace
        WHERE namespace.nspname = %s
          AND index_relation.relname = ANY(%s)
          AND index_row.indisunique
          AND index_row.indpred IS NOT NULL
        """,
        (
            SCHEMA,
            [
                "uq_agent_v02_release_one_active_workspace",
                "uq_agent_v02_cutover_one_open_workspace",
            ],
        ),
    ).fetchone()
    if indexes is None or indexes[0] is not True:
        return False
    triggers = conn.execute(
        """
        SELECT count(*) = 12 AND bool_and(trigger.tgenabled = 'A')
        FROM pg_trigger trigger
        JOIN pg_class relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND trigger.tgname LIKE 'trg_agent_v02_%%'
          AND NOT trigger.tgisinternal
        """,
        (
            SCHEMA,
            [
                "agent_v02_release_stamps",
                "agent_v02_public_cutovers",
                "agent_v02_release_events",
                "agent_v02_release_actions",
            ],
        ),
    ).fetchone()
    return triggers is not None and triggers[0] is True


def release_authority_schema_ready(settings: Settings) -> bool:
    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            return release_authority_schema_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return False


def release_authority_runtime_security_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    """Require a constrained runtime login plus FORCE RLS on authority tables."""

    if not release_authority_schema_is_ready_on_connection(conn):
        return False
    tables = (
        "agent_v02_release_stamps",
        "agent_v02_public_cutovers",
        "agent_v02_release_events",
        "agent_v02_release_actions",
    )
    principal = conn.execute(
        """
        SELECT
            (
                SELECT count(*) = 3
                   AND bool_and(
                        NOT rolsuper
                        AND NOT rolbypassrls
                        AND NOT rolcanlogin
                        AND NOT rolcreatedb
                        AND NOT rolcreaterole
                        AND NOT rolinherit
                        AND NOT rolreplication
                   )
                FROM pg_roles
                WHERE rolname = ANY(%s)
            ),
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
        (
            ["quant_migrator", "quant_runtime", "quant_readonly"],
            SCHEMA,
            SCHEMA,
        ),
    ).fetchone()
    if principal is None or not all(bool(value) for value in principal):
        return False

    relations = conn.execute(
        """
        SELECT
            relation.relname,
            relation.relrowsecurity,
            relation.relforcerowsecurity,
            pg_get_userbyid(relation.relowner)
        FROM pg_class relation
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
        """,
        (SCHEMA, list(tables)),
    ).fetchall()
    if {
        (str(name), bool(rls), bool(force_rls), str(owner))
        for name, rls, force_rls, owner in relations
    } != {(name, True, True, "quant_migrator") for name in tables}:
        return False

    policies = conn.execute(
        """
        SELECT
            relation.relname,
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
          AND relation.relname = ANY(%s)
          AND policy.polname = ANY(%s)
        """,
        (
            SCHEMA,
            list(tables),
            ["v4r_root_scope", "v4r_migrator_all"],
        ),
    ).fetchall()
    if {
        (str(row[0]), str(row[1])) for row in policies
    } != {
        (table_name, policy_name)
        for table_name in tables
        for policy_name in ("v4r_root_scope", "v4r_migrator_all")
    }:
        return False
    root_expression = (
        "(owner_user_id = "
        "'00000000-0000-0000-0000-000000000001'::uuid)"
    )
    for _table, policy_name, command, using, with_check, roles in policies:
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

    privilege_contract = {
        "agent_v02_release_stamps": (
            "SELECT,INSERT,UPDATE",
            "DELETE,TRUNCATE",
        ),
        "agent_v02_public_cutovers": (
            "SELECT,INSERT,UPDATE",
            "DELETE,TRUNCATE",
        ),
        "agent_v02_release_events": (
            "SELECT,INSERT",
            "UPDATE,DELETE,TRUNCATE",
        ),
        "agent_v02_release_actions": (
            "SELECT,INSERT",
            "UPDATE,DELETE,TRUNCATE",
        ),
    }
    for table_name, (required, forbidden) in privilege_contract.items():
        privileges = conn.execute(
            """
            SELECT
                has_table_privilege(session_user, %s, %s),
                NOT has_table_privilege(session_user, %s, %s)
            """,
            (
                f"{SCHEMA}.{table_name}",
                required,
                f"{SCHEMA}.{table_name}",
                forbidden,
            ),
        ).fetchone()
        if privileges != (True, True):
            return False
    meta_privileges = conn.execute(
        """
        SELECT
            has_table_privilege(session_user, %s, 'SELECT'),
            NOT has_table_privilege(
                session_user,
                %s,
                'INSERT,UPDATE,DELETE,TRUNCATE'
            ),
            has_sequence_privilege(
                session_user,
                %s,
                'USAGE,SELECT'
            )
        """,
        (
            f"{SCHEMA}.agent_v02_release_authority_meta",
            f"{SCHEMA}.agent_v02_release_authority_meta",
            f"{SCHEMA}.agent_v02_release_events_event_cursor_seq",
        ),
    ).fetchone()
    return meta_privileges == (True, True, True)


def release_authority_runtime_security_ready(settings: Settings) -> bool:
    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            return release_authority_runtime_security_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return False


class ReleaseAuthority:
    """Durable, multi-process-consistent release/cutover repository."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        schema_fingerprint_reader: Callable[[Database | None], str] = schema_fingerprint,
    ) -> None:
        self._settings = settings
        self._database_override = database
        self._schema_fingerprint_reader = schema_fingerprint_reader

    def _database(self) -> Database:
        database = self._database_override or get_database(self._settings)
        if database is None:
            raise ReleaseAuthorityUnavailable(
                "release authority requires PostgreSQL"
            )
        return database

    @staticmethod
    def _lock_workspace(
        conn: psycopg.Connection,
        workspace_id: str,
    ) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"quant_system:agent_v02_release:{workspace_id}",),
        )

    @staticmethod
    def _expected_action(
        operation: str,
        payload: Mapping[str, object],
        action_digest: str,
    ) -> str:
        supplied = _validate_digest(action_digest, "action_digest")
        expected = canonical_release_action_digest(operation, payload)
        if supplied != expected:
            raise ReleaseAuthorityValidationError(
                "action_digest does not match the canonical request"
            )
        return supplied

    @staticmethod
    def _action_replay(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        client_action_id: str,
        operation: str,
        action_digest: str,
    ) -> ReleaseAuthorityReceipt | None:
        row = conn.execute(
            f"""
            SELECT operation, action_digest, receipt
            FROM {SCHEMA}.agent_v02_release_actions
            WHERE workspace_id = %s AND client_action_id = %s
            """,
            (workspace_id, client_action_id),
        ).fetchone()
        if row is None:
            return None
        if str(row[0]) != operation or str(row[1]) != action_digest:
            raise ReleaseAuthorityConflict(
                "client action id already froze a different action receipt"
            )
        if not isinstance(row[2], Mapping):
            raise ReleaseAuthorityUnavailable("stored action receipt is invalid")
        return _receipt_from_dict(row[2], replay=True)

    @staticmethod
    def _store_action(
        conn: psycopg.Connection,
        receipt: ReleaseAuthorityReceipt,
    ) -> None:
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.agent_v02_release_actions (
                owner_user_id,
                workspace_id,
                client_action_id,
                operation,
                action_digest,
                receipt,
                created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                ROOT_USER_ID,
                receipt.workspace_id,
                receipt.client_action_id,
                receipt.operation,
                receipt.action_digest,
                json.dumps(receipt.to_storage_dict(), separators=(",", ":")),
                receipt.occurred_at,
            ),
        )

    @staticmethod
    def _append_event(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        stamp_id: str | None,
        cutover_id: str | None,
        event_type: str,
        event_data: Mapping[str, object],
        occurred_at: datetime,
    ) -> int:
        row = conn.execute(
            f"""
            INSERT INTO {SCHEMA}.agent_v02_release_events (
                event_id,
                owner_user_id,
                workspace_id,
                stamp_id,
                cutover_id,
                event_type,
                event_data,
                occurred_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING event_cursor
            """,
            (
                f"evt_{uuid4().hex}",
                ROOT_USER_ID,
                workspace_id,
                stamp_id,
                cutover_id,
                event_type,
                json.dumps(dict(event_data), separators=(",", ":"), sort_keys=True),
                occurred_at,
            ),
        ).fetchone()
        if row is None:
            raise ReleaseAuthorityUnavailable("release event insert returned no cursor")
        return int(row[0])

    def create_release_stamp(
        self,
        request: CreateReleaseStampRequest,
        *,
        now: datetime | None = None,
        stamp_id: str | None = None,
    ) -> ReleaseAuthorityReceipt:
        workspace_id = _validate_id(request.workspace_id, "workspace_id")
        route = _validate_route(request.route)
        platform_digest = _validate_digest(
            request.platform_runtime_digest, "platform_runtime_digest"
        )
        hqa_digest = _validate_digest(request.hqa_runtime_digest, "hqa_runtime_digest")
        hermes_digest = _validate_digest(
            request.hermes_runtime_digest, "hermes_runtime_digest"
        )
        evidence_digest = _validate_digest(request.evidence_digest, "evidence_digest")
        note = _validate_note(request.note, "note")
        action_id = _validate_id(request.client_action_id, "client_action_id")
        payload = {
            "workspace_id": workspace_id,
            "route": route,
            "platform_runtime_digest": platform_digest,
            "hqa_runtime_digest": hqa_digest,
            "hermes_runtime_digest": hermes_digest,
            "evidence_digest": evidence_digest,
            "note": note,
        }
        action_digest = self._expected_action(
            "release.open", payload, request.action_digest
        )
        resource_id = _validate_id(stamp_id or f"release_{uuid4().hex}", "stamp_id")
        clock = _validate_now(now or datetime.now(UTC))
        database = self._database()
        fingerprint = self._schema_fingerprint_reader(database)
        _validate_digest(fingerprint, "database_schema_fingerprint")
        release_digest = canonical_release_stamp_digest(
            stamp_id=resource_id,
            workspace_id=workspace_id,
            route=route,
            platform_runtime_digest=platform_digest,
            hqa_runtime_digest=hqa_digest,
            hermes_runtime_digest=hermes_digest,
            database_schema_fingerprint=fingerprint,
            evidence_digest=evidence_digest,
            opened_at=clock,
        )
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_workspace(conn, workspace_id)
                replay = self._action_replay(
                    conn,
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    operation="release.open",
                    action_digest=action_digest,
                )
                if replay is not None:
                    return replay
                active = conn.execute(
                    f"""
                    SELECT stamp_id
                    FROM {SCHEMA}.agent_v02_release_stamps
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                    (workspace_id,),
                ).fetchone()
                if active is not None:
                    raise ReleaseAuthorityConflict(
                        "workspace already has an active release stamp"
                    )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_release_stamps (
                        stamp_id,
                        owner_user_id,
                        workspace_id,
                        route,
                        platform_runtime_digest,
                        hqa_runtime_digest,
                        hermes_runtime_digest,
                        database_schema_fingerprint,
                        evidence_digest,
                        release_digest,
                        status,
                        opened_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s
                    )
                    """,
                    (
                        resource_id,
                        ROOT_USER_ID,
                        workspace_id,
                        route,
                        platform_digest,
                        hqa_digest,
                        hermes_digest,
                        fingerprint,
                        evidence_digest,
                        release_digest,
                        clock,
                    ),
                )
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace_id,
                    stamp_id=resource_id,
                    cutover_id=None,
                    event_type="release.opened",
                    event_data={
                        "evidence_digest": evidence_digest,
                        "note": note,
                        "release_digest": release_digest,
                        "route": route,
                    },
                    occurred_at=clock,
                )
                receipt = ReleaseAuthorityReceipt(
                    operation="release.open",
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    action_digest=action_digest,
                    resource_id=resource_id,
                    resource_digest=release_digest,
                    status="active",
                    event_cursor=cursor,
                    occurred_at=clock,
                )
                self._store_action(conn, receipt)
                return receipt
        except ReleaseAuthorityError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise ReleaseAuthorityConflict(
                "release identity or active workspace constraint conflicted"
            ) from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "release authority database operation failed"
            ) from exc

    def create_public_cutover(
        self,
        request: CreatePublicCutoverRequest,
        *,
        now: datetime | None = None,
        cutover_id: str | None = None,
    ) -> ReleaseAuthorityReceipt:
        workspace_id = _validate_id(request.workspace_id, "workspace_id")
        stamp_id = _validate_id(request.stamp_id, "stamp_id")
        expected_release = _validate_digest(
            request.expected_release_digest, "expected_release_digest"
        )
        route = _validate_route(request.route)
        note = _validate_note(request.note, "note")
        action_id = _validate_id(request.client_action_id, "client_action_id")
        payload = {
            "workspace_id": workspace_id,
            "stamp_id": stamp_id,
            "expected_release_digest": expected_release,
            "route": route,
            "note": note,
        }
        action_digest = self._expected_action(
            "public_cutover.open", payload, request.action_digest
        )
        resource_id = _validate_id(
            cutover_id or f"cutover_{uuid4().hex}", "cutover_id"
        )
        clock = _validate_now(now or datetime.now(UTC))
        database = self._database()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_workspace(conn, workspace_id)
                replay = self._action_replay(
                    conn,
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    operation="public_cutover.open",
                    action_digest=action_digest,
                )
                if replay is not None:
                    return replay
                row = conn.execute(
                    f"""
                    SELECT {_STAMP_COLUMNS}
                    FROM {SCHEMA}.agent_v02_release_stamps
                    WHERE workspace_id = %s
                      AND stamp_id = %s
                      AND status = 'active'
                    """,
                    (workspace_id, stamp_id),
                ).fetchone()
                if row is None:
                    raise ReleaseAuthorityConflict(
                        "public cutover requires the active release stamp"
                    )
                stamp = _stamp_from_row(row)
                if (
                    stamp.release_digest != expected_release
                    or stamp.route != route
                ):
                    raise ReleaseAuthorityConflict(
                        "public cutover release binding mismatch"
                    )
                open_row = conn.execute(
                    f"""
                    SELECT cutover_id
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s AND status = 'open'
                    """,
                    (workspace_id,),
                ).fetchone()
                if open_row is not None:
                    raise ReleaseAuthorityConflict(
                        "workspace already has an open public cutover"
                    )
                cutover_digest = canonical_public_cutover_digest(
                    cutover_id=resource_id,
                    stamp_id=stamp_id,
                    workspace_id=workspace_id,
                    route=route,
                    release_digest=expected_release,
                    opened_at=clock,
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_public_cutovers (
                        cutover_id,
                        stamp_id,
                        owner_user_id,
                        workspace_id,
                        route,
                        release_digest,
                        cutover_digest,
                        status,
                        opened_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s)
                    """,
                    (
                        resource_id,
                        stamp_id,
                        ROOT_USER_ID,
                        workspace_id,
                        route,
                        expected_release,
                        cutover_digest,
                        clock,
                    ),
                )
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace_id,
                    stamp_id=stamp_id,
                    cutover_id=resource_id,
                    event_type="public_cutover.opened",
                    event_data={
                        "cutover_digest": cutover_digest,
                        "note": note,
                        "release_digest": expected_release,
                        "route": route,
                    },
                    occurred_at=clock,
                )
                receipt = ReleaseAuthorityReceipt(
                    operation="public_cutover.open",
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    action_digest=action_digest,
                    resource_id=resource_id,
                    resource_digest=cutover_digest,
                    status="open",
                    event_cursor=cursor,
                    occurred_at=clock,
                )
                self._store_action(conn, receipt)
                return receipt
        except ReleaseAuthorityError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise ReleaseAuthorityConflict(
                "public cutover identity or open workspace constraint conflicted"
            ) from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "public cutover database operation failed"
            ) from exc

    def close_public_cutover(
        self,
        request: ClosePublicCutoverRequest,
        *,
        now: datetime | None = None,
    ) -> ReleaseAuthorityReceipt:
        workspace_id = _validate_id(request.workspace_id, "workspace_id")
        cutover_id = _validate_id(request.cutover_id, "cutover_id")
        expected_digest = _validate_digest(
            request.expected_cutover_digest, "expected_cutover_digest"
        )
        reason = _validate_note(request.reason, "reason")
        action_id = _validate_id(request.client_action_id, "client_action_id")
        payload = {
            "workspace_id": workspace_id,
            "cutover_id": cutover_id,
            "expected_cutover_digest": expected_digest,
            "reason": reason,
        }
        action_digest = self._expected_action(
            "public_cutover.close", payload, request.action_digest
        )
        clock = _validate_now(now or datetime.now(UTC))
        database = self._database()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_workspace(conn, workspace_id)
                replay = self._action_replay(
                    conn,
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    operation="public_cutover.close",
                    action_digest=action_digest,
                )
                if replay is not None:
                    return replay
                row = conn.execute(
                    f"""
                    SELECT {_CUTOVER_COLUMNS}
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s AND cutover_id = %s
                    """,
                    (workspace_id, cutover_id),
                ).fetchone()
                if row is None:
                    raise ReleaseAuthorityNotFound("public cutover was not found")
                cutover = _cutover_from_row(row)
                if cutover.cutover_digest != expected_digest:
                    raise ReleaseAuthorityConflict(
                        "public cutover digest binding mismatch"
                    )
                if cutover.status == "closed":
                    receipt = ReleaseAuthorityReceipt(
                        operation="public_cutover.close",
                        workspace_id=workspace_id,
                        client_action_id=action_id,
                        action_digest=action_digest,
                        resource_id=cutover_id,
                        resource_digest=expected_digest,
                        status="closed",
                        event_cursor=self._current_event_cursor_on_connection(
                            conn, workspace_id
                        ),
                        occurred_at=clock,
                    )
                    self._store_action(conn, receipt)
                    return receipt
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_public_cutovers
                    SET status = 'closed', closed_at = %s, close_reason = %s
                    WHERE workspace_id = %s
                      AND cutover_id = %s
                      AND status = 'open'
                      AND cutover_digest = %s
                    """,
                    (
                        clock,
                        reason,
                        workspace_id,
                        cutover_id,
                        expected_digest,
                    ),
                )
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace_id,
                    stamp_id=cutover.stamp_id,
                    cutover_id=cutover_id,
                    event_type="public_cutover.closed",
                    event_data={
                        "cutover_digest": expected_digest,
                        "reason": reason,
                    },
                    occurred_at=clock,
                )
                receipt = ReleaseAuthorityReceipt(
                    operation="public_cutover.close",
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    action_digest=action_digest,
                    resource_id=cutover_id,
                    resource_digest=expected_digest,
                    status="closed",
                    event_cursor=cursor,
                    occurred_at=clock,
                )
                self._store_action(conn, receipt)
                return receipt
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "public cutover rollback database operation failed"
            ) from exc

    def close_release_stamp(
        self,
        request: CloseReleaseStampRequest,
        *,
        now: datetime | None = None,
    ) -> ReleaseAuthorityReceipt:
        workspace_id = _validate_id(request.workspace_id, "workspace_id")
        stamp_id = _validate_id(request.stamp_id, "stamp_id")
        expected_digest = _validate_digest(
            request.expected_release_digest, "expected_release_digest"
        )
        reason = _validate_note(request.reason, "reason")
        action_id = _validate_id(request.client_action_id, "client_action_id")
        payload = {
            "workspace_id": workspace_id,
            "stamp_id": stamp_id,
            "expected_release_digest": expected_digest,
            "reason": reason,
        }
        action_digest = self._expected_action(
            "release.close", payload, request.action_digest
        )
        clock = _validate_now(now or datetime.now(UTC))
        database = self._database()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_workspace(conn, workspace_id)
                replay = self._action_replay(
                    conn,
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    operation="release.close",
                    action_digest=action_digest,
                )
                if replay is not None:
                    return replay
                row = conn.execute(
                    f"""
                    SELECT {_STAMP_COLUMNS}
                    FROM {SCHEMA}.agent_v02_release_stamps
                    WHERE workspace_id = %s AND stamp_id = %s
                    """,
                    (workspace_id, stamp_id),
                ).fetchone()
                if row is None:
                    raise ReleaseAuthorityNotFound("release stamp was not found")
                stamp = _stamp_from_row(row)
                if stamp.release_digest != expected_digest:
                    raise ReleaseAuthorityConflict(
                        "release stamp digest binding mismatch"
                    )
                open_cutover = conn.execute(
                    f"""
                    SELECT cutover_id
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s
                      AND stamp_id = %s
                      AND status = 'open'
                    """,
                    (workspace_id, stamp_id),
                ).fetchone()
                if open_cutover is not None:
                    raise ReleaseAuthorityConflict(
                        "close the public cutover before closing its release stamp"
                    )
                if stamp.status == "closed":
                    receipt = ReleaseAuthorityReceipt(
                        operation="release.close",
                        workspace_id=workspace_id,
                        client_action_id=action_id,
                        action_digest=action_digest,
                        resource_id=stamp_id,
                        resource_digest=expected_digest,
                        status="closed",
                        event_cursor=self._current_event_cursor_on_connection(
                            conn, workspace_id
                        ),
                        occurred_at=clock,
                    )
                    self._store_action(conn, receipt)
                    return receipt
                conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_release_stamps
                    SET status = 'closed', closed_at = %s, close_reason = %s
                    WHERE workspace_id = %s
                      AND stamp_id = %s
                      AND status = 'active'
                      AND release_digest = %s
                    """,
                    (
                        clock,
                        reason,
                        workspace_id,
                        stamp_id,
                        expected_digest,
                    ),
                )
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace_id,
                    stamp_id=stamp_id,
                    cutover_id=None,
                    event_type="release.closed",
                    event_data={
                        "reason": reason,
                        "release_digest": expected_digest,
                    },
                    occurred_at=clock,
                )
                receipt = ReleaseAuthorityReceipt(
                    operation="release.close",
                    workspace_id=workspace_id,
                    client_action_id=action_id,
                    action_digest=action_digest,
                    resource_id=stamp_id,
                    resource_digest=expected_digest,
                    status="closed",
                    event_cursor=cursor,
                    occurred_at=clock,
                )
                self._store_action(conn, receipt)
                return receipt
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "release rollback database operation failed"
            ) from exc

    def active_release_stamp(
        self,
        workspace_id: str,
    ) -> ReleaseStampRecord | None:
        workspace = _validate_id(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_STAMP_COLUMNS}
                    FROM {SCHEMA}.agent_v02_release_stamps
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                    (workspace,),
                ).fetchone()
            return _stamp_from_row(row) if row is not None else None
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "release stamp observation failed"
            ) from exc

    def open_public_cutover(
        self,
        workspace_id: str,
    ) -> PublicCutoverRecord | None:
        workspace = _validate_id(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_CUTOVER_COLUMNS}
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s AND status = 'open'
                    """,
                    (workspace,),
                ).fetchone()
            return _cutover_from_row(row) if row is not None else None
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "public cutover observation failed"
            ) from exc

    @staticmethod
    def _current_event_cursor_on_connection(
        conn: psycopg.Connection,
        workspace_id: str,
    ) -> int:
        row = conn.execute(
            f"""
            SELECT COALESCE(max(event_cursor), 0)
            FROM {SCHEMA}.agent_v02_release_events
            WHERE workspace_id = %s
            """,
            (workspace_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    def current_event_cursor(self, workspace_id: str) -> int:
        workspace = _validate_id(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                return self._current_event_cursor_on_connection(conn, workspace)
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "release event cursor observation failed"
            ) from exc

    def events_after(
        self,
        workspace_id: str,
        *,
        after_cursor: int,
        limit: int = 100,
    ) -> tuple[ReleaseAuthorityEvent, ...]:
        workspace = _validate_id(workspace_id, "workspace_id")
        if (
            isinstance(after_cursor, bool)
            or not isinstance(after_cursor, int)
            or after_cursor < 0
        ):
            raise ReleaseAuthorityValidationError(
                "after_cursor must be a nonnegative integer"
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ReleaseAuthorityValidationError("limit must be between 1 and 500")
        try:
            with self._database().connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT
                        event_cursor,
                        event_id,
                        workspace_id,
                        stamp_id,
                        cutover_id,
                        event_type,
                        event_data,
                        occurred_at
                    FROM {SCHEMA}.agent_v02_release_events
                    WHERE workspace_id = %s AND event_cursor > %s
                    ORDER BY event_cursor
                    LIMIT %s
                    """,
                    (workspace, after_cursor, limit),
                ).fetchall()
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "release event observation failed"
            ) from exc
        return tuple(
            ReleaseAuthorityEvent(
                cursor=int(row[0]),
                event_id=str(row[1]),
                workspace_id=str(row[2]),
                stamp_id=str(row[3]) if row[3] is not None else None,
                cutover_id=str(row[4]) if row[4] is not None else None,
                event_type=str(row[5]),
                event_data=dict(row[6]) if isinstance(row[6], Mapping) else {},
                occurred_at=row[7],  # type: ignore[arg-type]
            )
            for row in rows
        )


__all__ = [
    "ClosePublicCutoverRequest",
    "CloseReleaseStampRequest",
    "CreatePublicCutoverRequest",
    "CreateReleaseStampRequest",
    "PublicCutoverRecord",
    "RELEASE_AUTHORITY_SCHEMA_VERSION",
    "ReleaseAuthority",
    "ReleaseAuthorityConflict",
    "ReleaseAuthorityError",
    "ReleaseAuthorityEvent",
    "ReleaseAuthorityNotFound",
    "ReleaseAuthorityReceipt",
    "ReleaseAuthorityUnavailable",
    "ReleaseAuthorityValidationError",
    "ReleaseStampRecord",
    "canonical_public_cutover_digest",
    "canonical_release_action_digest",
    "canonical_release_stamp_digest",
    "release_authority_runtime_security_is_ready_on_connection",
    "release_authority_runtime_security_ready",
    "release_authority_schema_is_ready_on_connection",
    "release_authority_schema_ready",
]
