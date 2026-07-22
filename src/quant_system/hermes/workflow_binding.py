"""Exact, provider-free binding between platform commands and HQA workflow facts.

The platform owns the transport command. HQA owns Task/Attempt/plan and the
content-addressed payload. This module persists only immutable identifiers,
digests, and expiry metadata; it never reads a prompt or calls Hermes/provider.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import (
    COMMAND_WAKEUP_CHANNEL,
    LEDGER_SCHEMA_VERSION,
    ROOT_USER_ID,
    HermesCommandConflict,
    HermesCommandLedgerUnavailable,
    HermesCommandNotFound,
    HermesCommandValidationError,
    command_ledger_schema_is_ready_on_connection,
    command_ledger_schema_version,
)
from quant_system.storage.database import SCHEMA, DatabaseUnavailable, get_database

WORKFLOW_BINDING_SCHEMA_VERSION: Final = 1
PREPARED_RECEIPT_SCHEMA_VERSION: Final = "1.0"
RESEARCH_COMMAND_KIND: Final = "research_chat"
WORKFLOW_BINDING_INVENTORY_SCHEMA_VERSION: Final = "1.0"
WORKFLOW_BINDING_INVENTORY_FETCH_SIZE: Final = 100
PG_BIGINT_MAX: Final = 9_223_372_036_854_775_807
PG_INTEGER_MAX: Final = 2_147_483_647

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SAGA_ID_RE = re.compile(r"^hqs_[0-9a-f]{24}$")
_TASK_ID_RE = re.compile(r"^hqt_[0-9a-f]{24}$")
_ATTEMPT_ID_RE = re.compile(r"^hqa_[0-9a-f]{24}$")
_PREPARED_EVENT_ID_RE = re.compile(r"^hqe_[0-9a-f]{24}$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_PAYLOAD_REF_RE = re.compile(r"^hqa-payload:sha256:([0-9a-f]{64})$")


@dataclass(frozen=True)
class PreparedWorkflowCommand:
    """HQA-authored, digest-bound facts prepared before platform persistence."""

    schema_version: str
    workflow_saga_id: str
    owner_user_id: UUID
    platform_session_id: str
    client_request_id: str
    command_kind: str
    canonical_request_digest: str
    payload_ref: str
    payload_digest: str
    payload_expires_at: datetime
    provider_policy_digest: str
    task_id: str
    task_version: int
    attempt_id: str
    attempt_number: int
    prepared_event_id: str
    prepared_event_digest: str
    plan_schema_version: int
    plan_version: int
    plan_digest: str
    workflow_preparation_digest: str


@dataclass(frozen=True)
class HermesWorkflowBinding:
    command_id: UUID
    command_version: int
    preparation_schema_version: str
    workflow_saga_id: str
    owner_user_id: UUID
    platform_session_id: str
    client_request_id: str
    command_kind: str
    canonical_request_digest: str
    payload_ref: str
    payload_digest: str
    payload_expires_at: datetime
    provider_policy_digest: str
    task_id: str
    task_version: int
    attempt_id: str
    attempt_number: int
    prepared_event_id: str
    prepared_event_digest: str
    plan_schema_version: int
    plan_version: int
    plan_digest: str
    workflow_preparation_digest: str
    binding_schema_version: int
    binding_digest: str
    created_at: datetime


@dataclass(frozen=True)
class EnsureBoundCommandResult:
    command_id: UUID
    command_state: str
    command_version: int
    binding: HermesWorkflowBinding
    created: bool


def _canonical_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HermesCommandValidationError("payload_expires_at must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_preparation(prepared: PreparedWorkflowCommand) -> dict[str, object]:
    return {
        "attempt_id": prepared.attempt_id,
        "attempt_number": prepared.attempt_number,
        "canonical_request_digest": prepared.canonical_request_digest,
        "client_request_id": prepared.client_request_id,
        "command_kind": prepared.command_kind,
        "owner_user_id": str(prepared.owner_user_id),
        "payload_digest": prepared.payload_digest,
        "payload_expires_at": _canonical_timestamp(prepared.payload_expires_at),
        "payload_ref": prepared.payload_ref,
        "plan_digest": prepared.plan_digest,
        "plan_schema_version": prepared.plan_schema_version,
        "plan_version": prepared.plan_version,
        "platform_session_id": prepared.platform_session_id,
        "prepared_event_digest": prepared.prepared_event_digest,
        "prepared_event_id": prepared.prepared_event_id,
        "provider_policy_digest": prepared.provider_policy_digest,
        "schema_version": prepared.schema_version,
        "task_id": prepared.task_id,
        "task_version": prepared.task_version,
        "workflow_saga_id": prepared.workflow_saga_id,
    }


def _sha256(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def workflow_preparation_digest(prepared: PreparedWorkflowCommand) -> str:
    """Digest the exact HQA-prepared facts, excluding the digest itself."""

    return _sha256(_canonical_preparation(prepared))


def workflow_binding_digest(
    prepared: PreparedWorkflowCommand,
    *,
    command_id: UUID,
) -> str:
    """Bind the immutable HQA receipt to one exact platform command ID."""

    return _sha256(
        {
            **_canonical_preparation(prepared),
            "command_id": str(command_id),
            "workflow_preparation_digest": prepared.workflow_preparation_digest,
        }
    )


def workflow_binding_to_dict(binding: HermesWorkflowBinding) -> dict[str, object]:
    """Serialize one binding with stable UUID and six-microsecond UTC timestamps."""

    return {
        "command_id": str(binding.command_id),
        "command_version": binding.command_version,
        "preparation_schema_version": binding.preparation_schema_version,
        "workflow_saga_id": binding.workflow_saga_id,
        "owner_user_id": str(binding.owner_user_id),
        "platform_session_id": binding.platform_session_id,
        "client_request_id": binding.client_request_id,
        "command_kind": binding.command_kind,
        "canonical_request_digest": binding.canonical_request_digest,
        "payload_ref": binding.payload_ref,
        "payload_digest": binding.payload_digest,
        "payload_expires_at": _canonical_timestamp(binding.payload_expires_at),
        "provider_policy_digest": binding.provider_policy_digest,
        "task_id": binding.task_id,
        "task_version": binding.task_version,
        "attempt_id": binding.attempt_id,
        "attempt_number": binding.attempt_number,
        "prepared_event_id": binding.prepared_event_id,
        "prepared_event_digest": binding.prepared_event_digest,
        "plan_schema_version": binding.plan_schema_version,
        "plan_version": binding.plan_version,
        "plan_digest": binding.plan_digest,
        "workflow_preparation_digest": binding.workflow_preparation_digest,
        "binding_schema_version": binding.binding_schema_version,
        "binding_digest": binding.binding_digest,
        "created_at": _canonical_timestamp(binding.created_at),
    }


def _validate_digest(value: str, *, field: str) -> None:
    if _DIGEST_RE.fullmatch(value) is None:
        raise HermesCommandValidationError(f"{field} must be lowercase SHA-256")


def _validate_prepared(prepared: PreparedWorkflowCommand) -> None:
    for field in (
        "schema_version",
        "workflow_saga_id",
        "platform_session_id",
        "client_request_id",
        "command_kind",
        "canonical_request_digest",
        "payload_ref",
        "payload_digest",
        "provider_policy_digest",
        "task_id",
        "attempt_id",
        "prepared_event_id",
        "prepared_event_digest",
        "plan_digest",
        "workflow_preparation_digest",
    ):
        if type(getattr(prepared, field)) is not str:
            raise HermesCommandValidationError(f"{field} must be an exact string")
    if type(prepared.owner_user_id) is not UUID:
        raise HermesCommandValidationError("owner_user_id must be an exact UUID")
    if type(prepared.payload_expires_at) is not datetime:
        raise HermesCommandValidationError("payload_expires_at must be an exact datetime")
    if prepared.schema_version != PREPARED_RECEIPT_SCHEMA_VERSION:
        raise HermesCommandValidationError("schema_version must be 1.0")
    if _SAGA_ID_RE.fullmatch(prepared.workflow_saga_id) is None:
        raise HermesCommandValidationError("invalid workflow_saga_id")
    if prepared.owner_user_id != ROOT_USER_ID:
        raise HermesCommandValidationError("owner_user_id must be the local root authority")
    if _SESSION_ID_RE.fullmatch(prepared.platform_session_id) is None:
        raise HermesCommandValidationError("invalid platform_session_id")
    if _CLIENT_REQUEST_ID_RE.fullmatch(prepared.client_request_id) is None:
        raise HermesCommandValidationError("invalid client_request_id")
    if prepared.command_kind != RESEARCH_COMMAND_KIND:
        raise HermesCommandValidationError("command_kind must be research_chat")
    for field in (
        "canonical_request_digest",
        "payload_digest",
        "provider_policy_digest",
        "prepared_event_digest",
        "plan_digest",
        "workflow_preparation_digest",
    ):
        _validate_digest(str(getattr(prepared, field)), field=field)
    match = _PAYLOAD_REF_RE.fullmatch(prepared.payload_ref)
    if match is None or match.group(1) != prepared.payload_digest:
        raise HermesCommandValidationError(
            "payload_ref must exactly address payload_digest as hqa-payload:sha256:<digest>"
        )
    _canonical_timestamp(prepared.payload_expires_at)
    for field, pattern in (
        ("task_id", _TASK_ID_RE),
        ("attempt_id", _ATTEMPT_ID_RE),
        ("prepared_event_id", _PREPARED_EVENT_ID_RE),
    ):
        if pattern.fullmatch(str(getattr(prepared, field))) is None:
            raise HermesCommandValidationError(f"invalid {field}")
    for field, maximum in (
        ("task_version", PG_BIGINT_MAX),
        ("attempt_number", PG_INTEGER_MAX),
        ("plan_version", PG_BIGINT_MAX),
    ):
        value = getattr(prepared, field)
        if type(value) is not int or not 1 <= value <= maximum:
            raise HermesCommandValidationError(
                f"{field} must fit its positive PostgreSQL integer type"
            )
    if type(prepared.plan_schema_version) is not int or prepared.plan_schema_version != 1:
        raise HermesCommandValidationError("plan_schema_version must be 1")
    if prepared.workflow_preparation_digest != workflow_preparation_digest(prepared):
        raise HermesCommandValidationError(
            "workflow_preparation_digest does not match the exact prepared facts"
        )


_BINDING_SELECT = """
    binding.command_id,
    binding.command_version,
    binding.preparation_schema_version,
    binding.workflow_saga_id,
    binding.owner_user_id,
    binding.platform_session_id,
    binding.client_request_id,
    binding.command_kind,
    binding.canonical_request_digest,
    binding.payload_ref,
    binding.payload_digest,
    binding.payload_expires_at,
    binding.provider_policy_digest,
    binding.task_id,
    binding.task_version,
    binding.attempt_id,
    binding.attempt_number,
    binding.prepared_event_id,
    binding.prepared_event_digest,
    binding.plan_schema_version,
    binding.plan_version,
    binding.plan_digest,
    binding.workflow_preparation_digest,
    binding.binding_schema_version,
    binding.binding_digest,
    binding.created_at
