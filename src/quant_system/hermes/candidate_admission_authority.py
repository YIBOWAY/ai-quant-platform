"""Durable, owner-local candidate admission for Agent v0.2.

The candidate window is a narrowly scoped bootstrap authority used to collect
the real `/hermes` evidence required by the final release stamp.  It never
opens the public cutover and never grants trading authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
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

CANDIDATE_ADMISSION_SCHEMA_VERSION = 1
CANDIDATE_ROUTE = "/hermes"
CandidateStatus = Literal["open", "accepted", "revoked", "expired"]

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_NONTERMINAL_COMMAND_STATES = (
    "queued",
    "leased",
    "delivered",
    "outcome_unknown",
)
_CANDIDATE_TRIGGER_SIGNATURES = {
    (
        "trg_agent_v02_candidate_admission_guard",
        "agent_v02_candidate_admissions",
        27,
        "A",
        "quant_system",
        "guard_agent_v02_candidate_transition",
        True,
        "",
    ),
    (
        "trg_agent_v02_candidate_events_append_only",
        "agent_v02_candidate_events",
        27,
        "A",
        "quant_system",
        "reject_agent_v02_candidate_append_only",
        True,
        "",
    ),
    (
        "trg_agent_v02_candidate_actions_append_only",
        "agent_v02_candidate_actions",
        27,
        "A",
        "quant_system",
        "reject_agent_v02_candidate_append_only",
        True,
        "",
    ),
    (
        "trg_hermes_session_candidate_binding",
        "hermes_workspace_sessions",
        23,
        "A",
        "quant_system",
        "bind_agent_v02_candidate_session",
        True,
        "",
    ),
    (
        "trg_hermes_command_candidate_binding",
        "hermes_commands",
        23,
        "A",
        "quant_system",
        "bind_agent_v02_candidate_command",
        True,
        "",
    ),
}
_CANDIDATE_FUNCTION_SIGNATURES = {
    (
        "bind_agent_v02_candidate_command",
        "quant_migrator",
        "plpgsql",
        False,
        "v",
    ),
    (
        "bind_agent_v02_candidate_session",
        "quant_migrator",
        "plpgsql",
        False,
        "v",
    ),
    (
        "guard_agent_v02_candidate_transition",
        "quant_migrator",
        "plpgsql",
        False,
        "v",
    ),
    (
        "reject_agent_v02_candidate_append_only",
        "quant_migrator",
        "plpgsql",
        False,
        "v",
    ),
}
_CANDIDATE_FUNCTION_SOURCE_SHA256 = {
    "bind_agent_v02_candidate_command": (
        "ac05c8d18b74f389ce35f0dfd0dc157e8fe40cd5db4bc065ac03e1823962fbfd"
    ),
    "bind_agent_v02_candidate_session": (
        "fb0cc0d59493faa7bbf0153a07aa5e4fc30b7eb30de61f999db7912d2ad2fc85"
    ),
    "guard_agent_v02_candidate_transition": (
        "71bf68ecebc77e6adb74db5105d80b67133f28060f06f9cafb2ba1e5a3033972"
    ),
    "reject_agent_v02_candidate_append_only": (
        "9e6e78dc09a82f7826e1ed159f1932881d869a7da81c5bf86f31e1174aa7e995"
    ),
}

_ADMISSION_COLUMNS = """
    admission_id,
    workspace_id,
    route,
    platform_runtime_digest,
    hqa_runtime_digest,
    hermes_runtime_digest,
    database_schema_fingerprint,
    preflight_evidence_digest,
    baseline_order_snapshot_digest,
    admission_digest,
    status,
    opened_at,
    expires_at,
    closed_at,
    close_reason,
    final_evidence_digest,
    acceptance_digest,
    evidence_set_id,
    evidence_set_digest,
    final_order_snapshot_digest
