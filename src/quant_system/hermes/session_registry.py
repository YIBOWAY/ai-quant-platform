"""PostgreSQL authority for Agent Workspace session registry (V4).

Records only session identity, kind, lineage and immutable provider-policy
digest. Never stores prompt bodies, Hermes credentials, or trading intent.
Mutation of observed_external_session is fail-closed at both the repository
and database layers. Public chat write remains OFF until the full V4/V8 gate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

SESSION_REGISTRY_SCHEMA_VERSION = 1
SessionKind = Literal["observed_external_session", "web_managed_session"]
SessionWriter = Literal["external_channel", "web_control_plane"]
SourceChannel = Literal["discord", "historical", "web_managed"]

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_HERMES_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class HermesSessionRegistryUnavailable(RuntimeError):
    """Raised when the session registry cannot safely accept identity."""


class HermesSessionRegistryConflict(RuntimeError):
    """Raised when an identity key is reused for different session facts."""


class HermesSessionRegistryValidationError(ValueError):
    """Raised when a session registration request violates the contract."""


class HermesSessionNotWritable(RuntimeError):
    """Raised when a write is attempted against a non-web-managed session."""


@dataclass(frozen=True)
class WorkspaceSessionRecord:
    platform_session_id: str
    hermes_session_id: str
    workspace_id: str
    owner_user_id: UUID
    kind: SessionKind
    source_channel: str | None
    parent_platform_session_id: str | None
    fork_point: str | None
    provider_policy_digest: str | None
    writer: SessionWriter
    created_at: datetime
    updated_at: datetime

    @property
    def web_writable(self) -> bool:
        return self.kind == "web_managed_session" and self.writer == "web_control_plane"


@dataclass(frozen=True)
class RegisterWorkspaceSession:
    platform_session_id: str
    hermes_session_id: str
    workspace_id: str
    kind: SessionKind
    source_channel: str | None = None
    parent_platform_session_id: str | None = None
    fork_point: str | None = None
    provider_policy_digest: str | None = None
    owner_user_id: UUID = ROOT_USER_ID


def _validate_register(request: RegisterWorkspaceSession) -> SessionWriter:
    if request.owner_user_id != ROOT_USER_ID:
        raise HermesSessionRegistryValidationError("owner_user_id must be the root user")
    if _SESSION_ID_RE.fullmatch(request.platform_session_id) is None:
        raise HermesSessionRegistryValidationError("invalid platform_session_id")
    if _HERMES_ID_RE.fullmatch(request.hermes_session_id) is None:
        raise HermesSessionRegistryValidationError("invalid hermes_session_id")
    if _WORKSPACE_ID_RE.fullmatch(request.workspace_id) is None:
        raise HermesSessionRegistryValidationError("invalid workspace_id")
    if request.kind == "observed_external_session":
        if request.source_channel not in {"discord", "historical"}:
            raise HermesSessionRegistryValidationError(
                "observed_external_session requires source_channel discord|historical"
            )
        if request.parent_platform_session_id is not None:
            raise HermesSessionRegistryValidationError(
                "observed_external_session cannot have a parent"
            )
        if request.fork_point is not None:
            raise HermesSessionRegistryValidationError(
                "observed_external_session cannot have a fork_point"
            )
        if request.provider_policy_digest is not None:
            raise HermesSessionRegistryValidationError(
                "observed_external_session cannot carry provider_policy_digest"
            )
        return "external_channel"

    if request.kind != "web_managed_session":
        raise HermesSessionRegistryValidationError("invalid session kind")
    if (
        request.provider_policy_digest is None
        or _DIGEST_RE.fullmatch(request.provider_policy_digest) is None
    ):
        raise HermesSessionRegistryValidationError(
            "web_managed_session requires provider_policy_digest"
        )
    if request.parent_platform_session_id is None:
        if request.source_channel is not None or request.fork_point is not None:
            raise HermesSessionRegistryValidationError(
                "root web_managed_session cannot carry source_channel or fork_point"
            )
    else:
        if _SESSION_ID_RE.fullmatch(request.parent_platform_session_id) is None:
            raise HermesSessionRegistryValidationError("invalid parent_platform_session_id")
        if request.parent_platform_session_id == request.platform_session_id:
            raise HermesSessionRegistryValidationError("session cannot parent itself")
        if request.source_channel not in {"discord", "historical", "web_managed"}:
            raise HermesSessionRegistryValidationError(
                "forked web_managed_session requires source_channel"
            )
        if (
            request.fork_point is None
            or not request.fork_point
            or len(request.fork_point) > 2000
            or not request.fork_point.isprintable()
        ):
            raise HermesSessionRegistryValidationError(
                "forked web_managed_session requires fork_point"
            )
    return "web_control_plane"


def _require_database(settings: Settings) -> Database:
    database = get_database(settings)
    if database is None:
        raise HermesSessionRegistryUnavailable(
            "Hermes session registry requires PostgreSQL; no filesystem fallback exists"
        )
    return database


def _row_to_record(row: tuple[object, ...]) -> WorkspaceSessionRecord:
    return WorkspaceSessionRecord(
        platform_session_id=str(row[0]),
        hermes_session_id=str(row[1]),
        workspace_id=str(row[2]),
        owner_user_id=UUID(str(row[3])),
        kind=row[4],  # type: ignore[arg-type]
        source_channel=str(row[5]) if row[5] is not None else None,
        parent_platform_session_id=str(row[6]) if row[6] is not None else None,
        fork_point=str(row[7]) if row[7] is not None else None,
        provider_policy_digest=str(row[8]) if row[8] is not None else None,
        writer=row[9],  # type: ignore[arg-type]
        created_at=row[10],  # type: ignore[arg-type]
        updated_at=row[11],  # type: ignore[arg-type]
    )


_SELECT_COLUMNS = """
    platform_session_id,
    hermes_session_id,
    workspace_id,
    owner_user_id,
    kind,
    source_channel,
    parent_platform_session_id,
    fork_point,
    provider_policy_digest,
    writer,
    created_at,
    updated_at