"""


def _binding_from_row(row: tuple[object, ...]) -> HermesWorkflowBinding:
    return HermesWorkflowBinding(
        command_id=UUID(str(row[0])),
        command_version=int(row[1]),
        preparation_schema_version=str(row[2]),
        workflow_saga_id=str(row[3]),
        owner_user_id=UUID(str(row[4])),
        platform_session_id=str(row[5]),
        client_request_id=str(row[6]),
        command_kind=str(row[7]),
        canonical_request_digest=str(row[8]),
        payload_ref=str(row[9]),
        payload_digest=str(row[10]),
        payload_expires_at=cast(datetime, row[11]),
        provider_policy_digest=str(row[12]),
        task_id=str(row[13]),
        task_version=int(row[14]),
        attempt_id=str(row[15]),
        attempt_number=int(row[16]),
        prepared_event_id=str(row[17]),
        prepared_event_digest=str(row[18]),
        plan_schema_version=int(row[19]),
        plan_version=int(row[20]),
        plan_digest=str(row[21]),
        workflow_preparation_digest=str(row[22]),
        binding_schema_version=int(row[23]),
        binding_digest=str(row[24]),
        created_at=cast(datetime, row[25]),
    )


def _load_receipt_by_saga(
    conn: psycopg.Connection,
    workflow_saga_id: str,
) -> EnsureBoundCommandResult | None:
    row = conn.execute(
        f"""
        SELECT {_BINDING_SELECT}, commands.state, commands.version
        FROM {SCHEMA}.hermes_command_workflow_bindings AS binding
        JOIN {SCHEMA}.hermes_commands AS commands
          ON commands.command_id = binding.command_id
         AND commands.owner_user_id = %s
        WHERE binding.workflow_saga_id = %s
        """,
        (ROOT_USER_ID, workflow_saga_id),
    ).fetchone()
    return _receipt_from_row(row) if row is not None else None


def _load_receipt_by_prepared_event(
    conn: psycopg.Connection,
    *,
    task_id: str,
    prepared_event_id: str,
) -> EnsureBoundCommandResult | None:
    row = conn.execute(
        f"""
        SELECT {_BINDING_SELECT}, commands.state, commands.version
        FROM {SCHEMA}.hermes_command_workflow_bindings AS binding
        JOIN {SCHEMA}.hermes_commands AS commands
          ON commands.command_id = binding.command_id
         AND commands.owner_user_id = %s
        WHERE binding.task_id = %s
          AND binding.prepared_event_id = %s
        """,
        (ROOT_USER_ID, task_id, prepared_event_id),
    ).fetchone()
    return _receipt_from_row(row) if row is not None else None


def _load_receipt_by_command(
    conn: psycopg.Connection,
    command_id: UUID,
) -> EnsureBoundCommandResult | None:
    row = conn.execute(
        f"""
        SELECT {_BINDING_SELECT}, commands.state, commands.version
        FROM {SCHEMA}.hermes_command_workflow_bindings AS binding
        JOIN {SCHEMA}.hermes_commands AS commands
          ON commands.command_id = binding.command_id
         AND commands.owner_user_id = %s
        WHERE binding.command_id = %s
        """,
        (ROOT_USER_ID, command_id),
    ).fetchone()
    return _receipt_from_row(row) if row is not None else None


def _receipt_from_row(row: tuple[object, ...]) -> EnsureBoundCommandResult:
    binding = _binding_from_row(row[:26])
    return EnsureBoundCommandResult(
        command_id=binding.command_id,
        command_state=str(row[26]),
        command_version=int(row[27]),
        binding=binding,
        created=False,
    )


def _require_exact_receipt(
    receipt: EnsureBoundCommandResult,
    prepared: PreparedWorkflowCommand,
) -> EnsureBoundCommandResult:
    binding = receipt.binding
    expected_binding_digest = workflow_binding_digest(
        prepared,
        command_id=receipt.command_id,
    )
    exact_facts = (
        binding.command_version == 1,
        binding.preparation_schema_version == prepared.schema_version,
        binding.workflow_saga_id == prepared.workflow_saga_id,
        binding.owner_user_id == prepared.owner_user_id,
        binding.platform_session_id == prepared.platform_session_id,
        binding.client_request_id == prepared.client_request_id,
        binding.command_kind == prepared.command_kind,
        binding.canonical_request_digest == prepared.canonical_request_digest,
        binding.payload_ref == prepared.payload_ref,
        binding.payload_digest == prepared.payload_digest,
        binding.payload_expires_at == prepared.payload_expires_at,
        binding.provider_policy_digest == prepared.provider_policy_digest,
        binding.task_id == prepared.task_id,
        binding.task_version == prepared.task_version,
        binding.attempt_id == prepared.attempt_id,
        binding.attempt_number == prepared.attempt_number,
        binding.prepared_event_id == prepared.prepared_event_id,
        binding.prepared_event_digest == prepared.prepared_event_digest,
        binding.plan_schema_version == prepared.plan_schema_version,
        binding.plan_version == prepared.plan_version,
        binding.plan_digest == prepared.plan_digest,
        binding.workflow_preparation_digest == prepared.workflow_preparation_digest,
        binding.binding_schema_version == WORKFLOW_BINDING_SCHEMA_VERSION,
        binding.binding_digest == expected_binding_digest,
    )
    if not all(exact_facts):
        raise HermesCommandConflict(
            "workflow saga, idempotency key, or prepared event belongs to different exact facts"
        )
    return receipt


def _require_binding_database(settings: Settings):
    if command_ledger_schema_version(settings) != LEDGER_SCHEMA_VERSION:
        raise HermesCommandLedgerUnavailable("Hermes command ledger schema is not ready")
    database = get_database(settings)
    if database is None:
        raise HermesCommandLedgerUnavailable(
            "Hermes workflow binding requires PostgreSQL; no filesystem fallback exists"
        )
    return database


def ensure_bound_command(
    settings: Settings,
    prepared: PreparedWorkflowCommand,
) -> EnsureBoundCommandResult:
    """Atomically ensure command, creation event, exact binding, and outbox."""

    _validate_prepared(prepared)
    database = _require_binding_database(settings)
    try:
        with database.connect() as conn, conn.transaction():
            if not command_ledger_schema_is_ready_on_connection(conn):
                raise HermesCommandLedgerUnavailable("Hermes command ledger schema is not ready")
            if not workflow_binding_schema_is_ready_on_connection(conn):
                raise HermesCommandLedgerUnavailable("Hermes workflow binding schema is not ready")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"hermes-workflow-saga:{prepared.workflow_saga_id}",),
            )
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"hermes-prepared-event:{prepared.task_id}:{prepared.prepared_event_id}",),
            )

            existing = _load_receipt_by_saga(conn, prepared.workflow_saga_id)
            if existing is not None:
                return _require_exact_receipt(existing, prepared)
            prepared_event_receipt = _load_receipt_by_prepared_event(
                conn,
                task_id=prepared.task_id,
                prepared_event_id=prepared.prepared_event_id,
            )
            if prepared_event_receipt is not None:
                return _require_exact_receipt(prepared_event_receipt, prepared)

            expiry = conn.execute(
                "SELECT %s::timestamptz > clock_timestamp()",
                (prepared.payload_expires_at,),
            ).fetchone()
            if expiry is None or expiry[0] is not True:
                raise HermesCommandValidationError(
                    "payload has expired according to the PostgreSQL authority clock"
                )

            command_id = uuid4()
            command_row = conn.execute(
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
                VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, 'queued', 1)
                ON CONFLICT (owner_user_id, platform_session_id, client_request_id)
                DO NOTHING
                RETURNING command_id, state, version
                """,
                (
                    command_id,
                    prepared.owner_user_id,
                    prepared.platform_session_id,
                    prepared.client_request_id,
                    prepared.command_kind,
                    prepared.canonical_request_digest,
                    prepared.payload_ref,
                    prepared.provider_policy_digest,
                ),
            ).fetchone()
            if command_row is None:
                existing_command = conn.execute(
                    f"""
                    SELECT command_id
                    FROM {SCHEMA}.hermes_commands
                    WHERE owner_user_id = %s
                      AND platform_session_id = %s
                      AND client_request_id = %s
                    """,
                    (
                        prepared.owner_user_id,
                        prepared.platform_session_id,
                        prepared.client_request_id,
                    ),
                ).fetchone()
                if existing_command is None:
                    raise HermesCommandLedgerUnavailable(
                        "idempotent command lookup returned no durable row"
                    )
                existing_receipt = _load_receipt_by_command(
                    conn,
                    UUID(str(existing_command[0])),
                )
                if existing_receipt is None:
                    raise HermesCommandConflict(
                        "client_request_id belongs to an unbound or different command"
                    )
                return _require_exact_receipt(existing_receipt, prepared)

            binding_digest = workflow_binding_digest(prepared, command_id=command_id)
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
                    event_data
                )
                VALUES (%s, 1, 'command_created', 'system', NULL, 'queued', %s, 0, %s)
                """,
                (
                    command_id,
                    prepared.canonical_request_digest,
                    Jsonb(
                        {
                            "binding_digest": binding_digest,
                            "workflow_preparation_digest": (prepared.workflow_preparation_digest),
                            "workflow_saga_id": prepared.workflow_saga_id,
                        }
                    ),
                ),
            )
            binding_row = conn.execute(
                f"""
                INSERT INTO {SCHEMA}.hermes_command_workflow_bindings (
                    command_id,
                    command_version,
                    preparation_schema_version,
                    workflow_saga_id,
                    owner_user_id,
                    platform_session_id,
                    client_request_id,
                    command_kind,
                    canonical_request_digest,
                    payload_ref,
                    payload_digest,
                    payload_expires_at,
                    provider_policy_digest,
                    task_id,
                    task_version,
                    attempt_id,
                    attempt_number,
                    prepared_event_id,
                    prepared_event_digest,
                    plan_schema_version,
                    plan_version,
                    plan_digest,
                    workflow_preparation_digest,
                    binding_schema_version,
                    binding_digest
                )
                VALUES (
                    %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s
                )
                RETURNING
                    command_id,
                    command_version,
                    preparation_schema_version,
                    workflow_saga_id,
                    owner_user_id,
                    platform_session_id,
                    client_request_id,
                    command_kind,
                    canonical_request_digest,
                    payload_ref,
                    payload_digest,
                    payload_expires_at,
                    provider_policy_digest,
                    task_id,
                    task_version,
                    attempt_id,
                    attempt_number,
                    prepared_event_id,
                    prepared_event_digest,
                    plan_schema_version,
                    plan_version,
                    plan_digest,
                    workflow_preparation_digest,
                    binding_schema_version,
                    binding_digest,
                    created_at
                """,
                (
                    command_id,
                    prepared.schema_version,
                    prepared.workflow_saga_id,
                    prepared.owner_user_id,
                    prepared.platform_session_id,
                    prepared.client_request_id,
                    prepared.command_kind,
                    prepared.canonical_request_digest,
                    prepared.payload_ref,
                    prepared.payload_digest,
                    prepared.payload_expires_at,
                    prepared.provider_policy_digest,
                    prepared.task_id,
                    prepared.task_version,
                    prepared.attempt_id,
                    prepared.attempt_number,
                    prepared.prepared_event_id,
                    prepared.prepared_event_digest,
                    prepared.plan_schema_version,
                    prepared.plan_version,
                    prepared.plan_digest,
                    prepared.workflow_preparation_digest,
                    binding_digest,
                ),
            ).fetchone()
            if binding_row is None:
                raise HermesCommandLedgerUnavailable(
                    "workflow binding insert returned no durable row"
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
            conn.execute(
                "SELECT pg_notify(%s, %s)",
                (COMMAND_WAKEUP_CHANNEL, str(command_id)),
            )
            return EnsureBoundCommandResult(
                command_id=command_id,
                command_state=str(command_row[1]),
                command_version=int(command_row[2]),
                binding=_binding_from_row(binding_row),
                created=True,
            )
    except (
        HermesCommandConflict,
        HermesCommandLedgerUnavailable,
        HermesCommandValidationError,
    ):
        raise
    except (DatabaseUnavailable, psycopg.Error) as exc:
        raise HermesCommandLedgerUnavailable("Hermes workflow binding persistence failed") from exc


def _get_binding(
    settings: Settings,
    *,
    field: str,
    value: str,
) -> HermesWorkflowBinding:
    database = _require_binding_database(settings)
    if field not in {"workflow_saga_id", "binding_digest"}:
        raise AssertionError("unsupported workflow binding lookup")
    try:
        with database.connect() as conn, conn.transaction():
            if not command_ledger_schema_is_ready_on_connection(conn):
                raise HermesCommandLedgerUnavailable("Hermes command ledger schema is not ready")
            if not workflow_binding_schema_is_ready_on_connection(conn):
                raise HermesCommandLedgerUnavailable("Hermes workflow binding schema is not ready")
            row = conn.execute(
                f"""
                SELECT {_BINDING_SELECT}
                FROM {SCHEMA}.hermes_command_workflow_bindings AS binding
                JOIN {SCHEMA}.hermes_commands AS commands
                  ON commands.command_id = binding.command_id
                 AND commands.owner_user_id = %s
                WHERE binding.{field} = %s
                """,
                (ROOT_USER_ID, value),
            ).fetchone()
    except HermesCommandLedgerUnavailable:
        raise
    except (DatabaseUnavailable, psycopg.Error) as exc:
        raise HermesCommandLedgerUnavailable("Hermes workflow binding lookup failed") from exc
    if row is None:
        raise HermesCommandNotFound(value)
    return _binding_from_row(row)


def get_workflow_binding_by_saga(
    settings: Settings,
    workflow_saga_id: str,
) -> HermesWorkflowBinding:
    if _SAGA_ID_RE.fullmatch(workflow_saga_id) is None:
        raise HermesCommandValidationError("invalid workflow_saga_id")
    return _get_binding(
        settings,
        field="workflow_saga_id",
        value=workflow_saga_id,
    )


def get_workflow_binding_by_digest(
    settings: Settings,
    binding_digest: str,
) -> HermesWorkflowBinding:
    _validate_digest(binding_digest, field="binding_digest")
    return _get_binding(
        settings,
        field="binding_digest",
        value=binding_digest,
    )


def _prepared_from_binding(binding: HermesWorkflowBinding) -> PreparedWorkflowCommand:
    return PreparedWorkflowCommand(
        schema_version=binding.preparation_schema_version,
        workflow_saga_id=binding.workflow_saga_id,
        owner_user_id=binding.owner_user_id,
        platform_session_id=binding.platform_session_id,
        client_request_id=binding.client_request_id,
        command_kind=binding.command_kind,
        canonical_request_digest=binding.canonical_request_digest,
        payload_ref=binding.payload_ref,
        payload_digest=binding.payload_digest,
        payload_expires_at=binding.payload_expires_at,
        provider_policy_digest=binding.provider_policy_digest,
        task_id=binding.task_id,
        task_version=binding.task_version,
        attempt_id=binding.attempt_id,
        attempt_number=binding.attempt_number,
        prepared_event_id=binding.prepared_event_id,
        prepared_event_digest=binding.prepared_event_digest,
        plan_schema_version=binding.plan_schema_version,
        plan_version=binding.plan_version,
        plan_digest=binding.plan_digest,
        workflow_preparation_digest=binding.workflow_preparation_digest,
    )


def _verified_inventory_binding(row: tuple[object, ...]) -> dict[str, object]:
    try:
        binding = _binding_from_row(row[:26])
        prepared = _prepared_from_binding(binding)
        _validate_prepared(prepared)
        command_id = row[26]
        exact_command_mirror = (
            command_id is not None,
            binding.command_version == 1,
            binding.binding_schema_version == WORKFLOW_BINDING_SCHEMA_VERSION,
            command_id is not None and binding.command_id == UUID(str(command_id)),
            row[27] is not None and binding.owner_user_id == UUID(str(row[27])),
            binding.platform_session_id == row[28],
            binding.client_request_id == row[29],
            binding.command_kind == row[30],
            row[31] == 1,
            binding.canonical_request_digest == row[32],
            binding.payload_ref == row[33],
            binding.provider_policy_digest == row[34],
            binding.binding_digest
            == workflow_binding_digest(prepared, command_id=binding.command_id),
        )
        if not all(exact_command_mirror):
            raise ValueError("binding command mirror mismatch")
        return workflow_binding_to_dict(binding)
    except (
        HermesCommandValidationError,
        IndexError,
        TypeError,
        ValueError,
    ) as exc:
        raise HermesCommandLedgerUnavailable(
            "Hermes workflow binding inventory failed integrity verification"
        ) from exc


def _canonical_inventory_binding_line(binding: dict[str, object]) -> bytes:
    return (
        json.dumps(
            binding,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def iter_workflow_binding_inventory(
    settings: Settings,
) -> Iterator[dict[str, object]]:
    """Stream one verified metadata-only binding inventory snapshot."""

    try:
        database = _require_binding_database(settings)
        trailer: dict[str, object] | None = None
        with database.connect() as conn, conn.transaction():
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            if not workflow_binding_schema_is_ready_on_connection(
                conn,
                lock_meta_rows=False,
            ):
                raise HermesCommandLedgerUnavailable("Hermes workflow binding schema is not ready")
            with conn.cursor(name="hermes_workflow_binding_inventory") as cursor:
                cursor.execute(
                    f"""
                    SELECT {_BINDING_SELECT},
                           commands.command_id,
                           commands.owner_user_id,
                           commands.platform_session_id,
                           commands.client_request_id,
                           commands.kind,
                           commands.intent_schema_version,
                           commands.canonical_request_digest,
                           commands.payload_ref,
                           commands.provider_policy_digest
                    FROM {SCHEMA}.hermes_command_workflow_bindings AS binding
                    LEFT JOIN {SCHEMA}.hermes_commands AS commands
                      ON commands.command_id = binding.command_id
                    WHERE binding.owner_user_id = %s
                    ORDER BY binding.workflow_saga_id ASC, binding.command_id ASC
                    """,
                    (ROOT_USER_ID,),
                )
                yield {
                    "schema_version": WORKFLOW_BINDING_INVENTORY_SCHEMA_VERSION,
                    "kind": "workflow_binding_inventory_header",
                    "binding_schema_version": WORKFLOW_BINDING_SCHEMA_VERSION,
                }
                inventory_hasher = hashlib.sha256()
                count = 0
                while True:
                    rows = cursor.fetchmany(WORKFLOW_BINDING_INVENTORY_FETCH_SIZE)
                    if not rows:
                        break
                    for row in rows:
                        binding = _verified_inventory_binding(row)
                        count += 1
                        inventory_hasher.update(_canonical_inventory_binding_line(binding))
                        yield {
                            "schema_version": WORKFLOW_BINDING_INVENTORY_SCHEMA_VERSION,
                            "kind": "workflow_binding_inventory_item",
                            "ordinal": count,
                            "binding": binding,
                        }
                trailer = {
                    "schema_version": WORKFLOW_BINDING_INVENTORY_SCHEMA_VERSION,
                    "kind": "workflow_binding_inventory_trailer",
                    "count": count,
                    "bindings_sha256": inventory_hasher.hexdigest(),
                }
        if trailer is None:
            raise HermesCommandLedgerUnavailable(
                "Hermes workflow binding inventory produced no trailer"
            )
        yield trailer
    except HermesCommandLedgerUnavailable:
        raise
    except (DatabaseUnavailable, psycopg.Error, TypeError, ValueError) as exc:
        raise HermesCommandLedgerUnavailable(
            "Hermes workflow binding inventory is unavailable"
        ) from exc


def workflow_binding_schema_version(settings: Settings) -> int | None:
    """Return the independently verified binding schema version when available."""

    database = get_database(settings)
    if database is None:
        return None
    try:
        with database.connect() as conn, conn.transaction():
            ready = workflow_binding_schema_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return None
    return WORKFLOW_BINDING_SCHEMA_VERSION if ready else None


_REQUIRED_COLUMN_SIGNATURES = frozenset(
    {
        ("hermes_workflow_binding_meta", "singleton", "boolean", True, "true"),
        ("hermes_workflow_binding_meta", "schema_version", "integer", True, None),
        (
            "hermes_workflow_binding_meta",
            "updated_at",
            "timestamp with time zone",
            True,
            "now()",
        ),
        ("hermes_command_workflow_bindings", "command_id", "uuid", True, None),
        ("hermes_command_workflow_bindings", "command_version", "bigint", True, "1"),
        (
            "hermes_command_workflow_bindings",
            "preparation_schema_version",
            "text",
            True,
            "'1.0'::text",
        ),
        ("hermes_command_workflow_bindings", "workflow_saga_id", "text", True, None),
        ("hermes_command_workflow_bindings", "owner_user_id", "uuid", True, None),
        ("hermes_command_workflow_bindings", "platform_session_id", "text", True, None),
        ("hermes_command_workflow_bindings", "client_request_id", "text", True, None),
        ("hermes_command_workflow_bindings", "command_kind", "text", True, None),
        (
            "hermes_command_workflow_bindings",
            "canonical_request_digest",
            "character(64)",
            True,
            None,
        ),
        ("hermes_command_workflow_bindings", "payload_ref", "text", True, None),
        (
            "hermes_command_workflow_bindings",
            "payload_digest",
            "character(64)",
            True,
            None,
        ),
        (
            "hermes_command_workflow_bindings",
            "payload_expires_at",
            "timestamp with time zone",
            True,
            None,
        ),
        (
            "hermes_command_workflow_bindings",
            "provider_policy_digest",
            "character(64)",
            True,
            None,
        ),
        ("hermes_command_workflow_bindings", "task_id", "text", True, None),
        ("hermes_command_workflow_bindings", "task_version", "bigint", True, None),
        ("hermes_command_workflow_bindings", "attempt_id", "text", True, None),
        ("hermes_command_workflow_bindings", "attempt_number", "integer", True, None),
        ("hermes_command_workflow_bindings", "prepared_event_id", "text", True, None),
        (
            "hermes_command_workflow_bindings",
            "prepared_event_digest",
            "character(64)",
            True,
            None,
        ),
        ("hermes_command_workflow_bindings", "plan_schema_version", "integer", True, "1"),
        ("hermes_command_workflow_bindings", "plan_version", "bigint", True, None),
        (
            "hermes_command_workflow_bindings",
            "plan_digest",
            "character(64)",
            True,
            None,
        ),
        (
            "hermes_command_workflow_bindings",
            "workflow_preparation_digest",
            "character(64)",
            True,
            None,
        ),
        (
            "hermes_command_workflow_bindings",
            "binding_schema_version",
            "integer",
            True,
            "1",
        ),
        (
            "hermes_command_workflow_bindings",
            "binding_digest",
            "character(64)",
            True,
            None,
        ),
        (
            "hermes_command_workflow_bindings",
            "created_at",
            "timestamp with time zone",
            True,
            "now()",
        ),
    }
)

_REQUIRED_CONSTRAINTS = frozenset(
    {
        (
            "hermes_workflow_binding_meta",
            "hermes_workflow_binding_meta_pkey",
            "p",
            "PRIMARY KEY (singleton)",
        ),
        (
            "hermes_workflow_binding_meta",
            "ck_hermes_workflow_binding_meta_singleton",
            "c",
            "CHECK (singleton)",
        ),
        (
            "hermes_workflow_binding_meta",
            "ck_hermes_workflow_binding_meta_version",
            "c",
            "CHECK (schema_version > 0)",
        ),
        (
            "hermes_command_events",
            "uq_hermes_command_events_binding_anchor",
            "u",
            "UNIQUE (command_id, command_version, canonical_request_digest)",
        ),
        (
            "hermes_command_workflow_bindings",
            "hermes_command_workflow_bindings_pkey",
            "p",
            "PRIMARY KEY (command_id)",
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_saga",
            "u",
            "UNIQUE (workflow_saga_id)",
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_task_attempt_number",
            "u",
            "UNIQUE (task_id, attempt_number)",
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_attempt",
            "u",
            "UNIQUE (attempt_id)",
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_prepared_event",
            "u",
            "UNIQUE (task_id, prepared_event_id)",
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_digest",
            "u",
            "UNIQUE (binding_digest)",
        ),
        (
            "hermes_command_workflow_bindings",
            "fk_hermes_workflow_binding_command",
            "f",
            "FOREIGN KEY (command_id) REFERENCES quant_system.hermes_commands(command_id)",
        ),
        (
            "hermes_command_workflow_bindings",
            "fk_hermes_workflow_binding_owner",
            "f",
            "FOREIGN KEY (owner_user_id) REFERENCES quant_system.app_users(id)",
        ),
        (
            "hermes_command_workflow_bindings",
            "fk_hermes_workflow_binding_event_anchor",
            "f",
            "FOREIGN KEY (command_id, command_version, canonical_request_digest) "
            "REFERENCES quant_system.hermes_command_events(command_id, command_version, "
            "canonical_request_digest)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_command_version",
            "c",
            "CHECK (command_version = 1)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_preparation_schema",
            "c",
            "CHECK (preparation_schema_version = '1.0'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_saga",
            "c",
            "CHECK (workflow_saga_id ~ '^hqs_[0-9a-f]{24}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_platform_session",
            "c",
            "CHECK (char_length(platform_session_id) >= 1 AND "
            "char_length(platform_session_id) <= 200 AND platform_session_id ~ "
            "'^[A-Za-z0-9][A-Za-z0-9._:-]*$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_client_request",
            "c",
            "CHECK (char_length(client_request_id) >= 1 AND "
            "char_length(client_request_id) <= 200 AND client_request_id ~ "
            "'^[A-Za-z0-9][A-Za-z0-9._:-]*$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_command_kind",
            "c",
            "CHECK (command_kind = 'research_chat'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_request_digest",
            "c",
            "CHECK (canonical_request_digest ~ '^[0-9a-f]{64}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_payload_digest",
            "c",
            "CHECK (payload_digest ~ '^[0-9a-f]{64}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_payload_ref",
            "c",
            "CHECK (payload_ref = ('hqa-payload:sha256:'::text || payload_digest::text))",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_provider_digest",
            "c",
            "CHECK (provider_policy_digest ~ '^[0-9a-f]{64}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_task",
            "c",
            "CHECK (task_id ~ '^hqt_[0-9a-f]{24}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_task_version",
            "c",
            "CHECK (task_version > 0)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_attempt",
            "c",
            "CHECK (attempt_id ~ '^hqa_[0-9a-f]{24}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_attempt_number",
            "c",
            "CHECK (attempt_number > 0)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_prepared_event",
            "c",
            "CHECK (prepared_event_id ~ '^hqe_[0-9a-f]{24}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_prepared_event_digest",
            "c",
            "CHECK (prepared_event_digest ~ '^[0-9a-f]{64}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_plan_schema",
            "c",
            "CHECK (plan_schema_version = 1)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_plan_version",
            "c",
            "CHECK (plan_version > 0)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_plan_digest",
            "c",
            "CHECK (plan_digest ~ '^[0-9a-f]{64}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_preparation_digest",
            "c",
            "CHECK (workflow_preparation_digest ~ '^[0-9a-f]{64}$'::text)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_schema",
            "c",
            "CHECK (binding_schema_version = 1)",
        ),
        (
            "hermes_command_workflow_bindings",
            "ck_hermes_workflow_binding_digest",
            "c",
            "CHECK (binding_digest ~ '^[0-9a-f]{64}$'::text)",
        ),
    }
)

_REQUIRED_INDEXES = frozenset(
    {
        (
            "hermes_command_workflow_bindings",
            "idx_hermes_workflow_binding_task_attempt",
            False,
            ("task_id", "attempt_id", "created_at", "command_id"),
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_saga",
            True,
            ("workflow_saga_id",),
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_task_attempt_number",
            True,
            ("task_id", "attempt_number"),
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_attempt",
            True,
            ("attempt_id",),
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_prepared_event",
            True,
            ("task_id", "prepared_event_id"),
        ),
        (
            "hermes_command_workflow_bindings",
            "uq_hermes_workflow_binding_digest",
            True,
            ("binding_digest",),
        ),
        (
            "hermes_command_events",
            "uq_hermes_command_events_binding_anchor",
            True,
            ("command_id", "command_version", "canonical_request_digest"),
        ),
    }
)

_REQUIRED_TRIGGERS = frozenset(
    {
        (
            "hermes_command_workflow_bindings",
            "trg_hermes_workflow_binding_validate",
            7,
            "validate_hermes_workflow_binding",
            "A",
            "CREATE TRIGGER trg_hermes_workflow_binding_validate BEFORE INSERT ON "
            "quant_system.hermes_command_workflow_bindings FOR EACH ROW EXECUTE "
            "FUNCTION quant_system.validate_hermes_workflow_binding()",
            None,
            "",
        ),
        (
            "hermes_command_workflow_bindings",
            "trg_hermes_workflow_binding_append_only",
            27,
            "reject_hermes_workflow_binding_mutation",
            "A",
            "CREATE TRIGGER trg_hermes_workflow_binding_append_only BEFORE DELETE OR "
            "UPDATE ON quant_system.hermes_command_workflow_bindings FOR EACH ROW "
            "EXECUTE FUNCTION quant_system.reject_hermes_workflow_binding_mutation()",
            None,
            "",
        ),
        (
            "hermes_command_workflow_bindings",
            "trg_hermes_workflow_binding_append_only_truncate",
            34,
            "reject_hermes_workflow_binding_mutation",
            "A",
            "CREATE TRIGGER trg_hermes_workflow_binding_append_only_truncate BEFORE "
            "TRUNCATE ON quant_system.hermes_command_workflow_bindings FOR EACH "
            "STATEMENT EXECUTE FUNCTION "
            "quant_system.reject_hermes_workflow_binding_mutation()",
            None,
            "",
        ),
        (
            "hermes_commands",
            "trg_hermes_command_intent_immutable",
            19,
            "protect_hermes_command_intent_identity",
            "A",
            "CREATE TRIGGER trg_hermes_command_intent_immutable BEFORE UPDATE ON "
            "quant_system.hermes_commands FOR EACH ROW EXECUTE FUNCTION "
            "quant_system.protect_hermes_command_intent_identity()",
            None,
            "",
        ),
        (
            "hermes_commands",
            "trg_hermes_command_claim_binding_guard",
            17,
            "enforce_hermes_claim_binding_eligibility",
            "A",
            "CREATE TRIGGER trg_hermes_command_claim_binding_guard AFTER UPDATE OF "
            "state ON quant_system.hermes_commands FOR EACH ROW EXECUTE FUNCTION "
            "quant_system.enforce_hermes_claim_binding_eligibility()",
            None,
            "",
        ),
    }
)

_REQUIRED_FUNCTIONS = frozenset(
    {
        (
            "enforce_hermes_claim_binding_eligibility",
            "plpgsql",
            False,
            "v",
            # 008_l2a_conversation_turn_claim.sql — research binding OR
            # store-backed conversation_turn claim path.
            "82f5e1d2f04e077eba8894a6111f41ab2989cdc9e4b00ca53aef34d4b4ebba10",
        ),
        (
            "protect_hermes_command_intent_identity",
            "plpgsql",
            False,
            "v",
            "53d9e5a2d699db5e761efb0eefd34ca981012ffc3d3f0fca81bbe76c44ab334a",
        ),
        (
            "reject_hermes_workflow_binding_mutation",
            "plpgsql",
            False,
            "v",
            "e769baede7d05d6a4920431076f0b593bfc0273e9544d787871069d5bb44561c",
        ),
        (
            "validate_hermes_workflow_binding",
            "plpgsql",
            False,
            "v",
            "b0d49a504cc479b37975ca1b2eb2c63477d6272a8f07e7f30b3c52807fb08da6",
        ),
    }
)


def _workflow_binding_schema_signature_is_ready(conn: psycopg.Connection) -> bool:
    table_names = [
        "hermes_workflow_binding_meta",
        "hermes_command_workflow_bindings",
    ]
    column_rows = conn.execute(
        """
        SELECT relation.relname,
               attribute.attname,
               format_type(attribute.atttypid, attribute.atttypmod),
               attribute.attnotnull,
               pg_get_expr(default_value.adbin, default_value.adrelid, true)
        FROM pg_attribute AS attribute
        JOIN pg_class AS relation ON relation.oid = attribute.attrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        LEFT JOIN pg_attrdef AS default_value
          ON default_value.adrelid = attribute.attrelid
         AND default_value.adnum = attribute.attnum
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        """,
        (SCHEMA, table_names),
    ).fetchall()
    actual_columns = {
        (
            str(table),
            str(column),
            str(data_type),
            bool(not_null),
            str(default) if default is not None else None,
        )
        for table, column, data_type, not_null, default in column_rows
    }
    if not _REQUIRED_COLUMN_SIGNATURES.issubset(actual_columns):
        return False

    constraint_rows = conn.execute(
        """
        SELECT relation.relname,
               constraint_object.conname,
               constraint_object.contype,
               constraint_object.convalidated,
               pg_get_constraintdef(constraint_object.oid, true)
        FROM pg_constraint AS constraint_object
        JOIN pg_class AS relation ON relation.oid = constraint_object.conrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
        """,
        (SCHEMA, [*table_names, "hermes_command_events"]),
    ).fetchall()
    actual_constraints = {
        (str(table), str(name), str(kind), str(definition))
        for table, name, kind, validated, definition in constraint_rows
        if bool(validated)
    }
    if not _REQUIRED_CONSTRAINTS.issubset(actual_constraints):
        return False
    # Refuse the pre-revision UNIQUE(task_id)-only shape even if the required
    # multi-Attempt constraint is also present. Subset matching alone would
    # otherwise accept a table that still forbids Research Task 1:N Attempt.
    if any(
        name == "uq_hermes_workflow_binding_task"
        or (
            kind == "u"
            and table == "hermes_command_workflow_bindings"
            and definition.replace(" ", "").lower() == "unique(task_id)"
        )
        for table, name, kind, definition in actual_constraints
    ):
        return False

    index_rows = conn.execute(
        """
        SELECT table_relation.relname,
               index_relation.relname,
               index_object.indisvalid,
               index_object.indisready,
               index_object.indisunique,
               ARRAY(
                   SELECT attribute.attname
                   FROM unnest(index_object.indkey)
                       WITH ORDINALITY AS index_key(attnum, ordinality)
                   JOIN pg_attribute AS attribute
                     ON attribute.attrelid = index_object.indrelid
                    AND attribute.attnum = index_key.attnum
                   WHERE index_key.ordinality <= index_object.indnkeyatts
                   ORDER BY index_key.ordinality
               )
        FROM pg_index AS index_object
        JOIN pg_class AS index_relation ON index_relation.oid = index_object.indexrelid
        JOIN pg_class AS table_relation ON table_relation.oid = index_object.indrelid
        JOIN pg_namespace AS namespace ON namespace.oid = index_relation.relnamespace
        WHERE namespace.nspname = %s
          AND index_relation.relname = ANY(%s)
        """,
        (SCHEMA, [signature[1] for signature in _REQUIRED_INDEXES]),
    ).fetchall()
    actual_indexes = {
        (str(table), str(name), bool(unique), tuple(str(key) for key in keys))
        for table, name, valid, ready, unique, keys in index_rows
        if bool(valid) and bool(ready)
    }
    if not _REQUIRED_INDEXES.issubset(actual_indexes):
        return False

    function_rows = conn.execute(
        """
        SELECT procedure.proname,
               language.lanname,
               procedure.prosecdef,
               procedure.provolatile,
               procedure.prosrc
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language ON language.oid = procedure.prolang
        WHERE namespace.nspname = %s
          AND procedure.proname = ANY(%s)
          AND procedure.pronargs = 0
          AND procedure.prorettype = 'trigger'::regtype
        """,
        (SCHEMA, [signature[0] for signature in _REQUIRED_FUNCTIONS]),
    ).fetchall()
    actual_functions = {
        (
            str(name),
            str(language),
            bool(security_definer),
            str(volatility),
            hashlib.sha256(" ".join(str(source).split()).encode()).hexdigest(),
        )
        for name, language, security_definer, volatility, source in function_rows
    }
    if not _REQUIRED_FUNCTIONS.issubset(actual_functions):
        return False

    trigger_rows = conn.execute(
        """
        SELECT relation.relname,
               trigger.tgname,
               trigger.tgtype,
               procedure.proname,
               trigger.tgenabled,
               pg_get_triggerdef(trigger.oid, true),
               pg_get_expr(trigger.tgqual, trigger.tgrelid, true),
               encode(trigger.tgargs, 'escape')
        FROM pg_trigger AS trigger
        JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
        JOIN pg_namespace AS procedure_namespace
          ON procedure_namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = %s
          AND procedure_namespace.nspname = %s
          AND trigger.tgname = ANY(%s)
          AND NOT trigger.tgisinternal
        """,
        (SCHEMA, SCHEMA, [signature[1] for signature in _REQUIRED_TRIGGERS]),
    ).fetchall()
    actual_triggers = {
        (
            str(table),
            str(name),
            int(kind),
            str(function),
            str(enabled),
            str(definition),
            str(qualifier) if qualifier is not None else None,
            str(arguments),
        )
        for table, name, kind, function, enabled, definition, qualifier, arguments in (trigger_rows)
    }
    return _REQUIRED_TRIGGERS.issubset(actual_triggers)


def workflow_binding_schema_is_ready_on_connection(
    conn: psycopg.Connection,
    *,
    lock_meta_rows: bool = True,
) -> bool:
    """Verify ledger evidence plus the complete binding schema in one transaction."""

    if not command_ledger_schema_is_ready_on_connection(
        conn,
        lock_meta_row=lock_meta_rows,
    ):
        return False
    conn.execute(
        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
        ("quant_system:006_hermes_workflow_binding",),
    )
    meta_query = f"""
        SELECT schema_version
        FROM {SCHEMA}.hermes_workflow_binding_meta
        WHERE singleton IS TRUE
    """
    if lock_meta_rows:
        meta_query += " FOR SHARE"
    row = conn.execute(meta_query).fetchone()
    return (
        row is not None
        and int(row[0]) == WORKFLOW_BINDING_SCHEMA_VERSION
        and _workflow_binding_schema_signature_is_ready(conn)
    )


__all__ = [
    "EnsureBoundCommandResult",
    "HermesWorkflowBinding",
    "PREPARED_RECEIPT_SCHEMA_VERSION",
    "PreparedWorkflowCommand",
    "RESEARCH_COMMAND_KIND",
    "WORKFLOW_BINDING_INVENTORY_FETCH_SIZE",
    "WORKFLOW_BINDING_INVENTORY_SCHEMA_VERSION",
    "WORKFLOW_BINDING_SCHEMA_VERSION",
    "ensure_bound_command",
    "get_workflow_binding_by_digest",
    "get_workflow_binding_by_saga",
    "iter_workflow_binding_inventory",
    "workflow_binding_digest",
    "workflow_binding_schema_version",
    "workflow_binding_schema_is_ready_on_connection",
    "workflow_binding_to_dict",
    "workflow_preparation_digest",
]
