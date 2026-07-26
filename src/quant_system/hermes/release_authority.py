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
from quant_system.hermes.candidate_admission_authority import (
    AcceptedCandidateReleaseBinding,
    CandidateAdmissionAuthority,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
    schema_fingerprint,
)

RELEASE_AUTHORITY_SCHEMA_VERSION = 1
RELEASE_HARDENING_SCHEMA_VERSION = 1
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
_BOUND_STAMP_COLUMNS = (
    _STAMP_COLUMNS
    + """,
    candidate_admission_id,
    candidate_admission_digest,
    candidate_acceptance_digest,
    evidence_set_id,
    evidence_set_digest,
    final_order_snapshot_digest,
    paper_authority_epoch
"""
)
_BOUND_CUTOVER_COLUMNS = (
    _CUTOVER_COLUMNS
    + """,
    candidate_admission_id,
    candidate_admission_digest,
    candidate_acceptance_digest,
    evidence_set_id,
    evidence_set_digest,
    final_order_snapshot_digest,
    paper_authority_epoch
"""
)


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
        raise ReleaseAuthorityValidationError(f"{field} must be a bounded identifier")
    return value


def _validate_digest(value: str, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ReleaseAuthorityValidationError(f"{field} must be a lowercase SHA-256 digest")
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
    candidate_admission_id: str | None = None,
    candidate_admission_digest: str | None = None,
    candidate_acceptance_digest: str | None = None,
    evidence_set_id: str | None = None,
    evidence_set_digest: str | None = None,
    final_order_snapshot_digest: str | None = None,
    paper_authority_epoch: int | None = None,
) -> str:
    payload: dict[str, object] = {
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
    candidate_binding = (
        candidate_admission_id,
        candidate_admission_digest,
        candidate_acceptance_digest,
        evidence_set_id,
        evidence_set_digest,
        final_order_snapshot_digest,
        paper_authority_epoch,
    )
    if any(value is not None for value in candidate_binding):
        if (
            not all(value is not None for value in candidate_binding)
            or isinstance(paper_authority_epoch, bool)
            or not isinstance(paper_authority_epoch, int)
            or paper_authority_epoch <= 0
        ):
            raise ReleaseAuthorityValidationError("release candidate binding must be complete")
        payload.update(
            {
                "candidate_acceptance_digest": candidate_acceptance_digest,
                "candidate_admission_digest": candidate_admission_digest,
                "candidate_admission_id": candidate_admission_id,
                "evidence_set_digest": evidence_set_digest,
                "evidence_set_id": evidence_set_id,
                "final_order_snapshot_digest": (final_order_snapshot_digest),
                "paper_authority_epoch": paper_authority_epoch,
            }
        )
    return _canonical_digest(payload)


def canonical_public_cutover_digest(
    *,
    cutover_id: str,
    stamp_id: str,
    workspace_id: str,
    route: str,
    release_digest: str,
    opened_at: datetime,
    candidate_admission_id: str | None = None,
    candidate_admission_digest: str | None = None,
    candidate_acceptance_digest: str | None = None,
    evidence_set_id: str | None = None,
    evidence_set_digest: str | None = None,
    final_order_snapshot_digest: str | None = None,
    paper_authority_epoch: int | None = None,
) -> str:
    payload: dict[str, object] = {
        "cutover_id": cutover_id,
        "opened_at": _canonical_timestamp(opened_at),
        "release_digest": release_digest,
        "route": route,
        "stamp_id": stamp_id,
        "workspace_id": workspace_id,
    }
    candidate_binding = (
        candidate_admission_id,
        candidate_admission_digest,
        candidate_acceptance_digest,
        evidence_set_id,
        evidence_set_digest,
        final_order_snapshot_digest,
        paper_authority_epoch,
    )
    if any(value is not None for value in candidate_binding):
        if (
            not all(value is not None for value in candidate_binding)
            or isinstance(paper_authority_epoch, bool)
            or not isinstance(paper_authority_epoch, int)
            or paper_authority_epoch <= 0
        ):
            raise ReleaseAuthorityValidationError("cutover candidate binding must be complete")
        payload.update(
            {
                "candidate_acceptance_digest": candidate_acceptance_digest,
                "candidate_admission_digest": candidate_admission_digest,
                "candidate_admission_id": candidate_admission_id,
                "evidence_set_digest": evidence_set_digest,
                "evidence_set_id": evidence_set_id,
                "final_order_snapshot_digest": (final_order_snapshot_digest),
                "paper_authority_epoch": paper_authority_epoch,
            }
        )
    return _canonical_digest(payload)


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
    candidate_admission_id: str | None = None
    candidate_admission_digest: str | None = None
    candidate_acceptance_digest: str | None = None
    evidence_set_id: str | None = None
    evidence_set_digest: str | None = None
    final_order_snapshot_digest: str | None = None
    paper_authority_epoch: int | None = None


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
    candidate_admission_id: str | None = None
    candidate_admission_digest: str | None = None
    candidate_acceptance_digest: str | None = None
    evidence_set_id: str | None = None
    evidence_set_digest: str | None = None
    final_order_snapshot_digest: str | None = None
    paper_authority_epoch: int | None = None


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
        candidate_admission_id=(str(row[13]) if len(row) > 13 and row[13] is not None else None),
        candidate_admission_digest=(
            str(row[14]).strip() if len(row) > 14 and row[14] is not None else None
        ),
        candidate_acceptance_digest=(
            str(row[15]).strip() if len(row) > 15 and row[15] is not None else None
        ),
        evidence_set_id=(str(row[16]) if len(row) > 16 and row[16] is not None else None),
        evidence_set_digest=(
            str(row[17]).strip() if len(row) > 17 and row[17] is not None else None
        ),
        final_order_snapshot_digest=(
            str(row[18]).strip() if len(row) > 18 and row[18] is not None else None
        ),
        paper_authority_epoch=(int(row[19]) if len(row) > 19 and row[19] is not None else None),
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
        candidate_admission_id=(str(row[10]) if len(row) > 10 and row[10] is not None else None),
        candidate_admission_digest=(
            str(row[11]).strip() if len(row) > 11 and row[11] is not None else None
        ),
        candidate_acceptance_digest=(
            str(row[12]).strip() if len(row) > 12 and row[12] is not None else None
        ),
        evidence_set_id=(str(row[13]) if len(row) > 13 and row[13] is not None else None),
        evidence_set_digest=(
            str(row[14]).strip() if len(row) > 14 and row[14] is not None else None
        ),
        final_order_snapshot_digest=(
            str(row[15]).strip() if len(row) > 15 and row[15] is not None else None
        ),
        paper_authority_epoch=(int(row[16]) if len(row) > 16 and row[16] is not None else None),
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
        raise ReleaseAuthorityUnavailable("stored receipt timestamp is invalid") from exc


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
        "agent_v02_release_hardening_meta",
        "agent_v02_release_stamps",
        "agent_v02_public_cutovers",
        "agent_v02_release_events",
        "agent_v02_release_actions",
        "agent_v02_paper_authority_owner_epochs",
        "agent_v02_paper_authority_epochs",
        "agent_v02_candidate_admissions",
        "agent_v02_candidate_evidence_sets",
        "paper_accounts",
        "paper_account_ledger",
        "paper_pending_orders",
        "paper_positions_current",
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
    hardening_version = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_release_hardening_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if hardening_version != (RELEASE_HARDENING_SCHEMA_VERSION,):
        return False
    sequence = conn.execute(
        """
        SELECT count(*) = 1
        FROM pg_class relation
        JOIN pg_namespace namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname =
                'agent_v02_paper_authority_epoch_seq'
          AND relation.relkind = 'S'
        """,
        (SCHEMA,),
    ).fetchone()
    if sequence != (True,):
        return False
    required_insert_functions = (
        (
            "quant_system.insert_agent_v02_release_stamp("
            "text,text,text,text,text,text,text,text,text,timestamp with time zone,"
            "text,text,text,text,text,text,bigint)"
        ),
        (
            "quant_system.insert_agent_v02_public_cutover("
            "text,text,text,text,text,text,timestamp with time zone,"
            "text,text,text,text,text,text,bigint)"
        ),
    )
    functions = conn.execute(
        """
        SELECT to_regprocedure(signature) IS NOT NULL
        FROM unnest(%s::text[]) AS required(signature)
        """,
        (list(required_insert_functions),),
    ).fetchall()
    if len(functions) != len(required_insert_functions) or not all(
        bool(row[0]) for row in functions
    ):
        return False
    required_columns = {
        ("agent_v02_candidate_admissions", "paper_authority_epoch"),
        ("agent_v02_candidate_evidence_sets", "paper_authority_epoch"),
        *{
            (table_name, column_name)
            for table_name in (
                "agent_v02_release_stamps",
                "agent_v02_public_cutovers",
            )
            for column_name in (
                "candidate_admission_id",
                "candidate_admission_digest",
                "candidate_acceptance_digest",
                "evidence_set_id",
                "evidence_set_digest",
                "final_order_snapshot_digest",
                "paper_authority_epoch",
            )
        },
    }
    required_column_pairs = sorted(required_columns)
    columns = conn.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND (table_name, column_name) IN (
              SELECT required.table_name, required.column_name
              FROM unnest(%s::text[], %s::text[])
                  AS required(table_name, column_name)
          )
        """,
        (
            SCHEMA,
            [table_name for table_name, _ in required_column_pairs],
            [column_name for _, column_name in required_column_pairs],
        ),
    ).fetchall()
    if {
        (str(table_name), str(column_name)) for table_name, column_name in columns
    } != required_columns:
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
    required_triggers = {
        "trg_agent_v02_release_stamps_update",
        "trg_agent_v02_release_stamps_delete",
        "trg_agent_v02_release_stamps_truncate",
        "trg_agent_v02_cutovers_update",
        "trg_agent_v02_cutovers_delete",
        "trg_agent_v02_cutovers_truncate",
        "trg_agent_v02_release_events_update",
        "trg_agent_v02_release_events_delete",
        "trg_agent_v02_release_events_truncate",
        "trg_agent_v02_release_actions_update",
        "trg_agent_v02_release_actions_delete",
        "trg_agent_v02_release_actions_truncate",
        "trg_agent_v02_paper_epoch_paper_accounts",
        "trg_agent_v02_paper_epoch_paper_account_ledger",
        "trg_agent_v02_paper_epoch_paper_pending_orders",
        "trg_agent_v02_paper_epoch_paper_positions_current",
        "trg_agent_v02_candidate_admission_epoch_bind",
        "trg_agent_v02_candidate_acceptance_epoch_guard",
        "trg_agent_v02_candidate_evidence_epoch_bind",
        "trg_agent_v02_release_stamps_insert_guard",
        "trg_agent_v02_release_stamps_binding_update",
        "trg_agent_v02_cutovers_insert_guard",
        "trg_agent_v02_cutovers_binding_update",
    }
    triggers = conn.execute(
        """
        SELECT trigger.tgname, trigger.tgenabled
        FROM pg_trigger trigger
        JOIN pg_class relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND trigger.tgname = ANY(%s)
          AND NOT trigger.tgisinternal
        """,
        (SCHEMA, list(required_triggers)),
    ).fetchall()
    return {(str(trigger_name), str(enabled)) for trigger_name, enabled in triggers} == {
        (trigger_name, "A") for trigger_name in required_triggers
    }


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
        "agent_v02_paper_authority_owner_epochs",
        "agent_v02_paper_authority_epochs",
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
    if {(str(row[0]), str(row[1])) for row in policies} != {
        (table_name, policy_name)
        for table_name in tables
        for policy_name in ("v4r_root_scope", "v4r_migrator_all")
    }:
        return False
    root_expression = "(owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid)"
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
            "SELECT,UPDATE",
            "INSERT,DELETE,TRUNCATE",
        ),
        "agent_v02_public_cutovers": (
            "SELECT,UPDATE",
            "INSERT,DELETE,TRUNCATE",
        ),
        "agent_v02_release_events": (
            "SELECT,INSERT",
            "UPDATE,DELETE,TRUNCATE",
        ),
        "agent_v02_release_actions": (
            "SELECT,INSERT",
            "UPDATE,DELETE,TRUNCATE",
        ),
        "agent_v02_paper_authority_epochs": (
            "SELECT",
            "INSERT,UPDATE,DELETE,TRUNCATE",
        ),
        "agent_v02_paper_authority_owner_epochs": (
            "SELECT",
            "INSERT,UPDATE,DELETE,TRUNCATE",
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
    controlled_insert_privileges = conn.execute(
        """
        SELECT
            has_function_privilege(
                session_user,
                %s,
                'EXECUTE'
            ),
            has_function_privilege(
                session_user,
                %s,
                'EXECUTE'
            ),
            NOT has_function_privilege(
                'quant_readonly',
                %s,
                'EXECUTE'
            ),
            NOT has_function_privilege(
                'quant_readonly',
                %s,
                'EXECUTE'
            )
        """,
        (
            (
                f"{SCHEMA}.insert_agent_v02_release_stamp("
                "text,text,text,text,text,text,text,text,text,"
                "timestamp with time zone,text,text,text,text,text,text,bigint)"
            ),
            (
                f"{SCHEMA}.insert_agent_v02_public_cutover("
                "text,text,text,text,text,text,timestamp with time zone,"
                "text,text,text,text,text,text,bigint)"
            ),
            (
                f"{SCHEMA}.insert_agent_v02_release_stamp("
                "text,text,text,text,text,text,text,text,text,"
                "timestamp with time zone,text,text,text,text,text,text,bigint)"
            ),
            (
                f"{SCHEMA}.insert_agent_v02_public_cutover("
                "text,text,text,text,text,text,timestamp with time zone,"
                "text,text,text,text,text,text,bigint)"
            ),
        ),
    ).fetchone()
    if controlled_insert_privileges != (True, True, True, True):
        return False
    controlled_insert_security = conn.execute(
        """
        SELECT
            count(*) = 2,
            bool_and(function_row.prosecdef),
            bool_and(function_row.provolatile = 'v'),
            bool_and(pg_get_userbyid(function_row.proowner) = 'quant_migrator')
        FROM pg_proc AS function_row
        WHERE function_row.oid IN (to_regprocedure(%s), to_regprocedure(%s))
        """,
        (
            (
                f"{SCHEMA}.insert_agent_v02_release_stamp("
                "text,text,text,text,text,text,text,text,text,"
                "timestamp with time zone,text,text,text,text,text,text,bigint)"
            ),
            (
                f"{SCHEMA}.insert_agent_v02_public_cutover("
                "text,text,text,text,text,text,timestamp with time zone,"
                "text,text,text,text,text,text,bigint)"
            ),
        ),
    ).fetchone()
    if controlled_insert_security != (True, True, True, True):
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
            ),
            has_table_privilege(session_user, %s, 'SELECT'),
            NOT has_table_privilege(
                session_user,
                %s,
                'INSERT,UPDATE,DELETE,TRUNCATE'
            ),
            NOT has_sequence_privilege(
                session_user,
                %s,
                'USAGE,SELECT,UPDATE'
            )
        """,
        (
            f"{SCHEMA}.agent_v02_release_authority_meta",
            f"{SCHEMA}.agent_v02_release_authority_meta",
            f"{SCHEMA}.agent_v02_release_events_event_cursor_seq",
            f"{SCHEMA}.agent_v02_release_hardening_meta",
            f"{SCHEMA}.agent_v02_release_hardening_meta",
            f"{SCHEMA}.agent_v02_paper_authority_epoch_seq",
        ),
    ).fetchone()
    return meta_privileges == (True, True, True, True, True, True)


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
            raise ReleaseAuthorityUnavailable("release authority requires PostgreSQL")
        return database

    @staticmethod
    def _hardening_installed(conn: psycopg.Connection) -> bool:
        row = conn.execute(
            """
            SELECT
                to_regclass(
                    'quant_system.agent_v02_release_hardening_meta'
                ) IS NOT NULL
            """
        ).fetchone()
        if row != (True,):
            return False
        version = conn.execute(
            f"""
            SELECT schema_version
            FROM {SCHEMA}.agent_v02_release_hardening_meta
            WHERE singleton IS TRUE
            """
        ).fetchone()
        return version == (RELEASE_HARDENING_SCHEMA_VERSION,)

    @classmethod
    def _stamp_columns(cls, conn: psycopg.Connection) -> str:
        return _BOUND_STAMP_COLUMNS if cls._hardening_installed(conn) else _STAMP_COLUMNS

    @classmethod
    def _cutover_columns(cls, conn: psycopg.Connection) -> str:
        return _BOUND_CUTOVER_COLUMNS if cls._hardening_installed(conn) else _CUTOVER_COLUMNS

    @staticmethod
    def _accepted_binding_on_connection(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        route: str,
        platform_runtime_digest: str,
        hqa_runtime_digest: str,
        hermes_runtime_digest: str,
        database_schema_fingerprint: str,
        final_evidence_digest: str,
    ) -> AcceptedCandidateReleaseBinding | None:
        row = conn.execute(
            f"""
            SELECT
                candidate.admission_id,
                candidate.workspace_id,
                candidate.route,
                candidate.admission_digest,
                candidate.acceptance_digest,
                candidate.platform_runtime_digest,
                candidate.hqa_runtime_digest,
                candidate.hermes_runtime_digest,
                candidate.database_schema_fingerprint,
                candidate.final_evidence_digest,
                candidate.evidence_set_id,
                candidate.evidence_set_digest,
                candidate.final_order_snapshot_digest,
                candidate.paper_authority_epoch
            FROM {SCHEMA}.agent_v02_candidate_admissions AS candidate
            JOIN {SCHEMA}.agent_v02_candidate_evidence_sets
                AS evidence_set
              ON evidence_set.evidence_set_id =
                    candidate.evidence_set_id
             AND evidence_set.admission_id = candidate.admission_id
             AND evidence_set.owner_user_id = candidate.owner_user_id
             AND evidence_set.workspace_id = candidate.workspace_id
             AND evidence_set.admission_digest =
                    candidate.admission_digest
             AND evidence_set.facts_digest =
                    candidate.evidence_set_digest
             AND evidence_set.final_order_snapshot_digest =
                    candidate.final_order_snapshot_digest
             AND evidence_set.baseline_order_snapshot_digest =
                    candidate.baseline_order_snapshot_digest
             AND evidence_set.paper_authority_epoch =
                    candidate.paper_authority_epoch
            JOIN {SCHEMA}.agent_v02_paper_authority_epochs
                AS paper_epoch
              ON paper_epoch.owner_user_id = candidate.owner_user_id
             AND paper_epoch.workspace_id = candidate.workspace_id
             AND paper_epoch.authority_epoch =
                    candidate.paper_authority_epoch
            JOIN {SCHEMA}.agent_v02_paper_authority_owner_epochs
                AS owner_epoch
              ON owner_epoch.owner_user_id = candidate.owner_user_id
             AND owner_epoch.authority_epoch =
                    candidate.paper_authority_epoch
            WHERE candidate.owner_user_id = %s
              AND candidate.workspace_id = %s
              AND candidate.route = %s
              AND candidate.status = 'accepted'
              AND candidate.platform_runtime_digest = %s
              AND candidate.hqa_runtime_digest = %s
              AND candidate.hermes_runtime_digest = %s
              AND candidate.database_schema_fingerprint = %s
              AND candidate.final_evidence_digest = %s
              AND candidate.acceptance_digest IS NOT NULL
              AND candidate.final_order_snapshot_digest =
                    candidate.baseline_order_snapshot_digest
            ORDER BY candidate.closed_at DESC, candidate.admission_id DESC
            LIMIT 1
            """,
            (
                ROOT_USER_ID,
                workspace_id,
                route,
                platform_runtime_digest,
                hqa_runtime_digest,
                hermes_runtime_digest,
                database_schema_fingerprint,
                final_evidence_digest,
            ),
        ).fetchone()
        if row is None:
            return None
        return AcceptedCandidateReleaseBinding(
            admission_id=str(row[0]),
            workspace_id=str(row[1]),
            route=str(row[2]),
            admission_digest=str(row[3]).strip(),
            acceptance_digest=str(row[4]).strip(),
            platform_runtime_digest=str(row[5]).strip(),
            hqa_runtime_digest=str(row[6]).strip(),
            hermes_runtime_digest=str(row[7]).strip(),
            database_schema_fingerprint=str(row[8]).strip(),
            final_evidence_digest=str(row[9]).strip(),
            evidence_set_id=str(row[10]),
            evidence_set_digest=str(row[11]).strip(),
            final_order_snapshot_digest=str(row[12]).strip(),
            paper_authority_epoch=int(row[13]),
        )

    def accepted_candidate_release_binding(
        self,
        workspace_id: str,
        admission_id: str,
    ) -> AcceptedCandidateReleaseBinding | None:
        """Independently re-read the accepted candidate for gate evaluation."""

        return CandidateAdmissionAuthority(
            self._settings,
            database=self._database(),
        ).accepted_release_binding(workspace_id, admission_id)

    @staticmethod
    def _lock_workspace(
        conn: psycopg.Connection,
        workspace_id: str,
    ) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"quant_system:agent_v02_admission:{workspace_id}",),
        )
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"quant_system:agent_v02_release:{workspace_id}",),
        )

    @staticmethod
    def _candidate_schema_presence(
        conn: psycopg.Connection,
    ) -> tuple[bool, bool]:
        row = conn.execute(
            """
            SELECT
                to_regclass(
                    'quant_system.agent_v02_candidate_admissions'
                ) IS NOT NULL,
                to_regclass(
                    'quant_system.agent_v02_candidate_evidence_sets'
                ) IS NOT NULL
            """
        ).fetchone()
        if row is None:
            raise ReleaseAuthorityUnavailable(
                "candidate schema presence probe returned no row"
            )
        return bool(row[0]), bool(row[1])

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
        hermes_digest = _validate_digest(request.hermes_runtime_digest, "hermes_runtime_digest")
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
        action_digest = self._expected_action("release.open", payload, request.action_digest)
        resource_id = _validate_id(stamp_id or f"release_{uuid4().hex}", "stamp_id")
        clock = _validate_now(now or datetime.now(UTC))
        database = self._database()
        fingerprint = self._schema_fingerprint_reader(database)
        _validate_digest(fingerprint, "database_schema_fingerprint")
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
                candidate_table_exists, evidence_table_exists = (
                    self._candidate_schema_presence(conn)
                )
                if candidate_table_exists:
                    open_candidate = conn.execute(
                        f"""
                        SELECT admission_id
                        FROM {SCHEMA}.agent_v02_candidate_admissions
                        WHERE workspace_id = %s
                          AND status = 'open'
                          AND expires_at > clock_timestamp()
                        """,
                        (workspace_id,),
                    ).fetchone()
                    if open_candidate is not None:
                        raise ReleaseAuthorityConflict(
                            "release stamp requires zero open candidate admissions"
                        )
                active = conn.execute(
                    f"""
                    SELECT stamp_id
                    FROM {SCHEMA}.agent_v02_release_stamps
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                    (workspace_id,),
                ).fetchone()
                if active is not None:
                    raise ReleaseAuthorityConflict("workspace already has an active release stamp")
                candidate_evidence_is_authoritative = (
                    candidate_table_exists and evidence_table_exists
                )
                hardening_installed = self._hardening_installed(conn)
                candidate_binding: AcceptedCandidateReleaseBinding | None = None
                if (
                    self._settings.candidate_admission.enabled is True
                    and not candidate_evidence_is_authoritative
                ):
                    raise ReleaseAuthorityConflict(
                        "release stamp requires the candidate evidence schema"
                    )
                # Once migrations 016/019 exist, candidate evidence is an
                # irreversible release prerequisite. Turning the runtime
                # candidate flag back off must not resurrect the legacy
                # pre-candidate release path.
                if candidate_evidence_is_authoritative:
                    if hardening_installed:
                        candidate_binding = self._accepted_binding_on_connection(
                            conn,
                            workspace_id=workspace_id,
                            route=route,
                            platform_runtime_digest=platform_digest,
                            hqa_runtime_digest=hqa_digest,
                            hermes_runtime_digest=hermes_digest,
                            database_schema_fingerprint=fingerprint,
                            final_evidence_digest=evidence_digest,
                        )
                        accepted_candidate = (
                            None if candidate_binding is None else (candidate_binding.admission_id,)
                        )
                    else:
                        accepted_candidate = conn.execute(
                            f"""
                        SELECT candidate.admission_id
                        FROM {SCHEMA}.agent_v02_candidate_admissions
                            AS candidate
                        JOIN {SCHEMA}.agent_v02_candidate_evidence_sets
                            AS evidence_set
                          ON evidence_set.evidence_set_id =
                                candidate.evidence_set_id
                         AND evidence_set.admission_id =
                                candidate.admission_id
                         AND evidence_set.owner_user_id =
                                candidate.owner_user_id
                         AND evidence_set.workspace_id =
                                candidate.workspace_id
                         AND evidence_set.admission_digest =
                                candidate.admission_digest
                         AND evidence_set.facts_digest =
                                candidate.evidence_set_digest
                         AND evidence_set.final_order_snapshot_digest =
                                candidate.final_order_snapshot_digest
                         AND evidence_set.baseline_order_snapshot_digest =
                                candidate.baseline_order_snapshot_digest
                        WHERE candidate.owner_user_id = %s
                          AND candidate.workspace_id = %s
                          AND candidate.route = %s
                          AND candidate.status = 'accepted'
                          AND candidate.platform_runtime_digest = %s
                          AND candidate.hqa_runtime_digest = %s
                          AND candidate.hermes_runtime_digest = %s
                          AND candidate.database_schema_fingerprint = %s
                          AND candidate.final_evidence_digest = %s
                          AND candidate.evidence_set_id IS NOT NULL
                          AND candidate.evidence_set_digest IS NOT NULL
                          AND candidate.final_order_snapshot_digest =
                                candidate.baseline_order_snapshot_digest
                        ORDER BY
                            candidate.closed_at DESC,
                            candidate.admission_id DESC
                        LIMIT 1
                        """,
                            (
                                ROOT_USER_ID,
                                workspace_id,
                                route,
                                platform_digest,
                                hqa_digest,
                                hermes_digest,
                                fingerprint,
                                evidence_digest,
                            ),
                        ).fetchone()
                    if accepted_candidate is None:
                        raise ReleaseAuthorityConflict(
                            "release stamp requires the exact accepted "
                            "candidate evidence and runtime binding"
                        )
                if hardening_installed and candidate_binding is None:
                    raise ReleaseAuthorityConflict(
                        "release hardening requires an accepted candidate"
                    )
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
                    candidate_admission_id=(
                        candidate_binding.admission_id if candidate_binding is not None else None
                    ),
                    candidate_admission_digest=(
                        candidate_binding.admission_digest
                        if candidate_binding is not None
                        else None
                    ),
                    candidate_acceptance_digest=(
                        candidate_binding.acceptance_digest
                        if candidate_binding is not None
                        else None
                    ),
                    evidence_set_id=(
                        candidate_binding.evidence_set_id if candidate_binding is not None else None
                    ),
                    evidence_set_digest=(
                        candidate_binding.evidence_set_digest
                        if candidate_binding is not None
                        else None
                    ),
                    final_order_snapshot_digest=(
                        candidate_binding.final_order_snapshot_digest
                        if candidate_binding is not None
                        else None
                    ),
                    paper_authority_epoch=(
                        candidate_binding.paper_authority_epoch
                        if candidate_binding is not None
                        else None
                    ),
                )
                if candidate_binding is not None:
                    conn.execute(
                        f"""
                        SELECT {SCHEMA}.insert_agent_v02_release_stamp(
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            resource_id,
                            workspace_id,
                            route,
                            platform_digest,
                            hqa_digest,
                            hermes_digest,
                            fingerprint,
                            evidence_digest,
                            release_digest,
                            clock,
                            candidate_binding.admission_id,
                            candidate_binding.admission_digest,
                            candidate_binding.acceptance_digest,
                            candidate_binding.evidence_set_id,
                            candidate_binding.evidence_set_digest,
                            candidate_binding.final_order_snapshot_digest,
                            candidate_binding.paper_authority_epoch,
                        ),
                    )
                else:
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
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, 'active', %s
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
                release_event_data: dict[str, object] = {
                    "evidence_digest": evidence_digest,
                    "note": note,
                    "release_digest": release_digest,
                    "route": route,
                }
                if candidate_binding is not None:
                    release_event_data.update(
                        {
                            "candidate_acceptance_digest": (candidate_binding.acceptance_digest),
                            "candidate_admission_id": (candidate_binding.admission_id),
                            "evidence_set_digest": (candidate_binding.evidence_set_digest),
                            "paper_authority_epoch": (candidate_binding.paper_authority_epoch),
                        }
                    )
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace_id,
                    stamp_id=resource_id,
                    cutover_id=None,
                    event_type="release.opened",
                    event_data=release_event_data,
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
        action_digest = self._expected_action("public_cutover.open", payload, request.action_digest)
        resource_id = _validate_id(cutover_id or f"cutover_{uuid4().hex}", "cutover_id")
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
                candidate_table_exists, _evidence_table_exists = (
                    self._candidate_schema_presence(conn)
                )
                if candidate_table_exists:
                    open_candidate = conn.execute(
                        f"""
                        SELECT admission_id
                        FROM {SCHEMA}.agent_v02_candidate_admissions
                        WHERE workspace_id = %s
                          AND status = 'open'
                          AND expires_at > clock_timestamp()
                        """,
                        (workspace_id,),
                    ).fetchone()
                    if open_candidate is not None:
                        raise ReleaseAuthorityConflict(
                            "public cutover requires zero open candidate admissions"
                        )
                stamp_columns = self._stamp_columns(conn)
                row = conn.execute(
                    f"""
                    SELECT {stamp_columns}
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
                if stamp.release_digest != expected_release or stamp.route != route:
                    raise ReleaseAuthorityConflict("public cutover release binding mismatch")
                open_row = conn.execute(
                    f"""
                    SELECT cutover_id
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s AND status = 'open'
                    """,
                    (workspace_id,),
                ).fetchone()
                if open_row is not None:
                    raise ReleaseAuthorityConflict("workspace already has an open public cutover")
                cutover_digest = canonical_public_cutover_digest(
                    cutover_id=resource_id,
                    stamp_id=stamp_id,
                    workspace_id=workspace_id,
                    route=route,
                    release_digest=expected_release,
                    opened_at=clock,
                    candidate_admission_id=stamp.candidate_admission_id,
                    candidate_admission_digest=(stamp.candidate_admission_digest),
                    candidate_acceptance_digest=(stamp.candidate_acceptance_digest),
                    evidence_set_id=stamp.evidence_set_id,
                    evidence_set_digest=stamp.evidence_set_digest,
                    final_order_snapshot_digest=(stamp.final_order_snapshot_digest),
                    paper_authority_epoch=stamp.paper_authority_epoch,
                )
                if stamp.candidate_admission_id is not None:
                    conn.execute(
                        f"""
                        SELECT {SCHEMA}.insert_agent_v02_public_cutover(
                            %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            resource_id,
                            stamp_id,
                            workspace_id,
                            route,
                            expected_release,
                            cutover_digest,
                            clock,
                            stamp.candidate_admission_id,
                            stamp.candidate_admission_digest,
                            stamp.candidate_acceptance_digest,
                            stamp.evidence_set_id,
                            stamp.evidence_set_digest,
                            stamp.final_order_snapshot_digest,
                            stamp.paper_authority_epoch,
                        ),
                    )
                else:
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
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, 'open', %s
                        )
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
                cutover_event_data: dict[str, object] = {
                    "cutover_digest": cutover_digest,
                    "note": note,
                    "release_digest": expected_release,
                    "route": route,
                }
                if stamp.candidate_admission_id is not None:
                    cutover_event_data.update(
                        {
                            "candidate_acceptance_digest": (stamp.candidate_acceptance_digest),
                            "candidate_admission_id": (stamp.candidate_admission_id),
                            "paper_authority_epoch": (stamp.paper_authority_epoch),
                        }
                    )
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace_id,
                    stamp_id=stamp_id,
                    cutover_id=resource_id,
                    event_type="public_cutover.opened",
                    event_data=cutover_event_data,
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
            raise ReleaseAuthorityUnavailable("public cutover database operation failed") from exc

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
                cutover_columns = self._cutover_columns(conn)
                row = conn.execute(
                    f"""
                    SELECT {cutover_columns}
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s AND cutover_id = %s
                    """,
                    (workspace_id, cutover_id),
                ).fetchone()
                if row is None:
                    raise ReleaseAuthorityNotFound("public cutover was not found")
                cutover = _cutover_from_row(row)
                if cutover.cutover_digest != expected_digest:
                    raise ReleaseAuthorityConflict("public cutover digest binding mismatch")
                if cutover.status == "closed":
                    receipt = ReleaseAuthorityReceipt(
                        operation="public_cutover.close",
                        workspace_id=workspace_id,
                        client_action_id=action_id,
                        action_digest=action_digest,
                        resource_id=cutover_id,
                        resource_digest=expected_digest,
                        status="closed",
                        event_cursor=self._current_event_cursor_on_connection(conn, workspace_id),
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
        action_digest = self._expected_action("release.close", payload, request.action_digest)
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
                stamp_columns = self._stamp_columns(conn)
                row = conn.execute(
                    f"""
                    SELECT {stamp_columns}
                    FROM {SCHEMA}.agent_v02_release_stamps
                    WHERE workspace_id = %s AND stamp_id = %s
                    """,
                    (workspace_id, stamp_id),
                ).fetchone()
                if row is None:
                    raise ReleaseAuthorityNotFound("release stamp was not found")
                stamp = _stamp_from_row(row)
                if stamp.release_digest != expected_digest:
                    raise ReleaseAuthorityConflict("release stamp digest binding mismatch")
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
                        event_cursor=self._current_event_cursor_on_connection(conn, workspace_id),
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
            raise ReleaseAuthorityUnavailable("release rollback database operation failed") from exc

    def active_release_stamp(
        self,
        workspace_id: str,
    ) -> ReleaseStampRecord | None:
        workspace = _validate_id(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                stamp_columns = self._stamp_columns(conn)
                row = conn.execute(
                    f"""
                    SELECT {stamp_columns}
                    FROM {SCHEMA}.agent_v02_release_stamps
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                    (workspace,),
                ).fetchone()
            return _stamp_from_row(row) if row is not None else None
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable("release stamp observation failed") from exc

    def open_public_cutover(
        self,
        workspace_id: str,
    ) -> PublicCutoverRecord | None:
        workspace = _validate_id(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                cutover_columns = self._cutover_columns(conn)
                row = conn.execute(
                    f"""
                    SELECT {cutover_columns}
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s AND status = 'open'
                    """,
                    (workspace,),
                ).fetchone()
            return _cutover_from_row(row) if row is not None else None
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable("public cutover observation failed") from exc

    def list_public_cutovers(
        self,
        workspace_id: str,
        *,
        limit: int = 20,
    ) -> tuple[PublicCutoverRecord, ...]:
        """Return the open cutover first, then recent durable closed facts."""

        workspace = _validate_id(workspace_id, "workspace_id")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ReleaseAuthorityValidationError("limit must be between 1 and 100")
        try:
            with self._database().connect() as conn:
                cutover_columns = self._cutover_columns(conn)
                rows = conn.execute(
                    f"""
                    SELECT {cutover_columns}
                    FROM {SCHEMA}.agent_v02_public_cutovers
                    WHERE workspace_id = %s
                    ORDER BY
                        (status = 'open') DESC,
                        COALESCE(closed_at, opened_at) DESC,
                        cutover_id ASC
                    LIMIT %s
                    """,
                    (workspace, limit),
                ).fetchall()
            return tuple(_cutover_from_row(row) for row in rows)
        except ReleaseAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise ReleaseAuthorityUnavailable(
                "public cutover history observation failed"
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
            raise ReleaseAuthorityUnavailable("release event cursor observation failed") from exc

    def events_after(
        self,
        workspace_id: str,
        *,
        after_cursor: int,
        limit: int = 100,
    ) -> tuple[ReleaseAuthorityEvent, ...]:
        workspace = _validate_id(workspace_id, "workspace_id")
        if isinstance(after_cursor, bool) or not isinstance(after_cursor, int) or after_cursor < 0:
            raise ReleaseAuthorityValidationError("after_cursor must be a nonnegative integer")
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
            raise ReleaseAuthorityUnavailable("release event observation failed") from exc
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