"""


class CandidateAdmissionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CandidateAdmissionUnavailable(CandidateAdmissionError):
    def __init__(self, message: str) -> None:
        super().__init__("candidate_admission_unavailable", message)


class CandidateAdmissionValidationError(CandidateAdmissionError):
    def __init__(self, message: str) -> None:
        super().__init__("candidate_admission_validation", message)


class CandidateAdmissionConflict(CandidateAdmissionError):
    def __init__(self, message: str) -> None:
        super().__init__("candidate_admission_conflict", message)


class CandidateAdmissionNotFound(CandidateAdmissionError):
    def __init__(self, message: str) -> None:
        super().__init__("candidate_admission_not_found", message)


def _identifier(value: str, field: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise CandidateAdmissionValidationError(f"{field} must be a bounded identifier")
    return value


def _digest(value: str, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise CandidateAdmissionValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _note(value: str, field: str) -> str:
    if type(value) is not str:
        raise CandidateAdmissionValidationError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise CandidateAdmissionValidationError(
            f"{field} must be nonempty and no longer than 500 characters"
        )
    return normalized


def _canonical_timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CandidateAdmissionValidationError("authority timestamp must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical_digest(payload: Mapping[str, object]) -> str:
    content = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def canonical_candidate_action_digest(
    operation: str,
    payload: Mapping[str, object],
) -> str:
    if operation not in {
        "candidate.open",
        "candidate.accept",
        "candidate.revoke",
    }:
        raise CandidateAdmissionValidationError("unsupported candidate operation")
    return _canonical_digest({"operation": operation, "payload": dict(payload)})


def canonical_candidate_admission_digest(
    *,
    admission_id: str,
    workspace_id: str,
    route: str,
    platform_runtime_digest: str,
    hqa_runtime_digest: str,
    hermes_runtime_digest: str,
    database_schema_fingerprint: str,
    preflight_evidence_digest: str,
    baseline_order_snapshot_digest: str,
    opened_at: datetime,
    expires_at: datetime,
) -> str:
    return _canonical_digest(
        {
            "admission_id": admission_id,
            "baseline_order_snapshot_digest": baseline_order_snapshot_digest,
            "database_schema_fingerprint": database_schema_fingerprint,
            "expires_at": _canonical_timestamp(expires_at),
            "hermes_runtime_digest": hermes_runtime_digest,
            "hqa_runtime_digest": hqa_runtime_digest,
            "opened_at": _canonical_timestamp(opened_at),
            "platform_runtime_digest": platform_runtime_digest,
            "preflight_evidence_digest": preflight_evidence_digest,
            "route": route,
            "workspace_id": workspace_id,
        }
    )


def canonical_candidate_acceptance_digest(
    *,
    admission_digest: str,
    final_evidence_digest: str,
    evidence_set_id: str,
    evidence_set_digest: str,
    final_order_snapshot_digest: str,
    closed_at: datetime,
    paper_authority_epoch: int | None = None,
) -> str:
    if paper_authority_epoch is not None and (
        isinstance(paper_authority_epoch, bool)
        or not isinstance(paper_authority_epoch, int)
        or paper_authority_epoch <= 0
    ):
        raise CandidateAdmissionValidationError("paper_authority_epoch must be a positive integer")
    payload: dict[str, object] = {
        "admission_digest": admission_digest,
        "closed_at": _canonical_timestamp(closed_at),
        "evidence_set_digest": evidence_set_digest,
        "evidence_set_id": evidence_set_id,
        "final_evidence_digest": final_evidence_digest,
        "final_order_snapshot_digest": final_order_snapshot_digest,
        "status": "accepted",
    }
    if paper_authority_epoch is not None:
        payload["paper_authority_epoch"] = paper_authority_epoch
    return _canonical_digest(payload)


@dataclass(frozen=True)
class OpenCandidateAdmissionRequest:
    workspace_id: str
    route: str
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str
    database_schema_fingerprint: str
    preflight_evidence_digest: str
    baseline_order_snapshot_digest: str
    ttl_seconds: int
    note: str
    client_action_id: str
    action_digest: str


@dataclass(frozen=True)
class AcceptCandidateAdmissionRequest:
    workspace_id: str
    admission_id: str
    expected_admission_digest: str
    final_evidence_digest: str
    evidence_set_id: str
    evidence_set_digest: str
    final_order_snapshot_digest: str
    note: str
    client_action_id: str
    action_digest: str


@dataclass(frozen=True)
class RevokeCandidateAdmissionRequest:
    workspace_id: str
    admission_id: str
    expected_admission_digest: str
    reason: str
    client_action_id: str
    action_digest: str


@dataclass(frozen=True)
class CandidateAdmissionRecord:
    admission_id: str
    workspace_id: str
    route: str
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str
    database_schema_fingerprint: str
    preflight_evidence_digest: str
    baseline_order_snapshot_digest: str
    admission_digest: str
    status: CandidateStatus
    opened_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    close_reason: str | None
    final_evidence_digest: str | None
    acceptance_digest: str | None
    evidence_set_id: str | None
    evidence_set_digest: str | None
    final_order_snapshot_digest: str | None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "acceptance_digest": self.acceptance_digest,
            "admission_digest": self.admission_digest,
            "admission_id": self.admission_id,
            "baseline_order_snapshot_digest": (self.baseline_order_snapshot_digest),
            "closed_at": (
                _canonical_timestamp(self.closed_at) if self.closed_at is not None else None
            ),
            "close_reason": self.close_reason,
            "database_schema_fingerprint": (self.database_schema_fingerprint),
            "expires_at": _canonical_timestamp(self.expires_at),
            "evidence_set_digest": self.evidence_set_digest,
            "evidence_set_id": self.evidence_set_id,
            "final_evidence_digest": self.final_evidence_digest,
            "final_order_snapshot_digest": (self.final_order_snapshot_digest),
            "hermes_runtime_digest": self.hermes_runtime_digest,
            "hqa_runtime_digest": self.hqa_runtime_digest,
            "opened_at": _canonical_timestamp(self.opened_at),
            "platform_runtime_digest": self.platform_runtime_digest,
            "preflight_evidence_digest": self.preflight_evidence_digest,
            "route": self.route,
            "status": self.status,
            "workspace_id": self.workspace_id,
        }


@dataclass(frozen=True)
class AcceptedCandidateReleaseBinding:
    """Exact accepted candidate/evidence fact re-read for the release gate."""

    admission_id: str
    workspace_id: str
    route: str
    admission_digest: str
    acceptance_digest: str
    platform_runtime_digest: str
    hqa_runtime_digest: str
    hermes_runtime_digest: str
    database_schema_fingerprint: str
    final_evidence_digest: str
    evidence_set_id: str
    evidence_set_digest: str
    final_order_snapshot_digest: str
    paper_authority_epoch: int


@dataclass(frozen=True)
class CandidateAdmissionReceipt:
    operation: str
    workspace_id: str
    client_action_id: str
    action_digest: str
    admission_id: str
    admission_digest: str
    status: str
    event_cursor: int
    occurred_at: datetime
    acceptance_digest: str | None = None
    evidence_set_id: str | None = None
    evidence_set_digest: str | None = None
    idempotent_replay: bool = False

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "acceptance_digest": self.acceptance_digest,
            "action_digest": self.action_digest,
            "admission_digest": self.admission_digest,
            "admission_id": self.admission_id,
            "client_action_id": self.client_action_id,
            "event_cursor": self.event_cursor,
            "evidence_set_digest": self.evidence_set_digest,
            "evidence_set_id": self.evidence_set_id,
            "idempotent_replay": False,
            "occurred_at": _canonical_timestamp(self.occurred_at),
            "operation": self.operation,
            "status": self.status,
            "workspace_id": self.workspace_id,
        }


def _record_from_row(row: tuple[object, ...]) -> CandidateAdmissionRecord:
    return CandidateAdmissionRecord(
        admission_id=str(row[0]),
        workspace_id=str(row[1]),
        route=str(row[2]),
        platform_runtime_digest=str(row[3]).strip(),
        hqa_runtime_digest=str(row[4]).strip(),
        hermes_runtime_digest=str(row[5]).strip(),
        database_schema_fingerprint=str(row[6]).strip(),
        preflight_evidence_digest=str(row[7]).strip(),
        baseline_order_snapshot_digest=str(row[8]).strip(),
        admission_digest=str(row[9]).strip(),
        status=str(row[10]),  # type: ignore[arg-type]
        opened_at=row[11],  # type: ignore[arg-type]
        expires_at=row[12],  # type: ignore[arg-type]
        closed_at=row[13],  # type: ignore[arg-type]
        close_reason=None if row[14] is None else str(row[14]),
        final_evidence_digest=(None if row[15] is None else str(row[15]).strip()),
        acceptance_digest=(None if row[16] is None else str(row[16]).strip()),
        evidence_set_id=(None if row[17] is None else str(row[17])),
        evidence_set_digest=(None if row[18] is None else str(row[18]).strip()),
        final_order_snapshot_digest=(None if row[19] is None else str(row[19]).strip()),
    )


def _receipt_from_payload(
    payload: Mapping[str, object],
    *,
    replay: bool,
) -> CandidateAdmissionReceipt:
    occurred = payload.get("occurred_at")
    if not isinstance(occurred, str):
        raise CandidateAdmissionUnavailable("stored candidate action receipt is invalid")
    try:
        parsed = datetime.fromisoformat(
            occurred[:-1] + "+00:00" if occurred.endswith("Z") else occurred
        ).astimezone(UTC)
        return CandidateAdmissionReceipt(
            operation=str(payload["operation"]),
            workspace_id=str(payload["workspace_id"]),
            client_action_id=str(payload["client_action_id"]),
            action_digest=str(payload["action_digest"]),
            admission_id=str(payload["admission_id"]),
            admission_digest=str(payload["admission_digest"]),
            status=str(payload["status"]),
            event_cursor=int(payload["event_cursor"]),
            occurred_at=parsed,
            acceptance_digest=(
                None
                if payload.get("acceptance_digest") is None
                else str(payload["acceptance_digest"])
            ),
            evidence_set_id=(
                None if payload.get("evidence_set_id") is None else str(payload["evidence_set_id"])
            ),
            evidence_set_digest=(
                None
                if payload.get("evidence_set_digest") is None
                else str(payload["evidence_set_digest"])
            ),
            idempotent_replay=replay,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateAdmissionUnavailable("stored candidate action receipt is invalid") from exc


def candidate_admission_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    tables = (
        "agent_v02_candidate_admission_meta",
        "agent_v02_candidate_admissions",
        "agent_v02_candidate_events",
        "agent_v02_candidate_actions",
    )
    relation = conn.execute(
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
    if relation != (True,):
        return False
    version = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_candidate_admission_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if version != (CANDIDATE_ADMISSION_SCHEMA_VERSION,):
        return False
    columns = conn.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND (
            (table_name = 'hermes_commands'
             AND column_name = 'candidate_admission_id')
            OR
            (table_name = 'hermes_workspace_sessions'
             AND column_name = 'candidate_admission_id')
          )
        """,
        (SCHEMA,),
    ).fetchall()
    if {(str(row[0]), str(row[1])) for row in columns} != {
        ("hermes_commands", "candidate_admission_id"),
        ("hermes_workspace_sessions", "candidate_admission_id"),
    }:
        return False
    triggers = conn.execute(
        """
        SELECT
            trigger.tgname,
            relation.relname,
            trigger.tgtype,
            trigger.tgenabled,
            function_namespace.nspname,
            procedure.proname,
            trigger.tgqual IS NULL,
            trigger.tgattr::text
        FROM pg_trigger trigger
        JOIN pg_class relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
        JOIN pg_proc procedure ON procedure.oid = trigger.tgfoid
        JOIN pg_namespace function_namespace
          ON function_namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = %s
          AND trigger.tgname = ANY(%s)
          AND NOT trigger.tgisinternal
        """,
        (
            SCHEMA,
            [
                "trg_agent_v02_candidate_admission_guard",
                "trg_agent_v02_candidate_events_append_only",
                "trg_agent_v02_candidate_actions_append_only",
                "trg_hermes_session_candidate_binding",
                "trg_hermes_command_candidate_binding",
            ],
        ),
    ).fetchall()
    trigger_signatures = {
        (
            str(row[0]),
            str(row[1]),
            int(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
            bool(row[6]),
            str(row[7]),
        )
        for row in triggers
    }
    if trigger_signatures != _CANDIDATE_TRIGGER_SIGNATURES:
        return False
    function_rows = conn.execute(
        """
        SELECT
            procedure.proname,
            pg_get_userbyid(procedure.proowner),
            language.lanname,
            procedure.prosecdef,
            procedure.provolatile,
            procedure.prosrc
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace
          ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language
          ON language.oid = procedure.prolang
        WHERE namespace.nspname = %s
          AND procedure.proname = ANY(%s)
          AND procedure.pronargs = 0
          AND procedure.prorettype = 'trigger'::regtype
        """,
        (
            SCHEMA,
            [
                "bind_agent_v02_candidate_session",
                "bind_agent_v02_candidate_command",
                "guard_agent_v02_candidate_transition",
                "reject_agent_v02_candidate_append_only",
            ],
        ),
    ).fetchall()
    function_signatures = {
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            bool(row[3]),
            str(row[4]),
        )
        for row in function_rows
    }
    if function_signatures != _CANDIDATE_FUNCTION_SIGNATURES:
        return False
    source_digests = {
        str(row[0]): hashlib.sha256(str(row[5]).encode("utf-8")).hexdigest()
        for row in function_rows
    }
    return source_digests == _CANDIDATE_FUNCTION_SOURCE_SHA256