"""


def session_registry_schema_is_ready_on_connection(conn: psycopg.Connection) -> bool:
    exists = conn.execute(
        "SELECT to_regclass(%s), to_regclass(%s)",
        (
            f"{SCHEMA}.hermes_session_registry_meta",
            f"{SCHEMA}.hermes_workspace_sessions",
        ),
    ).fetchone()
    if exists is None or exists[0] is None or exists[1] is None:
        return False

    version_row = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.hermes_session_registry_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if version_row is None or int(version_row[0]) != SESSION_REGISTRY_SCHEMA_VERSION:
        return False

    required = conn.execute(
        """
        SELECT
            EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_hermes_workspace_session_hermes'
                  AND conrelid = %s::regclass
            ),
            EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_hermes_workspace_session_immutability'
                  AND tgrelid = %s::regclass
                  AND NOT tgisinternal
                  AND tgenabled = 'A'
            )
        """,
        (
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
        ),
    ).fetchone()
    return required is not None and bool(required[0]) and bool(required[1])


def session_registry_schema_version(settings: Settings) -> int | None:
    try:
        database = get_database(settings)
        if database is None:
            return None
        with database.connect() as conn:
            if not session_registry_schema_is_ready_on_connection(conn):
                return None
            row = conn.execute(
                f"""
                SELECT schema_version
                FROM {SCHEMA}.hermes_session_registry_meta
                WHERE singleton IS TRUE
                """
            ).fetchone()
        if row is None:
            return None
        return int(row[0])
    except (DatabaseUnavailable, psycopg.Error, TypeError, ValueError):
        return None


def _facts_match(existing: WorkspaceSessionRecord, request: RegisterWorkspaceSession, writer: SessionWriter) -> bool:
    return (
        existing.platform_session_id == request.platform_session_id
        and existing.hermes_session_id == request.hermes_session_id
        and existing.workspace_id == request.workspace_id
        and existing.owner_user_id == request.owner_user_id
        and existing.kind == request.kind
        and existing.source_channel == request.source_channel
        and existing.parent_platform_session_id == request.parent_platform_session_id
        and existing.fork_point == request.fork_point
        and existing.provider_policy_digest == request.provider_policy_digest
        and existing.writer == writer
    )


def register_workspace_session(
    settings: Settings,
    request: RegisterWorkspaceSession,
) -> tuple[WorkspaceSessionRecord, bool]:
    """Idempotently register a workspace session. Returns (record, created)."""

    writer = _validate_register(request)
    database = _require_database(settings)
    try:
        with database.connect() as conn, conn.transaction():
            if not session_registry_schema_is_ready_on_connection(conn):
                raise HermesSessionRegistryUnavailable(
                    "Hermes session registry schema is not ready"
                )
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"hermes-workspace-session:{request.platform_session_id}",),
            )
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"hermes-session-identity:{request.hermes_session_id}",),
            )

            existing = conn.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM {SCHEMA}.hermes_workspace_sessions
                WHERE platform_session_id = %s
                   OR hermes_session_id = %s
                ORDER BY created_at ASC
                """,
                (request.platform_session_id, request.hermes_session_id),
            ).fetchall()
            if existing:
                records = [_row_to_record(row) for row in existing]
                primary = next(
                    (
                        record
                        for record in records
                        if record.platform_session_id == request.platform_session_id
                    ),
                    records[0],
                )
                if len(records) > 1 or not _facts_match(primary, request, writer):
                    raise HermesSessionRegistryConflict(
                        "session identity key reused with different facts"
                    )
                return primary, False

            if request.parent_platform_session_id is not None:
                parent = conn.execute(
                    f"""
                    SELECT kind
                    FROM {SCHEMA}.hermes_workspace_sessions
                    WHERE platform_session_id = %s
                      AND owner_user_id = %s
                    """,
                    (request.parent_platform_session_id, request.owner_user_id),
                ).fetchone()
                if parent is None:
                    raise HermesSessionRegistryValidationError(
                        "parent_platform_session_id does not exist"
                    )

            row = conn.execute(
                f"""
                INSERT INTO {SCHEMA}.hermes_workspace_sessions (
                    platform_session_id,
                    hermes_session_id,
                    workspace_id,
                    owner_user_id,
                    kind,
                    source_channel,
                    parent_platform_session_id,
                    fork_point,
                    provider_policy_digest,
                    writer
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING {_SELECT_COLUMNS}
                """,
                (
                    request.platform_session_id,
                    request.hermes_session_id,
                    request.workspace_id,
                    request.owner_user_id,
                    request.kind,
                    request.source_channel,
                    request.parent_platform_session_id,
                    request.fork_point,
                    request.provider_policy_digest,
                    writer,
                ),
            ).fetchone()
            if row is None:
                raise HermesSessionRegistryUnavailable(
                    "session registry insert returned no durable row"
                )
            return _row_to_record(row), True
    except (
        HermesSessionRegistryConflict,
        HermesSessionRegistryUnavailable,
        HermesSessionRegistryValidationError,
    ):
        raise
    except (DatabaseUnavailable, psycopg.Error) as exc:
        raise HermesSessionRegistryUnavailable(
            "Hermes session registry persistence failed"
        ) from exc


