"""PostgreSQL authority for durable, provider-free Hermes transport intent.

Creating a command records only an opaque payload reference and canonical
digest.  It never performs a network request and never means that Hermes
received or executed the intent.  Browser mutation routes remain absent until
the platform has authenticated same-origin and CSRF boundaries.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
LEDGER_SCHEMA_VERSION = 1
COMMAND_WAKEUP_CHANNEL = "quant_system_hermes_commands"
CommandState = Literal[
    "queued",
    "leased",
    "delivered",
    "outcome_unknown",
    "succeeded",
    "failed",
    "cancelled",
]
RunLinkRelation = Literal["input", "output", "context"]

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PAYLOAD_REF_RE = re.compile(r"^platform-payload://[A-Za-z0-9][A-Za-z0-9._:/-]{0,980}$")
_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HERMES_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_RESOURCE_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,499}$")
_SOURCE_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class HermesCommandLedgerUnavailable(RuntimeError):
    """Raised when the command authority cannot safely accept intent."""


class HermesCommandConflict(RuntimeError):
    """Raised when an idempotency key is reused for a different intent."""


class HermesCommandLeaseConflict(RuntimeError):
    """Raised when a stale or expired worker lease attempts a mutation."""


class HermesCommandNotFound(LookupError):
    """Raised when a command ID is not owned by the active platform user."""


class HermesCommandStateConflict(RuntimeError):
    """Raised when a requested transition is invalid from the current state."""


class HermesCommandVersionConflict(RuntimeError):
    """Raised when expected-version CAS observes a newer projection."""


class HermesCommandValidationError(ValueError):
    """Raised before persistence when bounded command metadata is invalid."""


@dataclass(frozen=True)
class HermesCommand:
    command_id: UUID
    owner_user_id: UUID
    platform_session_id: str
    client_request_id: str
    kind: str
    intent_schema_version: int
    canonical_request_digest: str
    payload_ref: str
    provider_policy_digest: str | None
    state: CommandState
    version: int
    attempt_count: int
    next_attempt_at: datetime | None
    lease_owner: str | None
    lease_token: UUID | None
    lease_until: datetime | None
    dispatch_started_at: datetime | None
    hermes_session_id: str | None
    hermes_run_id: str | None
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CreateHermesCommandResult:
    command: HermesCommand
    created: bool


@dataclass(frozen=True)
class ExpiredLeaseReconciliation:
    requeued: tuple[HermesCommand, ...]
    outcome_unknown: tuple[HermesCommand, ...]


@dataclass(frozen=True)
class HermesRunLink:
    link_id: UUID
    command_id: UUID
    platform_resource_type: str
    platform_resource_id: str
    relation: RunLinkRelation
    hermes_session_id: str
    hermes_run_id: str
    link_digest: str
    source_event_id: str | None
    observed_at: datetime
    created_at: datetime


@dataclass(frozen=True)
class RecordHermesRunLinkResult:
    link: HermesRunLink
    created: bool


@dataclass(frozen=True)
class HermesCommandEvent:
    event_id: int
    command_id: UUID
    command_version: int
    event_type: str
    actor: str
    from_state: CommandState | None
    to_state: CommandState
    canonical_request_digest: str
    attempt_count: int
    next_attempt_at: datetime | None
    lease_owner: str | None
    lease_token: UUID | None
    lease_until: datetime | None
    dispatch_started_at: datetime | None
    hermes_session_id: str | None
    hermes_run_id: str | None
    error_code: str | None
    event_data: dict[str, object]
    occurred_at: datetime


@dataclass(frozen=True)
class HermesOutboxEntry:
    outbox_id: int
    command_id: UUID
    command_version: int
    topic: str
    available_at: datetime
    consumed_by: str | None
    consumed_at: datetime | None
    created_at: datetime


class HermesCommandLedger:
    """Transactional repository for command, event, outbox, and run-link facts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_command(
        self,
        *,
        platform_session_id: str,
        client_request_id: str,
        kind: str,
        canonical_request_digest: str,
        payload_ref: str,
        provider_policy_digest: str | None = None,
    ) -> CreateHermesCommandResult:
        """Persist command + version-1 event + outbox atomically, without I/O."""
        _validate_create_fields(
            platform_session_id=platform_session_id,
            client_request_id=client_request_id,
            kind=kind,
            canonical_request_digest=canonical_request_digest,
            payload_ref=payload_ref,
            provider_policy_digest=provider_policy_digest,
        )
        database = self._require_ready_database()
        command_id = uuid4()
        try:
            with database.connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.hermes_commands (
                        command_id,
                        owner_user_id,
                        platform_session_id,
                        client_request_id,
                        kind,
                        intent_schema_version,
                        canonical_request_digest,
                        payload_ref,
                        provider_policy_digest,
                        state,
                        version
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', 1)
                    ON CONFLICT (
                        owner_user_id,
                        platform_session_id,
                        client_request_id
                    ) DO NOTHING
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        command_id,
                        ROOT_USER_ID,
                        platform_session_id,
                        client_request_id,
                        kind,
                        LEDGER_SCHEMA_VERSION,
                        canonical_request_digest,
                        payload_ref,
                        provider_policy_digest,
                    ),
                ).fetchone()
                if row is not None:
                    conn.execute(
                        f"""
                        INSERT INTO {SCHEMA}.hermes_command_events (
                            command_id,
                            command_version,
                            event_type,
                            actor,
                            from_state,
                            to_state,
                            canonical_request_digest,
                            attempt_count
                        )
                        VALUES (%s, 1, 'command_created', 'system', NULL, 'queued', %s, 0)
                        """,
                        (command_id, canonical_request_digest),
                    )
                    conn.execute(
                        f"""
                        INSERT INTO {SCHEMA}.hermes_outbox (
                            command_id,
                            command_version,
                            topic
                        )
                        VALUES (%s, 1, 'hermes.command.queued')
                        """,
                        (command_id,),
                    )
                    _notify_command_wakeup(conn, command_id)
                    return CreateHermesCommandResult(
                        command=_command_from_row(row),
                        created=True,
                    )

                existing = conn.execute(
                    f"""
                    SELECT {_COMMAND_COLUMNS}
                    FROM {SCHEMA}.hermes_commands
                    WHERE owner_user_id = %s
                      AND platform_session_id = %s
                      AND client_request_id = %s
                    """,
                    (ROOT_USER_ID, platform_session_id, client_request_id),
                ).fetchone()
                if existing is None:
                    raise HermesCommandLedgerUnavailable(
                        "idempotent command lookup returned no durable row"
                    )
                command = _command_from_row(existing)
                if (
                    command.canonical_request_digest != canonical_request_digest
                    or command.kind != kind
                    or command.payload_ref != payload_ref
                    or command.provider_policy_digest != provider_policy_digest
                ):
                    raise HermesCommandConflict(
                        "client_request_id already belongs to a different command intent"
                    )
                return CreateHermesCommandResult(command=command, created=False)
        except HermesCommandConflict:
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def get_command(self, command_id: UUID) -> HermesCommand:
        """Read the current durable projection for one owned command."""
        database = self._require_ready_database()
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_COMMAND_COLUMNS}
                    FROM {SCHEMA}.hermes_commands
                    WHERE command_id = %s AND owner_user_id = %s
                    """,
                    (command_id, ROOT_USER_ID),
                ).fetchone()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        if row is None:
            raise HermesCommandNotFound(str(command_id))
        return _command_from_row(row)

    def list_command_events(
        self,
        command_id: UUID,
        *,
        after_event_id: int = 0,
        limit: int = 100,
    ) -> tuple[HermesCommandEvent, ...]:
        """Read append-only command snapshots by the global event cursor."""
        if isinstance(after_event_id, bool) or after_event_id < 0:
            raise HermesCommandValidationError("after_event_id must be non-negative")
        _validate_limit(limit)
        database = self._require_ready_database()
        try:
            with database.connect() as conn:
                _require_owned_command_row(conn, command_id)
                rows = conn.execute(
                    f"""
                    SELECT {_COMMAND_EVENT_COLUMNS}
                    FROM {SCHEMA}.hermes_command_events
                    WHERE command_id = %s
                      AND event_id > %s
                    ORDER BY event_id
                    LIMIT %s
                    """,
                    (command_id, after_event_id, limit),
                ).fetchall()
        except HermesCommandNotFound:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        return tuple(_command_event_from_row(row) for row in rows)

    def list_command_outbox(
        self,
        command_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[HermesOutboxEntry, ...]:
        """Read queued and consumed wake-up facts for one owned command."""
        _validate_limit(limit)
        database = self._require_ready_database()
        try:
            with database.connect() as conn:
                _require_owned_command_row(conn, command_id)
                rows = conn.execute(
                    f"""
                    SELECT {_OUTBOX_COLUMNS}
                    FROM {SCHEMA}.hermes_outbox
                    WHERE command_id = %s
                    ORDER BY outbox_id
                    LIMIT %s
                    """,
                    (command_id, limit),
                ).fetchall()
        except HermesCommandNotFound:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        return tuple(_outbox_from_row(row) for row in rows)

    def cancel_queued_command(
        self,
        *,
        command_id: UUID,
        expected_version: int,
    ) -> HermesCommand:
        """Cancel local queued intent using expected-version CAS."""
        _validate_expected_version(expected_version)
        database = self._require_ready_database()
        try:
            with database.connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET state = 'cancelled',
                        version = version + 1,
                        next_attempt_at = NULL,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_until = NULL,
                        updated_at = now()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND version = %s
                      AND state = 'queued'
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (command_id, ROOT_USER_ID, expected_version),
                ).fetchone()
                if row is None:
                    self._raise_transition_conflict(
                        conn,
                        command_id=command_id,
                        expected_version=expected_version,
                        allowed_states={"queued"},
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="command_cancelled",
                    actor="system",
                    from_state="queued",
                )
                _consume_pending_outbox(
                    conn,
                    command_id=command.command_id,
                    consumed_by="system:command_cancelled",
                    topic="hermes.command.queued",
                )
                return command
        except (
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def claim_next_command(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> HermesCommand | None:
        """Claim one due command with ``SKIP LOCKED`` and a fencing token."""
        if _WORKER_ID_RE.fullmatch(worker_id) is None:
            raise HermesCommandValidationError("invalid worker_id")
        if now.tzinfo is None or now.utcoffset() is None:
            raise HermesCommandValidationError("now must be timezone-aware")
        lease_seconds = lease_duration.total_seconds()
        if not 1 <= lease_seconds <= 300:
            raise HermesCommandValidationError(
                "lease_duration must be between 1 and 300 seconds"
            )
        database = self._require_ready_database()
        lease_token = uuid4()
        try:
            with database.connect() as conn, conn.transaction():
                candidate = conn.execute(
                    f"""
                    SELECT command_id, version
                    FROM {SCHEMA}.hermes_commands
                    WHERE owner_user_id = %s
                      AND state = 'queued'
                      AND (
                          next_attempt_at IS NULL
                          OR next_attempt_at <= clock_timestamp()
                      )
                    ORDER BY next_attempt_at NULLS FIRST, created_at, command_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                    """,
                    (ROOT_USER_ID,),
                ).fetchone()
                if candidate is None:
                    return None
                command_id = UUID(str(candidate[0]))
                previous_version = int(candidate[1])
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET state = 'leased',
                        version = version + 1,
                        next_attempt_at = NULL,
                        lease_owner = %s,
                        lease_token = %s,
                        lease_until = clock_timestamp()
                            + (%s * interval '1 second'),
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND version = %s
                      AND state = 'queued'
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        worker_id,
                        lease_token,
                        lease_seconds,
                        command_id,
                        ROOT_USER_ID,
                        previous_version,
                    ),
                ).fetchone()
                if row is None:
                    raise HermesCommandLedgerUnavailable(
                        "locked command changed before lease projection update"
                    )
                consumed = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_outbox
                    SET consumed_by = %s,
                        consumed_at = clock_timestamp()
                    WHERE command_id = %s
                      AND command_version = %s
                      AND topic = 'hermes.command.queued'
                      AND consumed_at IS NULL
                    RETURNING outbox_id
                    """,
                    (worker_id, command_id, previous_version),
                ).fetchone()
                if consumed is None:
                    raise HermesCommandLedgerUnavailable(
                        "queued command has no matching durable outbox wake-up"
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="command_leased",
                    actor="worker",
                    from_state="queued",
                )
                return command
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def heartbeat_lease(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        lease_duration: timedelta,
    ) -> HermesCommand:
        """Extend an active lease while fencing stale workers."""
        _validate_expected_version(expected_version)
        _validate_lease_timing(now=now, lease_duration=lease_duration)
        database = self._require_ready_database()
        lease_seconds = lease_duration.total_seconds()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_active_lease(
                    conn,
                    command_id=command_id,
                    expected_version=expected_version,
                    lease_token=lease_token,
                    dispatch_requirement="any",
                )
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET version = version + 1,
                        lease_until = clock_timestamp()
                            + (%s * interval '1 second'),
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND state = 'leased'
                      AND version = %s
                      AND lease_token = %s
                      AND lease_until > clock_timestamp()
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        lease_seconds,
                        command_id,
                        ROOT_USER_ID,
                        expected_version,
                        lease_token,
                    ),
                ).fetchone()
                if row is None:
                    self._raise_lease_conflict(
                        conn,
                        command_id=command_id,
                        expected_version=expected_version,
                        lease_token=lease_token,
                        now=now,
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="lease_heartbeat",
                    actor="worker",
                    from_state="leased",
                )
                return command
        except (
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def mark_dispatch_started(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
    ) -> HermesCommand:
        """Persist the network-attempt boundary before any connector request."""
        _validate_expected_version(expected_version)
        _validate_aware_datetime(now, field="now")
        database = self._require_ready_database()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_active_lease(
                    conn,
                    command_id=command_id,
                    expected_version=expected_version,
                    lease_token=lease_token,
                    dispatch_requirement="not_started",
                )
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET version = version + 1,
                        attempt_count = attempt_count + 1,
                        dispatch_started_at = clock_timestamp(),
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND state = 'leased'
                      AND version = %s
                      AND lease_token = %s
                      AND lease_until > clock_timestamp()
                      AND dispatch_started_at IS NULL
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        command_id,
                        ROOT_USER_ID,
                        expected_version,
                        lease_token,
                    ),
                ).fetchone()
                if row is None:
                    self._raise_lease_conflict(
                        conn,
                        command_id=command_id,
                        expected_version=expected_version,
                        lease_token=lease_token,
                        now=now,
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="dispatch_started",
                    actor="worker",
                    from_state="leased",
                )
                return command
        except (
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def mark_delivered(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
    ) -> HermesCommand:
        """Bind authoritative Hermes IDs after a dispatched request is accepted."""
        _validate_expected_version(expected_version)
        _validate_aware_datetime(now, field="now")
        _validate_hermes_ids(
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
        )
        database = self._require_ready_database()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_active_lease(
                    conn,
                    command_id=command_id,
                    expected_version=expected_version,
                    lease_token=lease_token,
                    dispatch_requirement="started",
                )
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET state = 'delivered',
                        version = version + 1,
                        next_attempt_at = NULL,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_until = NULL,
                        hermes_session_id = %s,
                        hermes_run_id = %s,
                        last_error_code = NULL,
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND state = 'leased'
                      AND version = %s
                      AND lease_token = %s
                      AND lease_until > clock_timestamp()
                      AND dispatch_started_at IS NOT NULL
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        hermes_session_id,
                        hermes_run_id,
                        command_id,
                        ROOT_USER_ID,
                        expected_version,
                        lease_token,
                    ),
                ).fetchone()
                if row is None:
                    self._raise_lease_conflict(
                        conn,
                        command_id=command_id,
                        expected_version=expected_version,
                        lease_token=lease_token,
                        now=now,
                        require_dispatch_started=True,
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="command_delivered",
                    actor="worker",
                    from_state="leased",
                )
                return command
        except (
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def mark_dispatch_timeout(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        error_code: str = "dispatch_timeout",
    ) -> HermesCommand:
        """Fence a timed-out dispatch as unknown and enqueue reconciliation only."""
        _validate_expected_version(expected_version)
        _validate_aware_datetime(now, field="now")
        _validate_error_code(error_code)
        database = self._require_ready_database()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_active_lease(
                    conn,
                    command_id=command_id,
                    expected_version=expected_version,
                    lease_token=lease_token,
                    dispatch_requirement="started",
                )
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET state = 'outcome_unknown',
                        version = version + 1,
                        next_attempt_at = NULL,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_until = NULL,
                        last_error_code = %s,
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND state = 'leased'
                      AND version = %s
                      AND lease_token = %s
                      AND lease_until > clock_timestamp()
                      AND dispatch_started_at IS NOT NULL
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        error_code,
                        command_id,
                        ROOT_USER_ID,
                        expected_version,
                        lease_token,
                    ),
                ).fetchone()
                if row is None:
                    self._raise_lease_conflict(
                        conn,
                        command_id=command_id,
                        expected_version=expected_version,
                        lease_token=lease_token,
                        now=now,
                        require_dispatch_started=True,
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="dispatch_timed_out",
                    actor="worker",
                    from_state="leased",
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.hermes_outbox (
                        command_id,
                        command_version,
                        topic,
                        available_at
                    )
                    VALUES (
                        %s,
                        %s,
                        'hermes.command.reconcile',
                        clock_timestamp()
                    )
                    """,
                    (command.command_id, command.version),
                )
                _notify_command_wakeup(conn, command.command_id)
                return command
        except (
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def mark_dispatch_rejected(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        evidence_digest: str,
        error_code: str,
    ) -> HermesCommand:
        """Record a definitive upstream rejection without inventing Run IDs."""
        _validate_expected_version(expected_version)
        _validate_aware_datetime(now, field="now")
        _validate_digest(evidence_digest, field="evidence_digest")
        _validate_error_code(error_code)
        database = self._require_ready_database()
        try:
            with database.connect() as conn, conn.transaction():
                self._lock_active_lease(
                    conn,
                    command_id=command_id,
                    expected_version=expected_version,
                    lease_token=lease_token,
                    dispatch_requirement="started",
                )
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET state = 'failed',
                        version = version + 1,
                        next_attempt_at = NULL,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_until = NULL,
                        last_error_code = %s,
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND state = 'leased'
                      AND version = %s
                      AND lease_token = %s
                      AND lease_until > clock_timestamp()
                      AND dispatch_started_at IS NOT NULL
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        error_code,
                        command_id,
                        ROOT_USER_ID,
                        expected_version,
                        lease_token,
                    ),
                ).fetchone()
                if row is None:
                    self._raise_lease_conflict(
                        conn,
                        command_id=command_id,
                        expected_version=expected_version,
                        lease_token=lease_token,
                        now=now,
                        require_dispatch_started=True,
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="dispatch_rejected",
                    actor="worker",
                    from_state="leased",
                    event_data={"evidence_digest": evidence_digest},
                )
                return command
        except (
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def mark_succeeded(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
    ) -> HermesCommand:
        """Record an authoritative successful terminal outcome for an exact Run."""
        return self._mark_run_terminal(
            command_id=command_id,
            expected_version=expected_version,
            now=now,
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            evidence_digest=evidence_digest,
            terminal_state="succeeded",
            error_code=None,
        )

    def mark_failed(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
        error_code: str,
    ) -> HermesCommand:
        """Record an authoritative failed terminal outcome for an exact Run."""
        return self._mark_run_terminal(
            command_id=command_id,
            expected_version=expected_version,
            now=now,
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            evidence_digest=evidence_digest,
            terminal_state="failed",
            error_code=error_code,
        )

    def reconcile_outcome_as_delivered(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
    ) -> HermesCommand:
        """Bind a recovered active Run without replaying the original dispatch."""
        _validate_expected_version(expected_version)
        _validate_aware_datetime(now, field="now")
        _validate_hermes_ids(
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
        )
        _validate_digest(evidence_digest, field="evidence_digest")
        database = self._require_ready_database()
        try:
            with database.connect() as conn, conn.transaction():
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET state = 'delivered',
                        version = version + 1,
                        hermes_session_id = %s,
                        hermes_run_id = %s,
                        last_error_code = NULL,
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND version = %s
                      AND state = 'outcome_unknown'
                      AND (hermes_session_id IS NULL OR hermes_session_id = %s)
                      AND (hermes_run_id IS NULL OR hermes_run_id = %s)
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        hermes_session_id,
                        hermes_run_id,
                        command_id,
                        ROOT_USER_ID,
                        expected_version,
                        hermes_session_id,
                        hermes_run_id,
                    ),
                ).fetchone()
                if row is None:
                    self._raise_transition_conflict(
                        conn,
                        command_id=command_id,
                        expected_version=expected_version,
                        allowed_states={"outcome_unknown"},
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type="outcome_reconciled_delivered",
                    actor="reconciler",
                    from_state="outcome_unknown",
                    event_data={"evidence_digest": evidence_digest},
                )
                _consume_pending_outbox(
                    conn,
                    command_id=command.command_id,
                    consumed_by="reconciler:resolved",
                    topic="hermes.command.reconcile",
                )
                return command
        except (
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def _mark_run_terminal(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
        terminal_state: Literal["succeeded", "failed"],
        error_code: str | None,
    ) -> HermesCommand:
        _validate_expected_version(expected_version)
        _validate_aware_datetime(now, field="now")
        _validate_hermes_ids(
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
        )
        _validate_digest(evidence_digest, field="evidence_digest")
        if error_code is not None:
            _validate_error_code(error_code)
        database = self._require_ready_database()
        try:
            with database.connect() as conn, conn.transaction():
                current_row = conn.execute(
                    f"""
                    SELECT {_COMMAND_COLUMNS}
                    FROM {SCHEMA}.hermes_commands
                    WHERE command_id = %s
                      AND owner_user_id = %s
                    FOR UPDATE
                    """,
                    (command_id, ROOT_USER_ID),
                ).fetchone()
                if current_row is None:
                    raise HermesCommandNotFound(str(command_id))
                current = _command_from_row(current_row)
                if current.version != expected_version:
                    raise HermesCommandVersionConflict(
                        f"expected command version {expected_version}, "
                        f"found {current.version}"
                    )
                if current.state not in {"delivered", "outcome_unknown"}:
                    raise HermesCommandStateConflict(
                        f"command state {current.state} cannot become {terminal_state}"
                    )
                if (
                    current.hermes_session_id is not None
                    and current.hermes_session_id != hermes_session_id
                ) or (
                    current.hermes_run_id is not None
                    and current.hermes_run_id != hermes_run_id
                ):
                    raise HermesCommandConflict(
                        "terminal evidence names a different Hermes Session/Run"
                    )
                row = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.hermes_commands
                    SET state = %s,
                        version = version + 1,
                        next_attempt_at = NULL,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_until = NULL,
                        hermes_session_id = %s,
                        hermes_run_id = %s,
                        last_error_code = %s,
                        updated_at = clock_timestamp()
                    WHERE command_id = %s
                      AND owner_user_id = %s
                      AND version = %s
                    RETURNING {_COMMAND_COLUMNS}
                    """,
                    (
                        terminal_state,
                        hermes_session_id,
                        hermes_run_id,
                        error_code,
                        command_id,
                        ROOT_USER_ID,
                        expected_version,
                    ),
                ).fetchone()
                if row is None:
                    raise HermesCommandLedgerUnavailable(
                        "locked command changed during terminal transition"
                    )
                command = _command_from_row(row)
                _append_snapshot_event(
                    conn,
                    command=command,
                    event_type=f"command_{terminal_state}",
                    actor="reconciler" if current.state == "outcome_unknown" else "worker",
                    from_state=current.state,
                    event_data={"evidence_digest": evidence_digest},
                )
                if current.state == "outcome_unknown":
                    _consume_pending_outbox(
                        conn,
                        command_id=command.command_id,
                        consumed_by="reconciler:resolved",
                        topic="hermes.command.reconcile",
                    )
                return command
        except (
            HermesCommandConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def reconcile_expired_leases(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> ExpiredLeaseReconciliation:
        """Recover expired leases without ever guessing whether Hermes ran."""
        _validate_aware_datetime(now, field="now")
        if isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise HermesCommandValidationError("limit must be between 1 and 1000")
        database = self._require_ready_database()
        requeued: list[HermesCommand] = []
        outcome_unknown: list[HermesCommand] = []
        try:
            with database.connect() as conn, conn.transaction():
                for _index in range(limit):
                    candidate = conn.execute(
                        f"""
                        SELECT command_id, version, dispatch_started_at
                        FROM {SCHEMA}.hermes_commands
                        WHERE owner_user_id = %s
                          AND state = 'leased'
                          AND lease_until <= clock_timestamp()
                        ORDER BY lease_until, command_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                        """,
                        (ROOT_USER_ID,),
                    ).fetchone()
                    if candidate is None:
                        break
                    command_id = UUID(str(candidate[0]))
                    previous_version = int(candidate[1])
                    dispatch_started_at = candidate[2]
                    if dispatch_started_at is None:
                        row = conn.execute(
                            f"""
                            UPDATE {SCHEMA}.hermes_commands
                            SET state = 'queued',
                                version = version + 1,
                                next_attempt_at = clock_timestamp(),
                                lease_owner = NULL,
                                lease_token = NULL,
                                lease_until = NULL,
                                dispatch_started_at = NULL,
                                last_error_code = NULL,
                                updated_at = clock_timestamp()
                            WHERE command_id = %s
                              AND version = %s
                              AND state = 'leased'
                            RETURNING {_COMMAND_COLUMNS}
                            """,
                            (command_id, previous_version),
                        ).fetchone()
                        event_type = "lease_expired_requeued"
                        topic = "hermes.command.queued"
                    else:
                        row = conn.execute(
                            f"""
                            UPDATE {SCHEMA}.hermes_commands
                            SET state = 'outcome_unknown',
                                version = version + 1,
                                next_attempt_at = NULL,
                                lease_owner = NULL,
                                lease_token = NULL,
                                lease_until = NULL,
                                last_error_code = 'lease_expired_after_dispatch',
                                updated_at = clock_timestamp()
                            WHERE command_id = %s
                              AND version = %s
                              AND state = 'leased'
                            RETURNING {_COMMAND_COLUMNS}
                            """,
                            (command_id, previous_version),
                        ).fetchone()
                        event_type = "lease_expired_outcome_unknown"
                        topic = "hermes.command.reconcile"
                    if row is None:
                        raise HermesCommandLedgerUnavailable(
                            "locked command changed during expired-lease reconciliation"
                        )
                    command = _command_from_row(row)
                    _append_snapshot_event(
                        conn,
                        command=command,
                        event_type=event_type,
                        actor="reconciler",
                        from_state="leased",
                    )
                    conn.execute(
                        f"""
                        INSERT INTO {SCHEMA}.hermes_outbox (
                            command_id,
                            command_version,
                            topic,
                            available_at
                        )
                        VALUES (%s, %s, %s, clock_timestamp())
                        """,
                        (command.command_id, command.version, topic),
                    )
                    _notify_command_wakeup(conn, command.command_id)
                    if command.state == "queued":
                        requeued.append(command)
                    else:
                        outcome_unknown.append(command)
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        return ExpiredLeaseReconciliation(
            requeued=tuple(requeued),
            outcome_unknown=tuple(outcome_unknown),
        )

    def record_run_link(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        platform_resource_type: str,
        platform_resource_id: str,
        relation: RunLinkRelation,
        hermes_session_id: str,
        hermes_run_id: str,
        link_digest: str,
        source_event_id: str | None,
        observed_at: datetime,
    ) -> RecordHermesRunLinkResult:
        """Persist one immutable, exact platform-resource-to-Hermes-Run fact."""
        _validate_expected_version(expected_version)
        _validate_run_link_fields(
            platform_resource_type=platform_resource_type,
            platform_resource_id=platform_resource_id,
            relation=relation,
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            source_event_id=source_event_id,
            observed_at=observed_at,
        )
        expected_digest = hermes_run_link_digest(
            command_id=command_id,
            platform_resource_type=platform_resource_type,
            platform_resource_id=platform_resource_id,
            relation=relation,
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            source_event_id=source_event_id,
        )
        if link_digest != expected_digest:
            raise HermesCommandValidationError(
                "link_digest does not match the canonical exact-link facts"
            )
        database = self._require_ready_database()
        link_id = uuid4()
        try:
            with database.connect() as conn, conn.transaction():
                command_row = conn.execute(
                    f"""
                    SELECT {_COMMAND_COLUMNS}
                    FROM {SCHEMA}.hermes_commands
                    WHERE command_id = %s
                      AND owner_user_id = %s
                    FOR SHARE
                    """,
                    (command_id, ROOT_USER_ID),
                ).fetchone()
                if command_row is None:
                    raise HermesCommandNotFound(str(command_id))
                command = _command_from_row(command_row)
                if command.version != expected_version:
                    raise HermesCommandVersionConflict(
                        f"expected command version {expected_version}, "
                        f"found {command.version}"
                    )
                if command.state not in {"delivered", "succeeded", "failed"}:
                    raise HermesCommandStateConflict(
                        f"command state {command.state} has no authoritative Hermes Run"
                    )
                if (
                    command.hermes_session_id != hermes_session_id
                    or command.hermes_run_id != hermes_run_id
                ):
                    raise HermesCommandConflict(
                        "run link does not match the command's exact Hermes Session/Run"
                    )
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.hermes_run_links (
                        link_id,
                        command_id,
                        platform_resource_type,
                        platform_resource_id,
                        relation,
                        hermes_session_id,
                        hermes_run_id,
                        link_digest,
                        source_event_id,
                        observed_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        command_id,
                        platform_resource_type,
                        platform_resource_id,
                        relation
                    ) DO NOTHING
                    RETURNING {_RUN_LINK_COLUMNS}
                    """,
                    (
                        link_id,
                        command_id,
                        platform_resource_type,
                        platform_resource_id,
                        relation,
                        hermes_session_id,
                        hermes_run_id,
                        link_digest,
                        source_event_id,
                        observed_at,
                    ),
                ).fetchone()
                if row is not None:
                    return RecordHermesRunLinkResult(
                        link=_run_link_from_row(row),
                        created=True,
                    )
                existing_row = conn.execute(
                    f"""
                    SELECT {_RUN_LINK_COLUMNS}
                    FROM {SCHEMA}.hermes_run_links
                    WHERE command_id = %s
                      AND platform_resource_type = %s
                      AND platform_resource_id = %s
                      AND relation = %s
                    """,
                    (
                        command_id,
                        platform_resource_type,
                        platform_resource_id,
                        relation,
                    ),
                ).fetchone()
                if existing_row is None:
                    raise HermesCommandLedgerUnavailable(
                        "idempotent run-link lookup returned no durable row"
                    )
                existing = _run_link_from_row(existing_row)
                if (
                    existing.hermes_session_id != hermes_session_id
                    or existing.hermes_run_id != hermes_run_id
                    or existing.link_digest != link_digest
                    or existing.source_event_id != source_event_id
                ):
                    raise HermesCommandConflict(
                        "platform resource relation already belongs to a different exact link"
                    )
                return RecordHermesRunLinkResult(link=existing, created=False)
        except (
            HermesCommandConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            raise
        except DatabaseUnavailable as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        except psycopg.Error as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc

    def list_run_links_for_command(
        self,
        command_id: UUID,
        *,
        limit: int = 100,
    ) -> tuple[HermesRunLink, ...]:
        """Read immutable exact links owned by one platform command."""
        _validate_limit(limit)
        database = self._require_ready_database()
        try:
            with database.connect() as conn:
                if conn.execute(
                    f"""
                    SELECT 1
                    FROM {SCHEMA}.hermes_commands
                    WHERE command_id = %s AND owner_user_id = %s
                    """,
                    (command_id, ROOT_USER_ID),
                ).fetchone() is None:
                    raise HermesCommandNotFound(str(command_id))
                rows = conn.execute(
                    f"""
                    SELECT {_RUN_LINK_COLUMNS}
                    FROM {SCHEMA}.hermes_run_links
                    WHERE command_id = %s
                    ORDER BY created_at, link_id
                    LIMIT %s
                    """,
                    (command_id, limit),
                ).fetchall()
        except HermesCommandNotFound:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        return tuple(_run_link_from_row(row) for row in rows)

    def list_run_links_for_resource(
        self,
        *,
        platform_resource_type: str,
        platform_resource_id: str,
        limit: int = 100,
    ) -> tuple[HermesRunLink, ...]:
        """Read exact Hermes Run links for a stable platform resource ID."""
        _validate_platform_resource(
            platform_resource_type=platform_resource_type,
            platform_resource_id=platform_resource_id,
        )
        _validate_limit(limit)
        database = self._require_ready_database()
        try:
            with database.connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT {_RUN_LINK_COLUMNS}
                    FROM {SCHEMA}.hermes_run_links
                    WHERE platform_resource_type = %s
                      AND platform_resource_id = %s
                    ORDER BY created_at, link_id
                    LIMIT %s
                    """,
                    (platform_resource_type, platform_resource_id, limit),
                ).fetchall()
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise HermesCommandLedgerUnavailable(str(exc)) from exc
        return tuple(_run_link_from_row(row) for row in rows)

    @staticmethod
    def _raise_transition_conflict(
        conn: psycopg.Connection,
        *,
        command_id: UUID,
        expected_version: int,
        allowed_states: set[str],
    ) -> None:
        row = conn.execute(
            f"""
            SELECT version, state
            FROM {SCHEMA}.hermes_commands
            WHERE command_id = %s
              AND owner_user_id = %s
            """,
            (command_id, ROOT_USER_ID),
        ).fetchone()
        if row is None:
            raise HermesCommandNotFound(str(command_id))
        if int(row[0]) != expected_version:
            raise HermesCommandVersionConflict(
                f"expected command version {expected_version}, found {int(row[0])}"
            )
        if str(row[1]) not in allowed_states:
            raise HermesCommandStateConflict(
                f"command state {row[1]!s} does not allow this transition"
            )
        raise HermesCommandStateConflict("command transition lost a concurrent race")

    @staticmethod
    def _lock_active_lease(
        conn: psycopg.Connection,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        dispatch_requirement: Literal["any", "started", "not_started"],
    ) -> HermesCommand:
        """Fence a lease only after the command row lock is actually acquired."""
        row = conn.execute(
            f"""
            SELECT {_COMMAND_COLUMNS}
            FROM {SCHEMA}.hermes_commands
            WHERE command_id = %s
              AND owner_user_id = %s
            FOR UPDATE
            """,
            (command_id, ROOT_USER_ID),
        ).fetchone()
        if row is None:
            raise HermesCommandNotFound(str(command_id))
        command = _command_from_row(row)
        if command.version != expected_version:
            raise HermesCommandVersionConflict(
                f"expected command version {expected_version}, found {command.version}"
            )
        if command.state != "leased":
            raise HermesCommandStateConflict(
                f"command state {command.state} does not hold an active lease"
            )
        if command.lease_token != lease_token:
            raise HermesCommandLeaseConflict("lease token is stale")
        server_now_row = conn.execute("SELECT clock_timestamp()").fetchone()
        if server_now_row is None:
            raise HermesCommandLedgerUnavailable("database clock returned no value")
        if command.lease_until is None or command.lease_until <= server_now_row[0]:
            raise HermesCommandLeaseConflict("lease has expired")
        if dispatch_requirement == "started" and command.dispatch_started_at is None:
            raise HermesCommandStateConflict(
                "command cannot be delivered before dispatch is durably recorded"
            )
        if dispatch_requirement == "not_started" and command.dispatch_started_at is not None:
            raise HermesCommandStateConflict("command dispatch is already recorded")
        return command

    @staticmethod
    def _raise_lease_conflict(
        conn: psycopg.Connection,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        require_dispatch_started: bool = False,
    ) -> None:
        row = conn.execute(
            f"""
            SELECT version,
                   state,
                   lease_token,
                   lease_until,
                   dispatch_started_at,
                   clock_timestamp()
            FROM {SCHEMA}.hermes_commands
            WHERE command_id = %s
              AND owner_user_id = %s
            """,
            (command_id, ROOT_USER_ID),
        ).fetchone()
        if row is None:
            raise HermesCommandNotFound(str(command_id))
        if int(row[0]) != expected_version:
            raise HermesCommandVersionConflict(
                f"expected command version {expected_version}, found {int(row[0])}"
            )
        if str(row[1]) != "leased":
            raise HermesCommandStateConflict(
                f"command state {row[1]!s} does not hold an active lease"
            )
        if row[2] is None or UUID(str(row[2])) != lease_token:
            raise HermesCommandLeaseConflict("lease token is stale")
        if row[3] is None or row[3] <= row[5]:
            raise HermesCommandLeaseConflict("lease has expired")
        if require_dispatch_started and row[4] is None:
            raise HermesCommandStateConflict(
                "command cannot be delivered before dispatch is durably recorded"
            )
        raise HermesCommandLeaseConflict("lease update lost a concurrent race")

    def _require_ready_database(self) -> Database:
        database = get_database(self._settings)
        if database is None:
            raise HermesCommandLedgerUnavailable(
                "Hermes command ledger requires PostgreSQL; no filesystem fallback exists"
            )
        try:
            with database.connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT schema_version
                    FROM {SCHEMA}.hermes_ledger_meta
                    WHERE singleton IS TRUE
                    """
                ).fetchone()
                signature_ready = _ledger_schema_signature_is_ready(conn)
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise HermesCommandLedgerUnavailable(
                "Hermes command ledger schema is unavailable"
            ) from exc
        if (
            row is None
            or int(row[0]) != LEDGER_SCHEMA_VERSION
            or not signature_ready
        ):
            raise HermesCommandLedgerUnavailable(
                "Hermes command ledger schema version is not ready"
            )
        return database


_COMMAND_COLUMNS = """
    command_id,
    owner_user_id,
    platform_session_id,
    client_request_id,
    kind,
    intent_schema_version,
    canonical_request_digest,
    payload_ref,
    provider_policy_digest,
    state,
    version,
    attempt_count,
    next_attempt_at,
    lease_owner,
    lease_token,
    lease_until,
    dispatch_started_at,
    hermes_session_id,
    hermes_run_id,
    last_error_code,
    created_at,
    updated_at
"""

_RUN_LINK_COLUMNS = """
    link_id,
    command_id,
    platform_resource_type,
    platform_resource_id,
    relation,
    hermes_session_id,
    hermes_run_id,
    link_digest,
    source_event_id,
    observed_at,
    created_at
"""

_COMMAND_EVENT_COLUMNS = """
    event_id,
    command_id,
    command_version,
    event_type,
    actor,
    from_state,
    to_state,
    canonical_request_digest,
    attempt_count,
    next_attempt_at,
    lease_owner,
    lease_token,
    lease_until,
    dispatch_started_at,
    hermes_session_id,
    hermes_run_id,
    error_code,
    event_data,
    occurred_at
"""

_OUTBOX_COLUMNS = """
    outbox_id,
    command_id,
    command_version,
    topic,
    available_at,
    consumed_by,
    consumed_at,
    created_at
"""


_REQUIRED_LEDGER_COLUMNS: dict[str, frozenset[str]] = {
    "hermes_ledger_meta": frozenset({"singleton", "schema_version"}),
    "hermes_commands": frozenset(
        {
            "command_id",
            "owner_user_id",
            "platform_session_id",
            "client_request_id",
            "canonical_request_digest",
            "payload_ref",
            "state",
            "version",
            "lease_token",
            "lease_until",
            "dispatch_started_at",
            "hermes_session_id",
            "hermes_run_id",
        }
    ),
    "hermes_command_events": frozenset(
        {
            "event_id",
            "command_id",
            "command_version",
            "from_state",
            "to_state",
            "canonical_request_digest",
            "lease_token",
            "hermes_run_id",
            "event_data",
        }
    ),
    "hermes_outbox": frozenset(
        {
            "outbox_id",
            "command_id",
            "command_version",
            "topic",
            "available_at",
            "consumed_by",
            "consumed_at",
        }
    ),
    "hermes_run_links": frozenset(
        {
            "link_id",
            "command_id",
            "platform_resource_type",
            "platform_resource_id",
            "relation",
            "hermes_session_id",
            "hermes_run_id",
            "link_digest",
        }
    ),
}

_REQUIRED_LEDGER_CONSTRAINTS = frozenset(
    {
        ("hermes_commands", "hermes_commands_pkey"),
        ("hermes_commands", "hermes_commands_owner_user_id_fkey"),
        (
            "hermes_commands",
            "hermes_commands_owner_user_id_platform_session_id_client_re_key",
        ),
        ("hermes_commands", "ck_hermes_commands_state"),
        ("hermes_commands", "ck_hermes_commands_lease_triplet"),
        ("hermes_commands", "ck_hermes_commands_dispatch_state"),
        ("hermes_command_events", "hermes_command_events_command_id_fkey"),
        (
            "hermes_command_events",
            "hermes_command_events_command_id_command_version_key",
        ),
        ("hermes_command_events", "ck_hermes_command_events_states"),
        ("hermes_outbox", "hermes_outbox_command_id_fkey"),
        (
            "hermes_outbox",
            "hermes_outbox_command_id_command_version_topic_key",
        ),
        ("hermes_outbox", "ck_hermes_outbox_consumed_pair"),
        ("hermes_run_links", "hermes_run_links_command_id_fkey"),
        ("hermes_run_links", "ck_hermes_run_links_relation"),
    }
)

_REQUIRED_LEDGER_INDEXES = frozenset(
    {
        "uq_hermes_commands_upstream_run",
        "uq_hermes_run_links_command_resource",
    }
)

_REQUIRED_LEDGER_TRIGGERS = frozenset(
    {
        (
            "hermes_command_events",
            "trg_hermes_command_events_append_only",
            27,  # BEFORE UPDATE OR DELETE, FOR EACH ROW
            "reject_hermes_command_event_mutation",
        ),
        (
            "hermes_command_events",
            "trg_hermes_command_events_append_only_truncate",
            34,  # BEFORE TRUNCATE, FOR EACH STATEMENT
            "reject_hermes_command_event_mutation",
        ),
        (
            "hermes_run_links",
            "trg_hermes_run_links_append_only",
            27,  # BEFORE UPDATE OR DELETE, FOR EACH ROW
            "reject_hermes_run_link_mutation",
        ),
        (
            "hermes_run_links",
            "trg_hermes_run_links_append_only_truncate",
            34,  # BEFORE TRUNCATE, FOR EACH STATEMENT
            "reject_hermes_run_link_mutation",
        ),
    }
)


def _ledger_schema_signature_is_ready(conn: psycopg.Connection) -> bool:
    column_rows = conn.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = ANY(%s)
        """,
        (SCHEMA, list(_REQUIRED_LEDGER_COLUMNS)),
    ).fetchall()
    actual_columns: dict[str, set[str]] = {}
    for table_name, column_name in column_rows:
        actual_columns.setdefault(str(table_name), set()).add(str(column_name))
    if any(
        not required.issubset(actual_columns.get(table_name, set()))
        for table_name, required in _REQUIRED_LEDGER_COLUMNS.items()
    ):
        return False

    constraint_rows = conn.execute(
        """
        SELECT table_name, constraint_name
        FROM information_schema.table_constraints
        WHERE table_schema = %s
          AND table_name = ANY(%s)
        """,
        (SCHEMA, list(_REQUIRED_LEDGER_COLUMNS)),
    ).fetchall()
    if not _REQUIRED_LEDGER_CONSTRAINTS.issubset(
        {(str(table), str(name)) for table, name in constraint_rows}
    ):
        return False

    index_rows = conn.execute(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = %s
          AND indexname = ANY(%s)
        """,
        (SCHEMA, list(_REQUIRED_LEDGER_INDEXES)),
    ).fetchall()
    if {str(row[0]) for row in index_rows} != set(_REQUIRED_LEDGER_INDEXES):
        return False

    trigger_rows = conn.execute(
        """
        SELECT relation.relname,
               trigger.tgname,
               trigger.tgtype,
               procedure.proname
        FROM pg_trigger AS trigger
        JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
        JOIN pg_namespace AS procedure_namespace
          ON procedure_namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = %s
          AND procedure_namespace.nspname = %s
          AND trigger.tgenabled <> 'D'
          AND NOT trigger.tgisinternal
        """,
        (SCHEMA, SCHEMA),
    ).fetchall()
    return _REQUIRED_LEDGER_TRIGGERS.issubset(
        {
            (str(table), str(name), int(trigger_type), str(procedure_name))
            for table, name, trigger_type, procedure_name in trigger_rows
        }
    )


def _validate_create_fields(
    *,
    platform_session_id: str,
    client_request_id: str,
    kind: str,
    canonical_request_digest: str,
    payload_ref: str,
    provider_policy_digest: str | None,
) -> None:
    if _SESSION_ID_RE.fullmatch(platform_session_id) is None:
        raise HermesCommandValidationError("invalid platform_session_id")
    if _CLIENT_REQUEST_ID_RE.fullmatch(client_request_id) is None:
        raise HermesCommandValidationError("invalid client_request_id")
    if _KIND_RE.fullmatch(kind) is None:
        raise HermesCommandValidationError("invalid command kind")
    if _DIGEST_RE.fullmatch(canonical_request_digest) is None:
        raise HermesCommandValidationError(
            "canonical_request_digest must be lowercase SHA-256"
        )
    if provider_policy_digest is not None and _DIGEST_RE.fullmatch(
        provider_policy_digest
    ) is None:
        raise HermesCommandValidationError(
            "provider_policy_digest must be lowercase SHA-256"
        )
    if _PAYLOAD_REF_RE.fullmatch(payload_ref) is None:
        raise HermesCommandValidationError(
            "payload_ref must be a bounded platform-payload reference, not raw prompt text"
        )


def _validate_expected_version(expected_version: int) -> None:
    if isinstance(expected_version, bool) or expected_version < 1:
        raise HermesCommandValidationError("expected_version must be positive")


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise HermesCommandValidationError("limit must be between 1 and 1000")


def _validate_lease_timing(*, now: datetime, lease_duration: timedelta) -> None:
    _validate_aware_datetime(now, field="now")
    lease_seconds = lease_duration.total_seconds()
    if not 1 <= lease_seconds <= 300:
        raise HermesCommandValidationError(
            "lease_duration must be between 1 and 300 seconds"
        )


def _validate_aware_datetime(value: datetime, *, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HermesCommandValidationError(f"{field} must be timezone-aware")


def _validate_hermes_ids(*, hermes_session_id: str, hermes_run_id: str) -> None:
    if _HERMES_ID_RE.fullmatch(hermes_session_id) is None:
        raise HermesCommandValidationError("invalid hermes_session_id")
    if _HERMES_ID_RE.fullmatch(hermes_run_id) is None:
        raise HermesCommandValidationError("invalid hermes_run_id")


def _validate_error_code(error_code: str) -> None:
    if _ERROR_CODE_RE.fullmatch(error_code) is None:
        raise HermesCommandValidationError("invalid error_code")


def _validate_digest(value: str, *, field: str) -> None:
    if _DIGEST_RE.fullmatch(value) is None:
        raise HermesCommandValidationError(f"{field} must be lowercase SHA-256")


def _validate_platform_resource(
    *,
    platform_resource_type: str,
    platform_resource_id: str,
) -> None:
    if _RESOURCE_TYPE_RE.fullmatch(platform_resource_type) is None:
        raise HermesCommandValidationError("invalid platform_resource_type")
    if _RESOURCE_ID_RE.fullmatch(platform_resource_id) is None:
        raise HermesCommandValidationError("invalid platform_resource_id")


def _validate_run_link_fields(
    *,
    platform_resource_type: str,
    platform_resource_id: str,
    relation: str,
    hermes_session_id: str,
    hermes_run_id: str,
    source_event_id: str | None,
    observed_at: datetime,
) -> None:
    _validate_run_link_identity(
        platform_resource_type=platform_resource_type,
        platform_resource_id=platform_resource_id,
        relation=relation,
        hermes_session_id=hermes_session_id,
        hermes_run_id=hermes_run_id,
        source_event_id=source_event_id,
    )
    _validate_aware_datetime(observed_at, field="observed_at")


def _validate_run_link_identity(
    *,
    platform_resource_type: str,
    platform_resource_id: str,
    relation: str,
    hermes_session_id: str,
    hermes_run_id: str,
    source_event_id: str | None,
) -> None:
    _validate_platform_resource(
        platform_resource_type=platform_resource_type,
        platform_resource_id=platform_resource_id,
    )
    if relation not in {"input", "output", "context"}:
        raise HermesCommandValidationError("invalid run-link relation")
    _validate_hermes_ids(
        hermes_session_id=hermes_session_id,
        hermes_run_id=hermes_run_id,
    )
    if source_event_id is not None and _SOURCE_EVENT_ID_RE.fullmatch(
        source_event_id
    ) is None:
        raise HermesCommandValidationError("invalid source_event_id")


def hermes_run_link_digest(
    *,
    command_id: UUID,
    platform_resource_type: str,
    platform_resource_id: str,
    relation: RunLinkRelation,
    hermes_session_id: str,
    hermes_run_id: str,
    source_event_id: str | None,
) -> str:
    """Return the canonical SHA-256 for an exact cross-system identity link."""
    _validate_run_link_identity(
        platform_resource_type=platform_resource_type,
        platform_resource_id=platform_resource_id,
        relation=relation,
        hermes_session_id=hermes_session_id,
        hermes_run_id=hermes_run_id,
        source_event_id=source_event_id,
    )
    canonical = json.dumps(
        {
            "command_id": str(command_id),
            "hermes_run_id": hermes_run_id,
            "hermes_session_id": hermes_session_id,
            "platform_resource_id": platform_resource_id,
            "platform_resource_type": platform_resource_type,
            "relation": relation,
            "schema": "hermes-run-link-v1",
            "source_event_id": source_event_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _command_from_row(row: tuple[object, ...]) -> HermesCommand:
    return HermesCommand(
        command_id=UUID(str(row[0])),
        owner_user_id=UUID(str(row[1])),
        platform_session_id=str(row[2]),
        client_request_id=str(row[3]),
        kind=str(row[4]),
        intent_schema_version=int(row[5]),
        canonical_request_digest=str(row[6]),
        payload_ref=str(row[7]),
        provider_policy_digest=str(row[8]) if row[8] is not None else None,
        state=cast(CommandState, str(row[9])),
        version=int(row[10]),
        attempt_count=int(row[11]),
        next_attempt_at=cast(datetime | None, row[12]),
        lease_owner=str(row[13]) if row[13] is not None else None,
        lease_token=UUID(str(row[14])) if row[14] is not None else None,
        lease_until=cast(datetime | None, row[15]),
        dispatch_started_at=cast(datetime | None, row[16]),
        hermes_session_id=str(row[17]) if row[17] is not None else None,
        hermes_run_id=str(row[18]) if row[18] is not None else None,
        last_error_code=str(row[19]) if row[19] is not None else None,
        created_at=cast(datetime, row[20]),
        updated_at=cast(datetime, row[21]),
    )


def _require_owned_command_row(
    conn: psycopg.Connection,
    command_id: UUID,
) -> None:
    if conn.execute(
        f"""
        SELECT 1
        FROM {SCHEMA}.hermes_commands
        WHERE command_id = %s AND owner_user_id = %s
        """,
        (command_id, ROOT_USER_ID),
    ).fetchone() is None:
        raise HermesCommandNotFound(str(command_id))


def _command_event_from_row(row: tuple[object, ...]) -> HermesCommandEvent:
    return HermesCommandEvent(
        event_id=int(row[0]),
        command_id=UUID(str(row[1])),
        command_version=int(row[2]),
        event_type=str(row[3]),
        actor=str(row[4]),
        from_state=cast(CommandState | None, str(row[5]) if row[5] is not None else None),
        to_state=cast(CommandState, str(row[6])),
        canonical_request_digest=str(row[7]),
        attempt_count=int(row[8]),
        next_attempt_at=cast(datetime | None, row[9]),
        lease_owner=str(row[10]) if row[10] is not None else None,
        lease_token=UUID(str(row[11])) if row[11] is not None else None,
        lease_until=cast(datetime | None, row[12]),
        dispatch_started_at=cast(datetime | None, row[13]),
        hermes_session_id=str(row[14]) if row[14] is not None else None,
        hermes_run_id=str(row[15]) if row[15] is not None else None,
        error_code=str(row[16]) if row[16] is not None else None,
        event_data=dict(cast(dict[str, object], row[17])),
        occurred_at=cast(datetime, row[18]),
    )


def _outbox_from_row(row: tuple[object, ...]) -> HermesOutboxEntry:
    return HermesOutboxEntry(
        outbox_id=int(row[0]),
        command_id=UUID(str(row[1])),
        command_version=int(row[2]),
        topic=str(row[3]),
        available_at=cast(datetime, row[4]),
        consumed_by=str(row[5]) if row[5] is not None else None,
        consumed_at=cast(datetime | None, row[6]),
        created_at=cast(datetime, row[7]),
    )


def _run_link_from_row(row: tuple[object, ...]) -> HermesRunLink:
    return HermesRunLink(
        link_id=UUID(str(row[0])),
        command_id=UUID(str(row[1])),
        platform_resource_type=str(row[2]),
        platform_resource_id=str(row[3]),
        relation=cast(RunLinkRelation, str(row[4])),
        hermes_session_id=str(row[5]),
        hermes_run_id=str(row[6]),
        link_digest=str(row[7]),
        source_event_id=str(row[8]) if row[8] is not None else None,
        observed_at=cast(datetime, row[9]),
        created_at=cast(datetime, row[10]),
    )


def _append_snapshot_event(
    conn: psycopg.Connection,
    *,
    command: HermesCommand,
    event_type: str,
    actor: Literal["bff", "worker", "reconciler", "system"],
    from_state: CommandState | None,
    event_data: dict[str, object] | None = None,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {SCHEMA}.hermes_command_events (
            command_id,
            command_version,
            event_type,
            actor,
            from_state,
            to_state,
            canonical_request_digest,
            attempt_count,
            next_attempt_at,
            lease_owner,
            lease_token,
            lease_until,
            dispatch_started_at,
            hermes_session_id,
            hermes_run_id,
            error_code,
            event_data
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            command.command_id,
            command.version,
            event_type,
            actor,
            from_state,
            command.state,
            command.canonical_request_digest,
            command.attempt_count,
            command.next_attempt_at,
            command.lease_owner,
            command.lease_token,
            command.lease_until,
            command.dispatch_started_at,
            command.hermes_session_id,
            command.hermes_run_id,
            command.last_error_code,
            Jsonb(event_data or {}),
        ),
    )


def _consume_pending_outbox(
    conn: psycopg.Connection,
    *,
    command_id: UUID,
    consumed_by: str,
    topic: str,
) -> None:
    conn.execute(
        f"""
        UPDATE {SCHEMA}.hermes_outbox
        SET consumed_by = %s,
            consumed_at = clock_timestamp()
        WHERE command_id = %s
          AND topic = %s
          AND consumed_at IS NULL
        """,
        (consumed_by, command_id, topic),
    )


def command_ledger_schema_version(settings: Settings) -> int | None:
    """Return the verified ledger schema version, or ``None`` when unavailable."""
    database = get_database(settings)
    if database is None:
        return None
    try:
        with database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT schema_version
                FROM {SCHEMA}.hermes_ledger_meta
                WHERE singleton IS TRUE
                """
            ).fetchone()
            signature_ready = _ledger_schema_signature_is_ready(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return None
    if row is None or not signature_ready:
        return None
    version = int(row[0])
    return version if version == LEDGER_SCHEMA_VERSION else None


def _notify_command_wakeup(conn: psycopg.Connection, command_id: UUID) -> None:
    conn.execute(
        "SELECT pg_notify(%s, %s)",
        (COMMAND_WAKEUP_CHANNEL, str(command_id)),
    )


__all__ = [
    "CreateHermesCommandResult",
    "COMMAND_WAKEUP_CHANNEL",
    "ExpiredLeaseReconciliation",
    "HermesCommand",
    "HermesCommandConflict",
    "HermesCommandLeaseConflict",
    "HermesCommandLedger",
    "HermesCommandLedgerUnavailable",
    "HermesCommandNotFound",
    "HermesCommandEvent",
    "HermesOutboxEntry",
    "HermesCommandStateConflict",
    "HermesCommandValidationError",
    "HermesCommandVersionConflict",
    "HermesRunLink",
    "RecordHermesRunLinkResult",
    "command_ledger_schema_version",
    "hermes_run_link_digest",
]