def candidate_admission_schema_ready(settings: Settings) -> bool:
    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            return candidate_admission_schema_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return False


def candidate_admission_runtime_security_is_ready(
    settings: Settings,
) -> bool:
    """Require the candidate authority under the constrained runtime login."""

    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            if not candidate_admission_schema_is_ready_on_connection(conn):
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
            if principal is None or not all(bool(item) for item in principal):
                return False
            tables = (
                "agent_v02_candidate_admissions",
                "agent_v02_candidate_events",
                "agent_v02_candidate_actions",
            )
            relations = conn.execute(
                """
                SELECT
                    relation.relname,
                    relation.relrowsecurity,
                    relation.relforcerowsecurity,
                    pg_get_userbyid(relation.relowner)
                FROM pg_class relation
                JOIN pg_namespace namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = %s
                  AND relation.relname = ANY(%s)
                """,
                (SCHEMA, list(tables)),
            ).fetchall()
            if {
                (
                    str(name),
                    bool(row_security),
                    bool(force_security),
                    str(owner),
                )
                for name, row_security, force_security, owner in relations
            } != {(name, True, True, "quant_migrator") for name in tables}:
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
                        'SELECT,INSERT'
                    ),
                    NOT has_table_privilege(
                        session_user,
                        %s,
                        'UPDATE,DELETE,TRUNCATE'
                    ),
                    has_table_privilege(
                        session_user,
                        %s,
                        'SELECT,INSERT'
                    ),
                    NOT has_table_privilege(
                        session_user,
                        %s,
                        'UPDATE,DELETE,TRUNCATE'
                    )
                """,
                (
                    f"{SCHEMA}.agent_v02_candidate_admissions",
                    f"{SCHEMA}.agent_v02_candidate_admissions",
                    f"{SCHEMA}.agent_v02_candidate_events",
                    f"{SCHEMA}.agent_v02_candidate_events",
                    f"{SCHEMA}.agent_v02_candidate_actions",
                    f"{SCHEMA}.agent_v02_candidate_actions",
                ),
            ).fetchone()
            return privileges == (True, True, True, True, True, True)
    except (DatabaseUnavailable, psycopg.Error):
        return False


class CandidateAdmissionAuthority:
    """PostgreSQL authority for the one local candidate window."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        schema_fingerprint_reader=schema_fingerprint,
    ) -> None:
        self._settings = settings
        self._database_override = database
        self._schema_fingerprint_reader = schema_fingerprint_reader

    def _database(self) -> Database:
        database = self._database_override or get_database(self._settings)
        if database is None:
            raise CandidateAdmissionUnavailable("candidate admission requires PostgreSQL")
        return database

    @staticmethod
    def _lock(conn: psycopg.Connection, workspace_id: str) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"quant_system:agent_v02_admission:{workspace_id}",),
        )
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"agent-v02-candidate:{workspace_id}",),
        )

    @staticmethod
    def _clock(conn: psycopg.Connection) -> datetime:
        row = conn.execute("SELECT clock_timestamp()").fetchone()
        if row is None or not isinstance(row[0], datetime):
            raise CandidateAdmissionUnavailable("PostgreSQL candidate clock is unavailable")
        return row[0].astimezone(UTC)

    @staticmethod
    def _action_replay(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        client_action_id: str,
        operation: str,
        action_digest: str,
    ) -> CandidateAdmissionReceipt | None:
        row = conn.execute(
            f"""
            SELECT operation, action_digest, receipt
            FROM {SCHEMA}.agent_v02_candidate_actions
            WHERE workspace_id = %s AND client_action_id = %s
            """,
            (workspace_id, client_action_id),
        ).fetchone()
        if row is None:
            return None
        if str(row[0]) != operation or str(row[1]).strip() != action_digest:
            raise CandidateAdmissionConflict(
                "client action id already froze a different candidate action"
            )
        if not isinstance(row[2], Mapping):
            raise CandidateAdmissionUnavailable("stored candidate action receipt is invalid")
        return _receipt_from_payload(row[2], replay=True)

    @staticmethod
    def _store_action(
        conn: psycopg.Connection,
        receipt: CandidateAdmissionReceipt,
    ) -> None:
        conn.execute(
            f"""
            INSERT INTO {SCHEMA}.agent_v02_candidate_actions (
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
                json.dumps(
                    receipt.to_storage_dict(),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                receipt.occurred_at,
            ),
        )

    @staticmethod
    def _append_event(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        admission_id: str,
        event_type: str,
        event_data: Mapping[str, object],
        occurred_at: datetime,
    ) -> int:
        row = conn.execute(
            f"""
            INSERT INTO {SCHEMA}.agent_v02_candidate_events (
                event_id,
                owner_user_id,
                workspace_id,
                admission_id,
                event_type,
                event_data,
                occurred_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING event_cursor
            """,
            (
                f"evt_{uuid4().hex}",
                ROOT_USER_ID,
                workspace_id,
                admission_id,
                event_type,
                json.dumps(
                    dict(event_data),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                occurred_at,
            ),
        ).fetchone()
        if row is None:
            raise CandidateAdmissionUnavailable("candidate event insert returned no cursor")
        return int(row[0])

    @staticmethod
    def _expire_if_needed(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        observed_at: datetime,
    ) -> None:
        rows = conn.execute(
            f"""
            UPDATE {SCHEMA}.agent_v02_candidate_admissions
            SET status = 'expired',
                closed_at = %s,
                close_reason = 'postgresql_ttl_elapsed'
            WHERE workspace_id = %s
              AND status = 'open'
              AND expires_at <= %s
            RETURNING admission_id, admission_digest
            """,
            (observed_at, workspace_id, observed_at),
        ).fetchall()
        for admission_id, admission_digest in rows:
            CandidateAdmissionAuthority._append_event(
                conn,
                workspace_id=workspace_id,
                admission_id=str(admission_id),
                event_type="candidate.expired",
                event_data={"admission_digest": str(admission_digest).strip()},
                occurred_at=observed_at,
            )

    def current(
        self,
        workspace_id: str,
        *,
        include_expired_open: bool = False,
    ) -> CandidateAdmissionRecord | None:
        workspace = _identifier(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                clause = (
                    ""
                    if include_expired_open
                    else ("AND (status <> 'open' OR expires_at > clock_timestamp())")
                )
                row = conn.execute(
                    f"""
                    SELECT {_ADMISSION_COLUMNS}
                    FROM {SCHEMA}.agent_v02_candidate_admissions
                    WHERE workspace_id = %s
                      {clause}
                    ORDER BY
                        (status = 'open') DESC,
                        opened_at DESC,
                        admission_id DESC
                    LIMIT 1
                    """,
                    (workspace,),
                ).fetchone()
                return None if row is None else _record_from_row(row)
        except CandidateAdmissionError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable("candidate admission read failed") from exc

    def active(self, workspace_id: str) -> CandidateAdmissionRecord | None:
        workspace = _identifier(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_ADMISSION_COLUMNS}
                    FROM {SCHEMA}.agent_v02_candidate_admissions
                    WHERE workspace_id = %s
                      AND status = 'open'
                      AND expires_at > clock_timestamp()
                    LIMIT 1
                    """,
                    (workspace,),
                ).fetchone()
                return None if row is None else _record_from_row(row)
        except CandidateAdmissionError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable("candidate admission read failed") from exc

    def latest_accepted(
        self,
        workspace_id: str,
    ) -> CandidateAdmissionRecord | None:
        workspace = _identifier(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                row = conn.execute(
                    f"""
                    SELECT {_ADMISSION_COLUMNS}
                    FROM {SCHEMA}.agent_v02_candidate_admissions
                    WHERE workspace_id = %s
                      AND status = 'accepted'
                    ORDER BY closed_at DESC, admission_id DESC
                    LIMIT 1
                    """,
                    (workspace,),
                ).fetchone()
                return None if row is None else _record_from_row(row)
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable("candidate acceptance read failed") from exc

    def accepted_release_binding(
        self,
        workspace_id: str,
        admission_id: str,
    ) -> AcceptedCandidateReleaseBinding | None:
        """Re-read one still-current accepted candidate and evidence binding.

        A paper-authority mutation after evidence/acceptance advances the
        owner/workspace epoch, so this query returns ``None`` without mutating
        the historical acceptance row.
        """

        workspace = _identifier(workspace_id, "workspace_id")
        candidate_id = _identifier(admission_id, "admission_id")
        try:
            with self._database().connect() as conn:
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
                     AND evidence_set.paper_authority_epoch =
                            candidate.paper_authority_epoch
                    JOIN {SCHEMA}.agent_v02_paper_authority_epochs
                        AS paper_epoch
                      ON paper_epoch.owner_user_id =
                            candidate.owner_user_id
                     AND paper_epoch.workspace_id =
                            candidate.workspace_id
                     AND paper_epoch.authority_epoch =
                            candidate.paper_authority_epoch
                    JOIN {SCHEMA}.agent_v02_paper_authority_owner_epochs
                        AS owner_epoch
                      ON owner_epoch.owner_user_id =
                            candidate.owner_user_id
                     AND owner_epoch.authority_epoch =
                            candidate.paper_authority_epoch
                    WHERE candidate.owner_user_id = %s
                      AND candidate.workspace_id = %s
                      AND candidate.admission_id = %s
                      AND candidate.route = %s
                      AND candidate.status = 'accepted'
                      AND candidate.acceptance_digest IS NOT NULL
                      AND candidate.final_evidence_digest IS NOT NULL
                      AND candidate.final_order_snapshot_digest =
                            candidate.baseline_order_snapshot_digest
                    """,
                    (
                        ROOT_USER_ID,
                        workspace,
                        candidate_id,
                        CANDIDATE_ROUTE,
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
        except CandidateAdmissionError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable(
                "accepted candidate release binding read failed"
            ) from exc

    def open(
        self,
        request: OpenCandidateAdmissionRequest,
        *,
        admission_id: str | None = None,
    ) -> CandidateAdmissionReceipt:
        if self._settings.candidate_admission.enabled is not True:
            raise CandidateAdmissionValidationError("candidate admission setting is disabled")
        workspace = _identifier(request.workspace_id, "workspace_id")
        if request.route != CANDIDATE_ROUTE:
            raise CandidateAdmissionValidationError("route must be exactly /hermes")
        platform = _digest(request.platform_runtime_digest, "platform_runtime_digest")
        hqa = _digest(request.hqa_runtime_digest, "hqa_runtime_digest")
        hermes = _digest(request.hermes_runtime_digest, "hermes_runtime_digest")
        schema = _digest(
            request.database_schema_fingerprint,
            "database_schema_fingerprint",
        )
        preflight = _digest(
            request.preflight_evidence_digest,
            "preflight_evidence_digest",
        )
        orders = _digest(
            request.baseline_order_snapshot_digest,
            "baseline_order_snapshot_digest",
        )
        if (
            isinstance(request.ttl_seconds, bool)
            or not isinstance(request.ttl_seconds, int)
            or request.ttl_seconds < 1
            or request.ttl_seconds > 1800
            or request.ttl_seconds != self._settings.candidate_admission.ttl_seconds
        ):
            raise CandidateAdmissionValidationError(
                "ttl_seconds must equal the configured value in [1, 1800]"
            )
        note = _note(request.note, "note")
        action_id = _identifier(request.client_action_id, "client_action_id")
        payload = {
            "baseline_order_snapshot_digest": orders,
            "database_schema_fingerprint": schema,
            "hermes_runtime_digest": hermes,
            "hqa_runtime_digest": hqa,
            "note": note,
            "platform_runtime_digest": platform,
            "preflight_evidence_digest": preflight,
            "route": CANDIDATE_ROUTE,
            "ttl_seconds": request.ttl_seconds,
            "workspace_id": workspace,
        }
        expected_action = canonical_candidate_action_digest("candidate.open", payload)
        if _digest(request.action_digest, "action_digest") != expected_action:
            raise CandidateAdmissionValidationError(
                "action_digest does not match the canonical request"
            )
        resource_id = _identifier(
            admission_id or f"candidate_{uuid4().hex}",
            "admission_id",
        )
        database = self._database()
        observed_schema = self._schema_fingerprint_reader(database)
        if observed_schema != schema:
            raise CandidateAdmissionConflict(
                "candidate database schema fingerprint does not match the live authority"
            )
        try:
            with database.connect() as conn, conn.transaction():
                if not candidate_admission_schema_is_ready_on_connection(conn):
                    raise CandidateAdmissionUnavailable("candidate admission schema is not ready")
                self._lock(conn, workspace)
                clock = self._clock(conn)
                self._expire_if_needed(
                    conn,
                    workspace_id=workspace,
                    observed_at=clock,
                )
                replay = self._action_replay(
                    conn,
                    workspace_id=workspace,
                    client_action_id=action_id,
                    operation="candidate.open",
                    action_digest=expected_action,
                )
                if replay is not None:
                    return replay
                if (
                    conn.execute(
                        f"""
                    SELECT 1
                    FROM {SCHEMA}.agent_v02_candidate_admissions
                    WHERE workspace_id = %s AND status = 'open'
                    """,
                        (workspace,),
                    ).fetchone()
                    is not None
                ):
                    raise CandidateAdmissionConflict(
                        "workspace already has an open candidate admission"
                    )
                if (
                    conn.execute(
                        f"""
                    SELECT 1
                    FROM {SCHEMA}.agent_v02_release_stamps AS stamp
                    JOIN {SCHEMA}.agent_v02_public_cutovers AS cutover
                      ON cutover.stamp_id = stamp.stamp_id
                     AND cutover.status = 'open'
                    WHERE stamp.workspace_id = %s
                      AND stamp.status = 'active'
                    """,
                        (workspace,),
                    ).fetchone()
                    is not None
                ):
                    raise CandidateAdmissionConflict("public release is already open")
                if (
                    conn.execute(
                        f"""
                    SELECT 1
                    FROM {SCHEMA}.agent_v02_connector_workers
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                        (workspace,),
                    ).fetchone()
                    is not None
                ):
                    raise CandidateAdmissionConflict(
                        "candidate admission requires the connector to be stopped"
                    )
                nonterminal = conn.execute(
                    f"""
                    SELECT count(*)
                    FROM {SCHEMA}.hermes_commands
                    WHERE owner_user_id = %s
                      AND state = ANY(%s)
                    """,
                    (ROOT_USER_ID, list(_NONTERMINAL_COMMAND_STATES)),
                ).fetchone()
                if nonterminal is None or int(nonterminal[0]) != 0:
                    raise CandidateAdmissionConflict(
                        "candidate admission requires zero nonterminal commands"
                    )
                expires = conn.execute(
                    "SELECT %s + (%s * interval '1 second')",
                    (clock, request.ttl_seconds),
                ).fetchone()
                if expires is None or not isinstance(expires[0], datetime):
                    raise CandidateAdmissionUnavailable("candidate expiry derivation failed")
                expires_at = expires[0].astimezone(UTC)
                admission_digest = canonical_candidate_admission_digest(
                    admission_id=resource_id,
                    workspace_id=workspace,
                    route=CANDIDATE_ROUTE,
                    platform_runtime_digest=platform,
                    hqa_runtime_digest=hqa,
                    hermes_runtime_digest=hermes,
                    database_schema_fingerprint=schema,
                    preflight_evidence_digest=preflight,
                    baseline_order_snapshot_digest=orders,
                    opened_at=clock,
                    expires_at=expires_at,
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_candidate_admissions (
                        admission_id,
                        owner_user_id,
                        workspace_id,
                        route,
                        platform_runtime_digest,
                        hqa_runtime_digest,
                        hermes_runtime_digest,
                        database_schema_fingerprint,
                        preflight_evidence_digest,
                        baseline_order_snapshot_digest,
                        admission_digest,
                        status,
                        opened_at,
                        expires_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, 'open', %s, %s
                    )
                    """,
                    (
                        resource_id,
                        ROOT_USER_ID,
                        workspace,
                        CANDIDATE_ROUTE,
                        platform,
                        hqa,
                        hermes,
                        schema,
                        preflight,
                        orders,
                        admission_digest,
                        clock,
                        expires_at,
                    ),
                )
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace,
                    admission_id=resource_id,
                    event_type="candidate.opened",
                    event_data={
                        "admission_digest": admission_digest,
                        "expires_at": _canonical_timestamp(expires_at),
                        "note": note,
                    },
                    occurred_at=clock,
                )
                receipt = CandidateAdmissionReceipt(
                    operation="candidate.open",
                    workspace_id=workspace,
                    client_action_id=action_id,
                    action_digest=expected_action,
                    admission_id=resource_id,
                    admission_digest=admission_digest,
                    status="open",
                    event_cursor=cursor,
                    occurred_at=clock,
                )
                self._store_action(conn, receipt)
                return receipt
        except CandidateAdmissionError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise CandidateAdmissionConflict(
                "candidate identity or active-workspace constraint conflicted"
            ) from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable(
                "candidate admission database operation failed"
            ) from exc

    def accept(
        self,
        request: AcceptCandidateAdmissionRequest,
    ) -> CandidateAdmissionReceipt:
        workspace = _identifier(request.workspace_id, "workspace_id")
        admission_id = _identifier(request.admission_id, "admission_id")
        expected_admission = _digest(
            request.expected_admission_digest,
            "expected_admission_digest",
        )
        final_evidence = _digest(
            request.final_evidence_digest,
            "final_evidence_digest",
        )
        evidence_set_id = _identifier(
            request.evidence_set_id,
            "evidence_set_id",
        )
        evidence_set_digest = _digest(
            request.evidence_set_digest,
            "evidence_set_digest",
        )
        final_order_snapshot_digest = _digest(
            request.final_order_snapshot_digest,
            "final_order_snapshot_digest",
        )
        note = _note(request.note, "note")
        action_id = _identifier(request.client_action_id, "client_action_id")
        payload = {
            "admission_id": admission_id,
            "expected_admission_digest": expected_admission,
            "evidence_set_digest": evidence_set_digest,
            "evidence_set_id": evidence_set_id,
            "final_evidence_digest": final_evidence,
            "final_order_snapshot_digest": (final_order_snapshot_digest),
            "note": note,
            "workspace_id": workspace,
        }
        expected_action = canonical_candidate_action_digest("candidate.accept", payload)
        if _digest(request.action_digest, "action_digest") != expected_action:
            raise CandidateAdmissionValidationError(
                "action_digest does not match the canonical request"
            )
        try:
            with self._database().connect() as conn, conn.transaction():
                self._lock(conn, workspace)
                clock = self._clock(conn)
                self._expire_if_needed(
                    conn,
                    workspace_id=workspace,
                    observed_at=clock,
                )
                replay = self._action_replay(
                    conn,
                    workspace_id=workspace,
                    client_action_id=action_id,
                    operation="candidate.accept",
                    action_digest=expected_action,
                )
                if replay is not None:
                    return replay
                row = conn.execute(
                    f"""
                    SELECT {_ADMISSION_COLUMNS}
                    FROM {SCHEMA}.agent_v02_candidate_admissions
                    WHERE workspace_id = %s
                      AND admission_id = %s
                      AND status = 'open'
                      AND expires_at > %s
                    FOR UPDATE
                    """,
                    (workspace, admission_id, clock),
                ).fetchone()
                if row is None:
                    raise CandidateAdmissionConflict("candidate admission is not open")
                record = _record_from_row(row)
                if record.admission_digest != expected_admission:
                    raise CandidateAdmissionConflict("candidate admission digest mismatch")
                if (
                    conn.execute(
                        f"""
                    SELECT 1
                    FROM {SCHEMA}.agent_v02_connector_workers
                    WHERE workspace_id = %s AND status = 'active'
                    """,
                        (workspace,),
                    ).fetchone()
                    is not None
                ):
                    raise CandidateAdmissionConflict(
                        "candidate acceptance requires the connector to be stopped"
                    )
                nonterminal = conn.execute(
                    f"""
                    SELECT count(*)
                    FROM {SCHEMA}.hermes_commands
                    WHERE candidate_admission_id = %s
                      AND state = ANY(%s)
                    """,
                    (admission_id, list(_NONTERMINAL_COMMAND_STATES)),
                ).fetchone()
                if nonterminal is None or int(nonterminal[0]) != 0:
                    raise CandidateAdmissionConflict(
                        "candidate acceptance requires zero nonterminal candidate commands"
                    )
                verified_evidence = conn.execute(
                    f"""
                    SELECT
                        (
                            to_jsonb(evidence_set)
                            ->> 'paper_authority_epoch'
                        )::bigint
                    FROM {SCHEMA}.agent_v02_candidate_evidence_sets
                        AS evidence_set
                    WHERE evidence_set.owner_user_id = %s
                      AND evidence_set.workspace_id = %s
                      AND evidence_set.admission_id = %s
                      AND evidence_set.admission_digest = %s
                      AND evidence_set.evidence_set_id = %s
                      AND evidence_set.facts_digest = %s
                      AND evidence_set.baseline_order_snapshot_digest = %s
                      AND evidence_set.final_order_snapshot_digest = %s
                    """,
                    (
                        ROOT_USER_ID,
                        workspace,
                        admission_id,
                        expected_admission,
                        evidence_set_id,
                        evidence_set_digest,
                        record.baseline_order_snapshot_digest,
                        final_order_snapshot_digest,
                    ),
                ).fetchone()
                if verified_evidence is None:
                    raise CandidateAdmissionConflict(
                        "candidate acceptance requires its exact verified v3 evidence set"
                    )
                paper_authority_epoch = (
                    None if verified_evidence[0] is None else int(verified_evidence[0])
                )
                acceptance = canonical_candidate_acceptance_digest(
                    admission_digest=expected_admission,
                    final_evidence_digest=final_evidence,
                    evidence_set_id=evidence_set_id,
                    evidence_set_digest=evidence_set_digest,
                    final_order_snapshot_digest=(final_order_snapshot_digest),
                    closed_at=clock,
                    paper_authority_epoch=paper_authority_epoch,
                )
                updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_candidate_admissions
                    SET status = 'accepted',
                        closed_at = %s,
                        close_reason = %s,
                        final_evidence_digest = %s,
                        acceptance_digest = %s,
                        evidence_set_id = %s,
                        evidence_set_digest = %s,
                        final_order_snapshot_digest = %s
                    WHERE admission_id = %s
                      AND workspace_id = %s
                      AND status = 'open'
                    RETURNING admission_id
                    """,
                    (
                        clock,
                        note,
                        final_evidence,
                        acceptance,
                        evidence_set_id,
                        evidence_set_digest,
                        final_order_snapshot_digest,
                        admission_id,
                        workspace,
                    ),
                ).fetchone()
                if updated is None:
                    raise CandidateAdmissionConflict("candidate acceptance CAS failed")
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace,
                    admission_id=admission_id,
                    event_type="candidate.accepted",
                    event_data={
                        "acceptance_digest": acceptance,
                        "admission_digest": expected_admission,
                        "evidence_set_digest": evidence_set_digest,
                        "evidence_set_id": evidence_set_id,
                        "final_evidence_digest": final_evidence,
                        "final_order_snapshot_digest": (final_order_snapshot_digest),
                        "note": note,
                    },
                    occurred_at=clock,
                )
                receipt = CandidateAdmissionReceipt(
                    operation="candidate.accept",
                    workspace_id=workspace,
                    client_action_id=action_id,
                    action_digest=expected_action,
                    admission_id=admission_id,
                    admission_digest=expected_admission,
                    acceptance_digest=acceptance,
                    evidence_set_id=evidence_set_id,
                    evidence_set_digest=evidence_set_digest,
                    status="accepted",
                    event_cursor=cursor,
                    occurred_at=clock,
                )
                self._store_action(conn, receipt)
                return receipt
        except CandidateAdmissionError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable(
                "candidate acceptance database operation failed"
            ) from exc

    def revoke(
        self,
        request: RevokeCandidateAdmissionRequest,
    ) -> CandidateAdmissionReceipt:
        workspace = _identifier(request.workspace_id, "workspace_id")
        admission_id = _identifier(request.admission_id, "admission_id")
        expected_admission = _digest(
            request.expected_admission_digest,
            "expected_admission_digest",
        )
        reason = _note(request.reason, "reason")
        action_id = _identifier(request.client_action_id, "client_action_id")
        payload = {
            "admission_id": admission_id,
            "expected_admission_digest": expected_admission,
            "reason": reason,
            "workspace_id": workspace,
        }
        expected_action = canonical_candidate_action_digest("candidate.revoke", payload)
        if _digest(request.action_digest, "action_digest") != expected_action:
            raise CandidateAdmissionValidationError(
                "action_digest does not match the canonical request"
            )
        try:
            with self._database().connect() as conn, conn.transaction():
                self._lock(conn, workspace)
                clock = self._clock(conn)
                replay = self._action_replay(
                    conn,
                    workspace_id=workspace,
                    client_action_id=action_id,
                    operation="candidate.revoke",
                    action_digest=expected_action,
                )
                if replay is not None:
                    return replay
                updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_candidate_admissions
                    SET status = 'revoked',
                        closed_at = %s,
                        close_reason = %s
                    WHERE admission_id = %s
                      AND workspace_id = %s
                      AND status = 'open'
                      AND admission_digest = %s
                    RETURNING admission_id
                    """,
                    (
                        clock,
                        reason,
                        admission_id,
                        workspace,
                        expected_admission,
                    ),
                ).fetchone()
                if updated is None:
                    raise CandidateAdmissionConflict("candidate revoke CAS failed")
                cursor = self._append_event(
                    conn,
                    workspace_id=workspace,
                    admission_id=admission_id,
                    event_type="candidate.revoked",
                    event_data={
                        "admission_digest": expected_admission,
                        "reason": reason,
                    },
                    occurred_at=clock,
                )
                receipt = CandidateAdmissionReceipt(
                    operation="candidate.revoke",
                    workspace_id=workspace,
                    client_action_id=action_id,
                    action_digest=expected_action,
                    admission_id=admission_id,
                    admission_digest=expected_admission,
                    status="revoked",
                    event_cursor=cursor,
                    occurred_at=clock,
                )
                self._store_action(conn, receipt)
                return receipt
        except CandidateAdmissionError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise CandidateAdmissionUnavailable(
                "candidate revoke database operation failed"
            ) from exc


__all__ = [
    "AcceptedCandidateReleaseBinding",
    "CANDIDATE_ADMISSION_SCHEMA_VERSION",
    "CANDIDATE_ROUTE",
    "AcceptCandidateAdmissionRequest",
    "CandidateAdmissionAuthority",
    "CandidateAdmissionConflict",
    "CandidateAdmissionError",
    "CandidateAdmissionNotFound",
    "CandidateAdmissionReceipt",
    "CandidateAdmissionRecord",
    "CandidateAdmissionUnavailable",
    "CandidateAdmissionValidationError",
    "OpenCandidateAdmissionRequest",
    "RevokeCandidateAdmissionRequest",
    "candidate_admission_schema_is_ready_on_connection",
    "candidate_admission_schema_ready",
    "candidate_admission_runtime_security_is_ready",
    "canonical_candidate_acceptance_digest",
    "canonical_candidate_action_digest",
    "canonical_candidate_admission_digest",
]