def get_workspace_session(
    settings: Settings,
    *,
    platform_session_id: str,
) -> WorkspaceSessionRecord:
    if _SESSION_ID_RE.fullmatch(platform_session_id) is None:
        raise HermesSessionRegistryValidationError("invalid platform_session_id")
    database = _require_database(settings)
    try:
        with database.connect() as conn, conn.transaction():
            if not session_registry_schema_is_ready_on_connection(conn):
                raise HermesSessionRegistryUnavailable(
                    "Hermes session registry schema is not ready"
                )
            row = conn.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM {SCHEMA}.hermes_workspace_sessions
                WHERE platform_session_id = %s
                  AND owner_user_id = %s
                """,
                (platform_session_id, ROOT_USER_ID),
            ).fetchone()
            if row is None:
                raise LookupError(platform_session_id)
            return _row_to_record(row)
    except (HermesSessionRegistryUnavailable, HermesSessionRegistryValidationError, LookupError):
        raise
    except (DatabaseUnavailable, psycopg.Error) as exc:
        raise HermesSessionRegistryUnavailable(
            "Hermes session registry lookup failed"
        ) from exc


def require_web_writable_session(
    settings: Settings,
    *,
    platform_session_id: str,
) -> WorkspaceSessionRecord:
    """Application-layer fail-closed gate for external/read-only sessions."""

    record = get_workspace_session(settings, platform_session_id=platform_session_id)
    if not record.web_writable:
        raise HermesSessionNotWritable(
            "observed_external_session rejects web mutation; fork to web_managed_session"
        )
    return record
