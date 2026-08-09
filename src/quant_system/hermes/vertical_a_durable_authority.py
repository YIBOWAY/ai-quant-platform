"""Durable two-stage Vertical-A options domain authority.

The browser request path only seeds an immutable PostgreSQL domain request.
The separately invoked :mod:`quant_system.hermes.vertical_a_cli` binds that
request to an already-canonical Hermes Session/Run, durably consumes the
server-issued one-call grant and records the paper-account begin snapshot
*before* it calls the read-only Futu facade.

This module deliberately owns no Hermes Run and no HQA Task/Attempt.  It only
stores exact canonical references plus Platform-owned request, provider
receipt, zero-order proof and typed options result facts.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.result_surface_authority import TypedResultRecord
from quant_system.hermes.vertical_binding_authority import (
    VerticalBindingAuthorityError,
    _bounded_text,
    _enforce_live_auth_envelope,
    _stable_id,
    _validate_id,
)
from quant_system.hermes.vertical_ro_provider import VerticalRoQuote
from quant_system.hermes.zero_order_observation import (
    CanonicalZeroOrderProof,
    CanonicalZeroOrderSnapshot,
    ZeroOrderObservationError,
    capture_canonical_zero_order_snapshot,
    prove_zero_orders,
)
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

VERTICAL_A_DURABLE_SCHEMA_VERSION = 2
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REF_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")
_REQUIRED_FIELDS = ("ask", "bid", "delta", "expiry", "iv", "strike")
_AUTHORITY_TABLES = (
    "agent_v02_vertical_a_grants",
    "agent_v02_vertical_a_requests",
    "agent_v02_vertical_a_claims",
    "agent_v02_vertical_a_zero_order_observations",
    "agent_v02_vertical_a_provider_receipts",
    "agent_v02_vertical_a_results",
    "agent_v02_vertical_a_outcomes",
    "agent_v02_vertical_a_actions",
)
_APPEND_ONLY_TABLES = tuple(
    name for name in _AUTHORITY_TABLES if name != "agent_v02_vertical_a_grants"
)
_DEPENDENCY_READ_TABLES = (
    "agent_v02_candidate_admissions",
    "hermes_workspace_sessions",
    "hermes_commands",
    "hermes_run_links",
    "paper_accounts",
    "paper_account_ledger",
    "paper_pending_orders",
    "paper_positions_current",
)
_SCHEMA_FUNCTIONS = (
    "guard_agent_v02_vertical_a_claim",
    "protect_agent_v02_vertical_a_grant",
    "reject_agent_v02_vertical_a_fact_mutation",
)
# Filled from a fresh migration catalog.  The signature includes columns,
# defaults, every constraint/index/trigger/policy, table owners/RLS flags and
# the three trigger functions.  Any partial restore or CREATE IF NOT EXISTS
# drift therefore fails closed.
_EXPECTED_SCHEMA_SIGNATURE = "fe300908a6600f2418dc1e18109fbd8f544875833b355b8b228d2041ea96153a"


class VerticalADurableAuthorityError(VerticalBindingAuthorityError):
    """Stable fail-closed error surfaced through the submission saga."""


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise VerticalADurableAuthorityError(
            "durable_authority_invalid",
            "Vertical-A fact is not canonical JSON",
        ) from exc


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _public_timestamp(value: datetime | str) -> str:
    if isinstance(value, str):
        raw = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            value = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise VerticalADurableAuthorityError(
                "provider_schema",
                "provider as_of is not an ISO timestamp",
            ) from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise VerticalADurableAuthorityError(
            "provider_schema",
            "timestamp must be timezone-aware",
        )
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _timestamp_value(value: datetime | str) -> datetime:
    return datetime.fromisoformat(_public_timestamp(value).replace("Z", "+00:00"))


def _json_mapping(value: object, *, field: str) -> dict[str, object]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise VerticalADurableAuthorityError(
                "durable_authority_corrupt",
                f"stored {field} is invalid JSON",
            ) from exc
    if not isinstance(value, Mapping):
        raise VerticalADurableAuthorityError(
            "durable_authority_corrupt",
            f"stored {field} must be an object",
        )
    return {str(key): item for key, item in value.items()}


def _prefixed_ref(value: str, prefix: str, field: str) -> str:
    if type(value) is not str or not value.startswith(prefix):
        raise VerticalADurableAuthorityError(
            "validation",
            f"{field} must start with {prefix}",
        )
    bare = value[len(prefix) :]
    if _REF_ID_RE.fullmatch(bare) is None:
        raise VerticalADurableAuthorityError(
            "validation",
            f"{field} must contain a bounded canonical identifier",
        )
    return bare


def _schema_catalog_document(conn: psycopg.Connection) -> dict[str, object]:
    table_names = ("agent_v02_vertical_a_meta", *_AUTHORITY_TABLES)
    columns = conn.execute(
        """
        SELECT relation.relname,
               attribute.attnum,
               attribute.attname,
               format_type(attribute.atttypid, attribute.atttypmod),
               attribute.attnotnull,
               COALESCE(pg_get_expr(default_value.adbin, default_value.adrelid), '')
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
        LEFT JOIN pg_attrdef AS default_value
          ON default_value.adrelid = relation.oid
         AND default_value.adnum = attribute.attnum
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
        ORDER BY relation.relname, attribute.attnum
        """,
        (SCHEMA, list(table_names)),
    ).fetchall()
    constraints = conn.execute(
        """
        SELECT relation.relname,
               constraint_row.conname,
               constraint_row.contype,
               pg_get_constraintdef(constraint_row.oid, TRUE)
        FROM pg_constraint AS constraint_row
        JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
        ORDER BY relation.relname, constraint_row.conname
        """,
        (SCHEMA, list(table_names)),
    ).fetchall()
    indexes = conn.execute(
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = %s
          AND (
              tablename = ANY(%s)
              OR indexname = 'uq_agent_v02_candidate_exact_identity'
          )
        ORDER BY tablename, indexname
        """,
        (SCHEMA, list(table_names)),
    ).fetchall()
    triggers = conn.execute(
        """
        SELECT relation.relname,
               trigger_row.tgname,
               trigger_row.tgenabled,
               function_row.proname,
               pg_get_triggerdef(trigger_row.oid, TRUE)
        FROM pg_trigger AS trigger_row
        JOIN pg_class AS relation ON relation.oid = trigger_row.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS function_row ON function_row.oid = trigger_row.tgfoid
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND NOT trigger_row.tgisinternal
        ORDER BY relation.relname, trigger_row.tgname
        """,
        (SCHEMA, list(_AUTHORITY_TABLES)),
    ).fetchall()
    relations = conn.execute(
        """
        SELECT relation.relname,
               relation.relrowsecurity,
               relation.relforcerowsecurity,
               pg_get_userbyid(relation.relowner)
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
        ORDER BY relation.relname
        """,
        (SCHEMA, list(table_names)),
    ).fetchall()
    policies = conn.execute(
        """
        SELECT relation.relname,
               policy.polname,
               policy.polcmd,
               COALESCE(pg_get_expr(policy.polqual, policy.polrelid), ''),
               COALESCE(pg_get_expr(policy.polwithcheck, policy.polrelid), ''),
               ARRAY(
                   SELECT role.rolname::text
                   FROM unnest(policy.polroles) AS item(role_oid)
                   JOIN pg_roles AS role ON role.oid = item.role_oid
                   ORDER BY role.rolname::text
               )
        FROM pg_policy AS policy
        JOIN pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
        ORDER BY relation.relname, policy.polname
        """,
        (SCHEMA, list(_AUTHORITY_TABLES)),
    ).fetchall()
    functions = conn.execute(
        """
        SELECT function_row.proname,
               pg_get_userbyid(function_row.proowner),
               function_row.prosecdef,
               pg_get_functiondef(function_row.oid)
        FROM pg_proc AS function_row
        JOIN pg_namespace AS namespace ON namespace.oid = function_row.pronamespace
        WHERE namespace.nspname = %s
          AND function_row.proname = ANY(%s)
        ORDER BY function_row.proname
        """,
        (SCHEMA, list(_SCHEMA_FUNCTIONS)),
    ).fetchall()

    def normalized(rows: list[tuple[object, ...]]) -> list[list[object]]:
        result: list[list[object]] = []
        for row in rows:
            values: list[object] = []
            for value in row:
                if isinstance(value, list):
                    values.append([str(item) for item in value])
                elif isinstance(value, bool | int):
                    values.append(value)
                else:
                    values.append(" ".join(str(value).split()))
            result.append(values)
        return result

    return {
        "columns": normalized(columns),
        "constraints": normalized(constraints),
        "functions": normalized(functions),
        "indexes": normalized(indexes),
        "policies": normalized(policies),
        "relations": normalized(relations),
        "triggers": normalized(triggers),
    }


def _vertical_a_schema_signature(conn: psycopg.Connection) -> str:
    return _sha256(_schema_catalog_document(conn))


def vertical_a_schema_is_ready_on_connection(conn: psycopg.Connection) -> bool:
    names = ("agent_v02_vertical_a_meta", *_AUTHORITY_TABLES)
    row = conn.execute(
        """
        SELECT count(*) = %s
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
        """,
        (len(names), SCHEMA, list(names)),
    ).fetchone()
    if row != (True,):
        return False
    old_names = conn.execute(
        """
        SELECT count(*)
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND relation.relkind = 'r'
        """,
        (
            SCHEMA,
            [
                "agent_v02_vertical_a_tasks",
                "agent_v02_vertical_a_attempts",
                "agent_v02_vertical_a_runs",
            ],
        ),
    ).fetchone()
    if old_names != (0,):
        return False
    version = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_vertical_a_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if version != (VERTICAL_A_DURABLE_SCHEMA_VERSION,):
        return False
    return _vertical_a_schema_signature(conn) == _EXPECTED_SCHEMA_SIGNATURE


def _all_table_privileges(
    conn: psycopg.Connection,
    table_name: str,
    *,
    require_insert: bool,
) -> bool:
    relation = f"{SCHEMA}.{table_name}"
    row = conn.execute(
        """
        SELECT has_table_privilege(session_user, %s, 'SELECT'),
               has_table_privilege(session_user, %s, 'INSERT'),
               has_table_privilege(session_user, %s, 'UPDATE'),
               has_table_privilege(session_user, %s, 'DELETE'),
               has_table_privilege(session_user, %s, 'TRUNCATE')
        """,
        (relation, relation, relation, relation, relation),
    ).fetchone()
    if row is None:
        return False
    select_ok, insert_ok, update_ok, delete_ok, truncate_ok = (bool(value) for value in row)
    return (
        select_ok
        and insert_ok is require_insert
        and not update_ok
        and not delete_ok
        and not truncate_ok
    )


def vertical_a_runtime_security_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    if not vertical_a_schema_is_ready_on_connection(conn):
        return False
    principal = conn.execute(
        """
        SELECT EXISTS (
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
    meta = f"{SCHEMA}.agent_v02_vertical_a_meta"
    meta_privileges = conn.execute(
        """
        SELECT has_table_privilege(session_user, %s, 'SELECT'),
               has_table_privilege(session_user, %s, 'INSERT'),
               has_table_privilege(session_user, %s, 'UPDATE'),
               has_table_privilege(session_user, %s, 'DELETE'),
               has_table_privilege(session_user, %s, 'TRUNCATE')
        """,
        (meta, meta, meta, meta, meta),
    ).fetchone()
    if meta_privileges != (True, False, False, False, False):
        return False
    for table_name in _APPEND_ONLY_TABLES:
        if not _all_table_privileges(conn, table_name, require_insert=True):
            return False
    grant_relation = f"{SCHEMA}.agent_v02_vertical_a_grants"
    grant_privileges = conn.execute(
        """
        SELECT has_table_privilege(session_user, %s, 'SELECT'),
               has_table_privilege(session_user, %s, 'INSERT'),
               has_table_privilege(session_user, %s, 'UPDATE'),
               has_table_privilege(session_user, %s, 'DELETE'),
               has_table_privilege(session_user, %s, 'TRUNCATE'),
               has_column_privilege(session_user, %s, 'used_calls', 'UPDATE'),
               has_column_privilege(session_user, %s, 'updated_at', 'UPDATE')
        """,
        (
            grant_relation,
            grant_relation,
            grant_relation,
            grant_relation,
            grant_relation,
            grant_relation,
            grant_relation,
        ),
    ).fetchone()
    if grant_privileges != (True, True, False, False, False, True, True):
        return False
    for table_name in _DEPENDENCY_READ_TABLES:
        relation = f"{SCHEMA}.{table_name}"
        privileges = conn.execute(
            """
            SELECT has_table_privilege(session_user, %s, 'SELECT')
            """,
            (relation,),
        ).fetchone()
        if privileges != (True,):
            return False
    run_links = f"{SCHEMA}.hermes_run_links"
    return conn.execute(
        "SELECT has_table_privilege(session_user, %s, 'INSERT')",
        (run_links,),
    ).fetchone() == (True,)


def vertical_a_runtime_security_ready(settings: Settings) -> bool:
    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            return vertical_a_runtime_security_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return False


@dataclass(frozen=True)
class VerticalAAdmissionBinding:
    admission_id: str
    admission_digest: str
    workspace_id: str
    opened_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class DurableVerticalASeedReceipt:
    domain_request_id: str
    state: str
    action_digest: str
    admission_id: str
    admission_digest: str
    grant_id: str
    grant_digest: str
    result_id: str | None = None


@dataclass(frozen=True)
class DurableVerticalAClaim:
    claim_id: str
    claim_digest: str
    request_id: str
    workspace_id: str
    action_digest: str
    admission_id: str
    admission_digest: str
    grant_id: str
    grant_digest: str
    command_id: str
    platform_session_id: str
    hermes_session_id: str
    hermes_run_id: str
    worker_id: str
    ticker: str
    expiry: str
    strike: float
    begin: CanonicalZeroOrderSnapshot
    claimed_at: datetime

    @property
    def session_ref(self) -> str:
        return f"session:{self.platform_session_id}"

    @property
    def run_ref(self) -> str:
        return f"run:{self.hermes_run_id}"


@dataclass(frozen=True)
class DurableVerticalACompleted:
    request_id: str
    claim_id: str
    result_id: str
    provider_receipt_id: str
    capture_digest: str
    session_ref: str
    run_ref: str


@dataclass(frozen=True)
class DurableVerticalAProjection:
    options_requests: tuple[dict[str, object], ...]
    results: tuple[dict[str, object], ...]
    provider_health: str
    tasks: tuple[str, ...] = ()
    attempts: tuple[str, ...] = ()
    runs: tuple[str, ...] = ()


AdmissionResolver = Callable[[str], VerticalAAdmissionBinding | None]


class PostgresVerticalAAuthority:
    """PostgreSQL request/claim/result authority used by production wiring."""

    authority_kind = "postgres_vertical_a_domain_v2"

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        admission_resolver: AdmissionResolver | None = None,
    ) -> None:
        self._settings = settings
        self._database_override = database
        self._admission_resolver = admission_resolver

    def _validate_safety(self) -> None:
        settings = self._settings
        if settings.paper_account.db_mode != "canonical":
            raise VerticalADurableAuthorityError(
                "canonical_paper_authority_required",
                "Vertical-A live evidence requires canonical paper authority",
            )
        if settings.paper_account.auto_process_pending_orders_enabled:
            raise VerticalADurableAuthorityError(
                "paper_order_processing_must_be_disabled",
                "paper pending-order processing must remain disabled",
            )
        if not settings.safety.kill_switch:
            raise VerticalADurableAuthorityError(
                "kill_switch_must_be_enabled",
                "kill_switch must remain enabled",
            )
        if settings.safety.live_trading_enabled:
            raise VerticalADurableAuthorityError(
                "live_trading_must_be_disabled",
                "live trading must remain disabled",
            )
        if not settings.safety.dry_run or not settings.safety.paper_trading:
            raise VerticalADurableAuthorityError(
                "safe_research_posture_required",
                "dry_run and paper_trading must remain enabled",
            )
        if not settings.futu.enabled or not settings.futu.options_enabled:
            raise VerticalADurableAuthorityError(
                "provider_disabled",
                "Futu options read-only provider must be enabled",
            )

    def _database(self) -> Database:
        database = self._database_override or get_database(self._settings)
        if database is None:
            raise VerticalADurableAuthorityError(
                "durable_authority_unavailable",
                "Vertical-A durable authority requires PostgreSQL",
            )
        return database

    @staticmethod
    def _validate_runtime(conn: psycopg.Connection) -> None:
        if not vertical_a_schema_is_ready_on_connection(conn):
            raise VerticalADurableAuthorityError(
                "durable_authority_schema_unready",
                "Vertical-A durable authority schema is not ready",
            )
        if not vertical_a_runtime_security_is_ready_on_connection(conn):
            raise VerticalADurableAuthorityError(
                "durable_authority_runtime_role_unready",
                "Vertical-A requires the restricted runtime database login",
            )

    @staticmethod
    def _lock(conn: psycopg.Connection, value: str) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"quant_system:agent_v02_vertical_a:{value}",),
        )

    def _resolve_admission(
        self,
        workspace_id: str,
        *,
        now: datetime,
    ) -> VerticalAAdmissionBinding:
        if self._admission_resolver is not None:
            admission = self._admission_resolver(workspace_id)
        else:
            try:
                from quant_system.hermes.candidate_admission_gate import (
                    current_candidate_decision,
                )

                decision = current_candidate_decision(
                    self._settings,
                    require_connector=False,
                )
            except Exception as exc:
                raise VerticalADurableAuthorityError(
                    "candidate_admission_unavailable",
                    "candidate admission authority is unavailable",
                ) from exc
            record = decision.record
            admission = (
                None
                if not decision.ready or record is None
                else VerticalAAdmissionBinding(
                    admission_id=record.admission_id,
                    admission_digest=record.admission_digest,
                    workspace_id=record.workspace_id,
                    opened_at=record.opened_at,
                    expires_at=record.expires_at,
                )
            )
        if admission is None:
            raise VerticalADurableAuthorityError(
                "candidate_admission_missing",
                "an active server-owned candidate admission is required",
            )
        if admission.workspace_id != workspace_id:
            raise VerticalADurableAuthorityError(
                "candidate_admission_workspace_mismatch",
                "candidate admission belongs to a different workspace",
            )
        if (
            _DIGEST_RE.fullmatch(admission.admission_digest) is None
            or _REF_ID_RE.fullmatch(admission.admission_id) is None
        ):
            raise VerticalADurableAuthorityError(
                "candidate_admission_invalid",
                "candidate admission identity is invalid",
            )
        if not (admission.opened_at <= now < admission.expires_at):
            raise VerticalADurableAuthorityError(
                "candidate_admission_expired",
                "candidate admission is outside its server-owned TTL",
            )
        return admission

    @staticmethod
    def _seed_replay(
        conn: psycopg.Connection,
        *,
        workspace_id: str,
        client_action_id: str,
        action_digest: str,
    ) -> DurableVerticalASeedReceipt | None:
        row = conn.execute(
            f"""
            SELECT action.action_digest,
                   action.request_id,
                   request.admission_id,
                   request.admission_digest,
                   request.grant_id,
                   request.grant_digest,
                   outcome.status,
                   outcome.result_id
            FROM {SCHEMA}.agent_v02_vertical_a_actions AS action
            JOIN {SCHEMA}.agent_v02_vertical_a_requests AS request
              ON request.request_id = action.request_id
             AND request.owner_user_id = action.owner_user_id
             AND request.workspace_id = action.workspace_id
            LEFT JOIN {SCHEMA}.agent_v02_vertical_a_outcomes AS outcome
              ON outcome.request_id = request.request_id
             AND outcome.owner_user_id = request.owner_user_id
             AND outcome.workspace_id = request.workspace_id
            WHERE action.owner_user_id = %s
              AND action.workspace_id = %s
              AND action.client_action_id = %s
            """,
            (ROOT_USER_ID, workspace_id, client_action_id),
        ).fetchone()
        if row is None:
            return None
        if str(row[0]).strip() != action_digest:
            raise VerticalADurableAuthorityError(
                "conflict",
                "client_action_id already froze a different action digest",
            )
        state = "awaiting_run" if row[6] is None else str(row[6])
        return DurableVerticalASeedReceipt(
            domain_request_id=str(row[1]),
            state=state,
            action_digest=action_digest,
            admission_id=str(row[2]),
            admission_digest=str(row[3]).strip(),
            grant_id=str(row[4]),
            grant_digest=str(row[5]).strip(),
            result_id=None if row[7] is None else str(row[7]),
        )

    def seed_options_vertical_a(
        self,
        *,
        workspace_id: str,
        client_action_id: str,
        action_digest: str,
        ticker: str,
        goal_note: str,
        expiry: str,
        strike: float | int,
        include_provider_evidence: bool,
        provider_mode: str,
        auth_envelope: dict[str, Any] | None,
        now: datetime | None = None,
    ) -> DurableVerticalASeedReceipt:
        """Seed an immutable request; this function performs no provider I/O."""

        del goal_note
        self._validate_safety()
        workspace = _validate_id(workspace_id, "workspace_id")
        action_id = _validate_id(client_action_id, "client_action_id")
        if _DIGEST_RE.fullmatch(action_digest) is None:
            raise VerticalADurableAuthorityError(
                "validation",
                "action_digest must be lowercase SHA-256",
            )
        ticker_value = _bounded_text(ticker, "ticker", max_len=32).upper()
        expiry_value = _bounded_text(expiry, "expiry", max_len=32)
        if type(strike) is bool or not isinstance(strike, int | float):
            raise VerticalADurableAuthorityError(
                "validation",
                "strike must be a finite number",
            )
        strike_value = float(strike)
        if (
            strike_value <= 0
            or strike_value != strike_value
            or strike_value in (float("inf"), float("-inf"))
        ):
            raise VerticalADurableAuthorityError(
                "validation",
                "strike must be a positive finite number",
            )
        if provider_mode != "live_futu_ro" or include_provider_evidence is not True:
            raise VerticalADurableAuthorityError(
                "durable_live_futu_ro_required",
                "production Vertical-A requires live Futu read-only evidence",
            )
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None or clock.utcoffset() is None:
            clock = clock.replace(tzinfo=UTC)
        clock = clock.astimezone(UTC)
        requested = _enforce_live_auth_envelope(
            ticker=ticker_value,
            auth_envelope=auth_envelope,
            now=clock,
        )
        database = self._database()
        try:
            with database.connect() as conn, conn.transaction():
                self._validate_runtime(conn)
                self._lock(conn, workspace)
                replay = self._seed_replay(
                    conn,
                    workspace_id=workspace,
                    client_action_id=action_id,
                    action_digest=action_digest,
                )
                if replay is not None:
                    return replay

            admission = self._resolve_admission(workspace, now=clock)
            grant_id = _stable_id(
                "vagrant",
                admission.admission_digest,
                "candidate_futu_once",
            )
            grant_document = {
                "admission_digest": admission.admission_digest,
                "admission_id": admission.admission_id,
                "fields": list(_REQUIRED_FIELDS),
                "max_calls": 1,
                "owner_user_id": str(ROOT_USER_ID),
                "ticker": ticker_value,
                "window_end": _public_timestamp(admission.expires_at),
                "window_start": _public_timestamp(admission.opened_at),
                "workspace_id": workspace,
            }
            grant_digest = _sha256(grant_document)
            request_id = _stable_id("vreq", action_digest, "domain_request")
            requested_scope_digest = _sha256(
                {
                    "action_digest": action_digest,
                    "requested_auth_envelope_digest": str(requested.get("grant_digest") or ""),
                    "requested_fields": sorted(
                        str(value).lower() for value in requested.get("fields", [])
                    ),
                    "requested_max_calls": int(requested["max_calls"]),
                    "ticker": ticker_value,
                }
            )
            receipt_document = {
                "action_digest": action_digest,
                "admission_digest": admission.admission_digest,
                "admission_id": admission.admission_id,
                "domain_request_id": request_id,
                "grant_digest": grant_digest,
                "grant_id": grant_id,
                "state": "awaiting_run",
                "workspace_id": workspace,
            }
            with database.connect() as conn, conn.transaction():
                self._validate_runtime(conn)
                self._lock(conn, workspace)
                replay = self._seed_replay(
                    conn,
                    workspace_id=workspace,
                    client_action_id=action_id,
                    action_digest=action_digest,
                )
                if replay is not None:
                    return replay
                admission_row = conn.execute(
                    f"""
                    SELECT opened_at, expires_at
                    FROM {SCHEMA}.agent_v02_candidate_admissions
                    WHERE admission_id = %s
                      AND owner_user_id = %s
                      AND workspace_id = %s
                      AND admission_digest = %s
                      AND status = 'open'
                      AND opened_at <= %s
                      AND expires_at > %s
                    FOR SHARE
                    """,
                    (
                        admission.admission_id,
                        ROOT_USER_ID,
                        workspace,
                        admission.admission_digest,
                        clock,
                        clock,
                    ),
                ).fetchone()
                if admission_row != (
                    admission.opened_at,
                    admission.expires_at,
                ):
                    raise VerticalADurableAuthorityError(
                        "candidate_admission_drift",
                        "candidate admission changed before request persistence",
                    )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_grants (
                        grant_id, owner_user_id, workspace_id,
                        admission_id, admission_digest,
                        ticker, fields, max_calls, used_calls,
                        window_start, window_end, grant_digest
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s::jsonb,
                        1, 0, %s, %s, %s
                    )
                    ON CONFLICT (admission_id) DO NOTHING
                    """,
                    (
                        grant_id,
                        ROOT_USER_ID,
                        workspace,
                        admission.admission_id,
                        admission.admission_digest,
                        ticker_value,
                        _canonical_json(list(_REQUIRED_FIELDS)),
                        admission.opened_at,
                        admission.expires_at,
                        grant_digest,
                    ),
                )
                frozen_grant = conn.execute(
                    f"""
                    SELECT grant_id, grant_digest, ticker, fields,
                           max_calls, window_start, window_end
                    FROM {SCHEMA}.agent_v02_vertical_a_grants
                    WHERE admission_id = %s
                      AND owner_user_id = %s
                      AND workspace_id = %s
                    FOR UPDATE
                    """,
                    (admission.admission_id, ROOT_USER_ID, workspace),
                ).fetchone()
                if frozen_grant is None or (
                    str(frozen_grant[0]),
                    str(frozen_grant[1]).strip(),
                    str(frozen_grant[2]),
                    list(frozen_grant[3]),
                    int(frozen_grant[4]),
                    frozen_grant[5],
                    frozen_grant[6],
                ) != (
                    grant_id,
                    grant_digest,
                    ticker_value,
                    list(_REQUIRED_FIELDS),
                    1,
                    admission.opened_at,
                    admission.expires_at,
                ):
                    raise VerticalADurableAuthorityError(
                        "server_grant_conflict",
                        "candidate admission already froze a different provider grant",
                    )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_requests (
                        request_id, owner_user_id, workspace_id,
                        client_action_id, action_digest,
                        admission_id, admission_digest,
                        grant_id, grant_digest,
                        ticker, expiry, strike, option_type,
                        requested_scope_digest, created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, 'PUT', %s, %s
                    )
                    """,
                    (
                        request_id,
                        ROOT_USER_ID,
                        workspace,
                        action_id,
                        action_digest,
                        admission.admission_id,
                        admission.admission_digest,
                        grant_id,
                        grant_digest,
                        ticker_value,
                        expiry_value,
                        strike_value,
                        requested_scope_digest,
                        clock,
                    ),
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_actions (
                        owner_user_id, workspace_id, client_action_id,
                        action_digest, request_id, seed_receipt, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        ROOT_USER_ID,
                        workspace,
                        action_id,
                        action_digest,
                        request_id,
                        _canonical_json(receipt_document),
                        clock,
                    ),
                )
            return DurableVerticalASeedReceipt(
                domain_request_id=request_id,
                state="awaiting_run",
                action_digest=action_digest,
                admission_id=admission.admission_id,
                admission_digest=admission.admission_digest,
                grant_id=grant_id,
                grant_digest=grant_digest,
            )
        except VerticalADurableAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise VerticalADurableAuthorityError(
                "durable_authority_unavailable",
                "Vertical-A request persistence failed",
            ) from exc

    def claim_request(
        self,
        *,
        request_id: str,
        expected_action_digest: str,
        expected_admission_id: str,
        expected_admission_digest: str,
        session_ref: str,
        run_ref: str,
        worker_id: str,
        now: datetime | None = None,
    ) -> DurableVerticalAClaim:
        """Commit the one-call reservation and begin snapshot before Futu I/O."""

        self._validate_safety()
        request_value = _validate_id(request_id, "request_id")
        worker = _validate_id(worker_id, "worker_id")
        if _DIGEST_RE.fullmatch(expected_action_digest) is None:
            raise VerticalADurableAuthorityError(
                "validation",
                "expected_action_digest must be lowercase SHA-256",
            )
        if _DIGEST_RE.fullmatch(expected_admission_digest) is None:
            raise VerticalADurableAuthorityError(
                "validation",
                "expected_admission_digest must be lowercase SHA-256",
            )
        admission_id = _validate_id(expected_admission_id, "expected_admission_id")
        platform_session_id = _prefixed_ref(session_ref, "session:", "session_ref")
        hermes_run_id = _prefixed_ref(run_ref, "run:", "run_ref")
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None or clock.utcoffset() is None:
            clock = clock.replace(tzinfo=UTC)
        clock = clock.astimezone(UTC)
        database = self._database()
        try:
            with database.connect() as preflight:
                request_workspace = preflight.execute(
                    f"""
                    SELECT workspace_id
                    FROM {SCHEMA}.agent_v02_vertical_a_requests
                    WHERE owner_user_id = %s AND request_id = %s
                    """,
                    (ROOT_USER_ID, request_value),
                ).fetchone()
            if request_workspace is None:
                raise VerticalADurableAuthorityError(
                    "domain_request_missing",
                    "Vertical-A domain request does not exist",
                )
            admission = self._resolve_admission(
                str(request_workspace[0]),
                now=clock,
            )
            if (
                admission.admission_id != admission_id
                or admission.admission_digest != expected_admission_digest
            ):
                raise VerticalADurableAuthorityError(
                    "candidate_admission_drift",
                    "current candidate admission does not match the frozen request",
                )

            with database.connect() as conn, conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                self._validate_runtime(conn)
                self._lock(conn, request_value)
                request_row = conn.execute(
                    f"""
                    SELECT request.workspace_id,
                           request.action_digest,
                           request.admission_id,
                           request.admission_digest,
                           request.grant_id,
                           request.grant_digest,
                           request.ticker,
                           request.expiry,
                           request.strike,
                           admission.status,
                           admission.expires_at
                    FROM {SCHEMA}.agent_v02_vertical_a_requests AS request
                    JOIN {SCHEMA}.agent_v02_candidate_admissions AS admission
                      ON admission.admission_id = request.admission_id
                     AND admission.owner_user_id = request.owner_user_id
                     AND admission.workspace_id = request.workspace_id
                     AND admission.admission_digest = request.admission_digest
                    WHERE request.owner_user_id = %s
                      AND request.request_id = %s
                    """,
                    (ROOT_USER_ID, request_value),
                ).fetchone()
                if request_row is None:
                    raise VerticalADurableAuthorityError(
                        "domain_request_missing",
                        "Vertical-A domain request does not exist",
                    )
                workspace = str(request_row[0])
                action_digest = str(request_row[1]).strip()
                frozen_admission_id = str(request_row[2])
                frozen_admission_digest = str(request_row[3]).strip()
                grant_id = str(request_row[4])
                grant_digest = str(request_row[5]).strip()
                ticker = str(request_row[6])
                expiry = str(request_row[7])
                strike = float(request_row[8])
                if (
                    action_digest != expected_action_digest
                    or frozen_admission_id != admission_id
                    or frozen_admission_digest != expected_admission_digest
                ):
                    raise VerticalADurableAuthorityError(
                        "claim_binding_conflict",
                        "claim expectations do not match the frozen domain request",
                    )
                if str(request_row[9]) != "open" or request_row[10] <= clock:
                    raise VerticalADurableAuthorityError(
                        "candidate_admission_expired",
                        "candidate admission closed before provider claim",
                    )
                outcome = conn.execute(
                    f"""
                    SELECT status
                    FROM {SCHEMA}.agent_v02_vertical_a_outcomes
                    WHERE owner_user_id = %s AND request_id = %s
                    """,
                    (ROOT_USER_ID, request_value),
                ).fetchone()
                if outcome is not None:
                    code = (
                        "domain_request_already_completed"
                        if str(outcome[0]) == "completed"
                        else "provider_outcome_unknown"
                    )
                    raise VerticalADurableAuthorityError(code, code)
                prior_claim = conn.execute(
                    f"""
                    SELECT claim_digest
                    FROM {SCHEMA}.agent_v02_vertical_a_claims
                    WHERE owner_user_id = %s AND request_id = %s
                    """,
                    (ROOT_USER_ID, request_value),
                ).fetchone()
                if prior_claim is not None:
                    raise VerticalADurableAuthorityError(
                        "provider_outcome_unknown",
                        "pre-call was committed; provider outcome must not be replayed",
                    )
                canonical = conn.execute(
                    f"""
                    SELECT command.command_id,
                           session.hermes_session_id,
                           command.hermes_run_id
                    FROM {SCHEMA}.hermes_workspace_sessions AS session
                    JOIN {SCHEMA}.hermes_commands AS command
                      ON command.owner_user_id = session.owner_user_id
                     AND command.platform_session_id = session.platform_session_id
                     AND command.hermes_session_id = session.hermes_session_id
                    WHERE session.owner_user_id = %s
                      AND session.workspace_id = %s
                      AND session.platform_session_id = %s
                      AND session.kind = 'web_managed_session'
                      AND session.provision_state = 'ready'
                      AND session.provisioning_receipt_digest IS NOT NULL
                      AND session.provisioned_at IS NOT NULL
                      AND session.candidate_admission_id = %s
                      AND command.candidate_admission_id = %s
                      AND command.hermes_run_id = %s
                      AND command.state IN ('delivered', 'succeeded')
                    """,
                    (
                        ROOT_USER_ID,
                        workspace,
                        platform_session_id,
                        admission_id,
                        admission_id,
                        hermes_run_id,
                    ),
                ).fetchone()
                if canonical is None:
                    raise VerticalADurableAuthorityError(
                        "canonical_hermes_run_missing",
                        "claim lacks an exact delivered Hermes Session/Run",
                    )
                command_id = UUID(str(canonical[0]))
                hermes_session_id = str(canonical[1])
                updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_vertical_a_grants
                    SET used_calls = used_calls + 1,
                        updated_at = now()
                    WHERE grant_id = %s
                      AND owner_user_id = %s
                      AND workspace_id = %s
                      AND admission_id = %s
                      AND admission_digest = %s
                      AND grant_digest = %s
                      AND window_start <= %s
                      AND window_end > %s
                      AND used_calls < max_calls
                    RETURNING used_calls
                    """,
                    (
                        grant_id,
                        ROOT_USER_ID,
                        workspace,
                        admission_id,
                        expected_admission_digest,
                        grant_digest,
                        clock,
                        clock,
                    ),
                ).fetchone()
                if updated != (1,):
                    raise VerticalADurableAuthorityError(
                        "server_grant_budget_exceeded",
                        "server-issued candidate grant has no remaining call",
                    )
                begin = capture_canonical_zero_order_snapshot(
                    conn,
                    owner_user_id=ROOT_USER_ID,
                )
                claim_id = _stable_id("vaclaim", action_digest, "provider_attempt")
                claim_document = {
                    "action_digest": action_digest,
                    "admission_digest": expected_admission_digest,
                    "admission_id": admission_id,
                    "begin_snapshot_digest": begin.snapshot_digest,
                    "begin_table_counts": begin.table_counts,
                    "begin_table_digests": begin.table_digests,
                    "command_id": str(command_id),
                    "grant_digest": grant_digest,
                    "grant_id": grant_id,
                    "hermes_run_id": hermes_run_id,
                    "hermes_session_id": hermes_session_id,
                    "platform_session_id": platform_session_id,
                    "request_id": request_value,
                    "worker_id": worker,
                    "workspace_id": workspace,
                }
                claim_digest = _sha256(claim_document)
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_claims (
                        claim_id, request_id, owner_user_id, workspace_id,
                        action_digest, admission_id, admission_digest,
                        grant_id, grant_digest, command_id,
                        platform_session_id, hermes_session_id, hermes_run_id,
                        worker_id, begin_snapshot_digest,
                        begin_table_counts, begin_table_digests,
                        claim_digest, claimed_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s
                    )
                    """,
                    (
                        claim_id,
                        request_value,
                        ROOT_USER_ID,
                        workspace,
                        action_digest,
                        admission_id,
                        expected_admission_digest,
                        grant_id,
                        grant_digest,
                        command_id,
                        platform_session_id,
                        hermes_session_id,
                        hermes_run_id,
                        worker,
                        begin.snapshot_digest,
                        _canonical_json(begin.table_counts),
                        _canonical_json(begin.table_digests),
                        claim_digest,
                        clock,
                    ),
                )
            return DurableVerticalAClaim(
                claim_id=claim_id,
                claim_digest=claim_digest,
                request_id=request_value,
                workspace_id=workspace,
                action_digest=action_digest,
                admission_id=admission_id,
                admission_digest=expected_admission_digest,
                grant_id=grant_id,
                grant_digest=grant_digest,
                command_id=str(command_id),
                platform_session_id=platform_session_id,
                hermes_session_id=hermes_session_id,
                hermes_run_id=hermes_run_id,
                worker_id=worker,
                ticker=ticker,
                expiry=expiry,
                strike=strike,
                begin=begin,
                claimed_at=clock,
            )
        except VerticalADurableAuthorityError:
            raise
        except ZeroOrderObservationError as exc:
            raise VerticalADurableAuthorityError(exc.code, exc.message) from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise VerticalADurableAuthorityError(
                "durable_authority_unavailable",
                "Vertical-A pre-call claim failed",
            ) from exc

    @staticmethod
    def _provider_receipt(
        *,
        claim: DurableVerticalAClaim,
        quote: VerticalRoQuote,
        proof: CanonicalZeroOrderProof,
    ) -> tuple[str, str, dict[str, object], str]:
        if quote.provider_name != "futu":
            raise VerticalADurableAuthorityError(
                "provider_evidence_invalid",
                "verified provider receipt must bind provider=futu",
            )
        if (
            quote.ticker != claim.ticker
            or quote.expiry != claim.expiry
            or float(quote.strike) != claim.strike
        ):
            raise VerticalADurableAuthorityError(
                "provider_evidence_invalid",
                "provider quote does not match the immutable domain request",
            )
        if not quote.request_id:
            raise VerticalADurableAuthorityError(
                "provider_evidence_invalid",
                "provider receipt requires request_id",
            )
        field_summary: dict[str, object] = {
            "apr": quote.apr,
            "ask": quote.ask,
            "bid": quote.bid,
            "delta": quote.delta,
            "expiry": quote.expiry,
            "iv": quote.iv,
            "strike": quote.strike,
            "ticker": quote.ticker,
        }
        field_summary_digest = _sha256(field_summary)
        receipt_document = {
            "action_digest": claim.action_digest,
            "admission_digest": claim.admission_digest,
            "admission_id": claim.admission_id,
            "as_of": _public_timestamp(quote.as_of),
            "capture_digest": proof.capture_digest,
            "claim_digest": claim.claim_digest,
            "command_id": claim.command_id,
            "expiry": quote.expiry,
            "field_summary_digest": field_summary_digest,
            "grant_digest": claim.grant_digest,
            "grant_id": claim.grant_id,
            "hermes_run_id": claim.hermes_run_id,
            "hermes_session_id": claim.hermes_session_id,
            "provider": "futu",
            "provider_request_id": quote.request_id,
            "request_id": claim.request_id,
            "strike": quote.strike,
            "ticker": quote.ticker,
            "workspace_id": claim.workspace_id,
        }
        receipt_digest = _sha256(receipt_document)
        return (
            _stable_id("vaprovider", claim.action_digest, "provider_receipt"),
            receipt_digest,
            field_summary,
            field_summary_digest,
        )

    @staticmethod
    def _typed_result(
        *,
        claim: DurableVerticalAClaim,
        quote: VerticalRoQuote,
        proof: CanonicalZeroOrderProof,
        provider_receipt_id: str,
        provider_receipt_digest: str,
    ) -> TypedResultRecord:
        evidence = tuple(
            dict.fromkeys(
                [
                    *quote.evidence,
                    f"provider_receipt:{provider_receipt_id}",
                    f"provider_receipt_digest:{provider_receipt_digest}",
                    f"zero_order_capture:{proof.capture_digest}",
                    f"candidate_admission:{claim.admission_id}",
                    f"action_digest:{claim.action_digest}",
                    "orders_created:0",
                ]
            )
        )
        return TypedResultRecord(
            workspace_id=claim.workspace_id,
            result_id=_stable_id("varesult", claim.action_digest, "options_result"),
            kind="options_vertical_a",
            display_title=f"{quote.ticker} sell-put research (completed)",
            status="completed",
            sample_or_real="real",
            freshness="fresh",
            read_status="available",
            occurred_at=_public_timestamp(quote.as_of),
            summary="Futu read-only options observation",
            run_id=claim.hermes_run_id,
            command_id=claim.command_id,
            ticker=quote.ticker,
            expiry=quote.expiry,
            strike=quote.strike,
            bid=quote.bid,
            ask=quote.ask,
            delta=quote.delta,
            iv=quote.iv,
            apr=quote.apr,
            provider_evidence=evidence,
            filters=("delta_band", "dte_window", "sell_put_research"),
            exclusions=("earnings_week",),
            limitations=(
                "live_futu_read_only",
                "not_tradeable",
                "zero_orders",
                "canonical_zero_order_observed",
            ),
            source="vertical_a_futu_read_only_cli",
            authority="postgres_vertical_a_options_domain",
            payload_digest=provider_receipt_digest,
            extra={
                "domain_request_id": claim.request_id,
                "session_ref": claim.session_ref,
                "admission_id": claim.admission_id,
            },
        )

    @staticmethod
    def _load_completed(
        conn: psycopg.Connection,
        *,
        claim_id: str,
        expected_claim_digest: str,
    ) -> DurableVerticalACompleted | None:
        row = conn.execute(
            f"""
            SELECT claim.claim_digest,
                   claim.request_id,
                   result.result_id,
                   result.provider_receipt_id,
                   receipt.capture_digest,
                   claim.platform_session_id,
                   claim.hermes_run_id
            FROM {SCHEMA}.agent_v02_vertical_a_claims AS claim
            JOIN {SCHEMA}.agent_v02_vertical_a_outcomes AS outcome
              ON outcome.claim_id = claim.claim_id
             AND outcome.status = 'completed'
            JOIN {SCHEMA}.agent_v02_vertical_a_results AS result
              ON result.result_id = outcome.result_id
             AND result.claim_id = claim.claim_id
            JOIN {SCHEMA}.agent_v02_vertical_a_provider_receipts AS receipt
              ON receipt.provider_receipt_id = result.provider_receipt_id
            WHERE claim.owner_user_id = %s
              AND claim.claim_id = %s
            """,
            (ROOT_USER_ID, claim_id),
        ).fetchone()
        if row is None:
            return None
        if str(row[0]).strip() != expected_claim_digest:
            raise VerticalADurableAuthorityError(
                "claim_binding_conflict",
                "claim digest does not match the durable provider attempt",
            )
        return DurableVerticalACompleted(
            request_id=str(row[1]),
            claim_id=claim_id,
            result_id=str(row[2]),
            provider_receipt_id=str(row[3]),
            capture_digest=str(row[4]).strip(),
            session_ref=f"session:{row[5]}",
            run_ref=f"run:{row[6]}",
        )

    def finalize_verified_futu_quote(
        self,
        *,
        claim_id: str,
        expected_claim_digest: str,
        quote: VerticalRoQuote,
        now: datetime | None = None,
    ) -> DurableVerticalACompleted:
        """Finalize a quote returned by the fixed production Futu CLI path."""

        self._validate_safety()
        claim_value = _validate_id(claim_id, "claim_id")
        if _DIGEST_RE.fullmatch(expected_claim_digest) is None:
            raise VerticalADurableAuthorityError(
                "validation",
                "expected_claim_digest must be lowercase SHA-256",
            )
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None or clock.utcoffset() is None:
            clock = clock.replace(tzinfo=UTC)
        clock = clock.astimezone(UTC)
        database = self._database()
        try:
            with database.connect() as conn, conn.transaction():
                conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                self._validate_runtime(conn)
                self._lock(conn, claim_value)
                replay = self._load_completed(
                    conn,
                    claim_id=claim_value,
                    expected_claim_digest=expected_claim_digest,
                )
                if replay is not None:
                    return replay
                row = conn.execute(
                    f"""
                    SELECT claim.request_id,
                           claim.workspace_id,
                           claim.action_digest,
                           claim.admission_id,
                           claim.admission_digest,
                           claim.grant_id,
                           claim.grant_digest,
                           claim.command_id,
                           claim.platform_session_id,
                           claim.hermes_session_id,
                           claim.hermes_run_id,
                           claim.worker_id,
                           claim.begin_snapshot_digest,
                           claim.begin_table_counts,
                           claim.begin_table_digests,
                           claim.claim_digest,
                           claim.claimed_at,
                           request.ticker,
                           request.expiry,
                           request.strike,
                           outcome.status
                    FROM {SCHEMA}.agent_v02_vertical_a_claims AS claim
                    JOIN {SCHEMA}.agent_v02_vertical_a_requests AS request
                      ON request.request_id = claim.request_id
                     AND request.owner_user_id = claim.owner_user_id
                     AND request.workspace_id = claim.workspace_id
                    LEFT JOIN {SCHEMA}.agent_v02_vertical_a_outcomes AS outcome
                      ON outcome.claim_id = claim.claim_id
                    WHERE claim.owner_user_id = %s
                      AND claim.claim_id = %s
                    """,
                    (ROOT_USER_ID, claim_value),
                ).fetchone()
                if row is None:
                    raise VerticalADurableAuthorityError(
                        "provider_claim_missing",
                        "durable pre-call claim does not exist",
                    )
                if str(row[15]).strip() != expected_claim_digest:
                    raise VerticalADurableAuthorityError(
                        "claim_binding_conflict",
                        "claim digest does not match the durable provider attempt",
                    )
                if row[20] is not None:
                    raise VerticalADurableAuthorityError(
                        "provider_outcome_unknown",
                        "claim already has a non-completed terminal outcome",
                    )
                begin_counts = _json_mapping(row[13], field="begin_table_counts")
                begin_digests = _json_mapping(
                    row[14],
                    field="begin_table_digests",
                )
                begin = CanonicalZeroOrderSnapshot(
                    owner_user_id=str(ROOT_USER_ID),
                    account_count=int(begin_counts.get("paper_accounts") or 0),
                    table_counts={str(key): int(value) for key, value in begin_counts.items()},
                    table_digests={str(key): str(value) for key, value in begin_digests.items()},
                    snapshot_digest=str(row[12]).strip(),
                )
                claim = DurableVerticalAClaim(
                    claim_id=claim_value,
                    claim_digest=expected_claim_digest,
                    request_id=str(row[0]),
                    workspace_id=str(row[1]),
                    action_digest=str(row[2]).strip(),
                    admission_id=str(row[3]),
                    admission_digest=str(row[4]).strip(),
                    grant_id=str(row[5]),
                    grant_digest=str(row[6]).strip(),
                    command_id=str(row[7]),
                    platform_session_id=str(row[8]),
                    hermes_session_id=str(row[9]),
                    hermes_run_id=str(row[10]),
                    worker_id=str(row[11]),
                    ticker=str(row[17]),
                    expiry=str(row[18]),
                    strike=float(row[19]),
                    begin=begin,
                    claimed_at=row[16],
                )
                canonical = conn.execute(
                    f"""
                    SELECT 1
                    FROM {SCHEMA}.hermes_workspace_sessions AS session
                    JOIN {SCHEMA}.hermes_commands AS command
                      ON command.command_id = %s
                     AND command.owner_user_id = session.owner_user_id
                     AND command.platform_session_id = session.platform_session_id
                     AND command.hermes_session_id = session.hermes_session_id
                    WHERE session.owner_user_id = %s
                      AND session.workspace_id = %s
                      AND session.platform_session_id = %s
                      AND session.hermes_session_id = %s
                      AND session.kind = 'web_managed_session'
                      AND session.provision_state = 'ready'
                      AND session.provisioning_receipt_digest IS NOT NULL
                      AND session.provisioned_at IS NOT NULL
                      AND session.candidate_admission_id = %s
                      AND command.candidate_admission_id = %s
                      AND command.hermes_run_id = %s
                      AND command.state IN ('delivered', 'succeeded')
                    """,
                    (
                        UUID(claim.command_id),
                        ROOT_USER_ID,
                        claim.workspace_id,
                        claim.platform_session_id,
                        claim.hermes_session_id,
                        claim.admission_id,
                        claim.admission_id,
                        claim.hermes_run_id,
                    ),
                ).fetchone()
                if canonical != (1,):
                    raise VerticalADurableAuthorityError(
                        "canonical_hermes_run_drift",
                        "canonical Hermes Session/Run link changed before finalize",
                    )
                end = capture_canonical_zero_order_snapshot(
                    conn,
                    owner_user_id=ROOT_USER_ID,
                )
                proof = prove_zero_orders(
                    action_digest=claim.action_digest,
                    admission_digest=claim.admission_digest,
                    begin=claim.begin,
                    end=end,
                )
                (
                    provider_receipt_id,
                    provider_receipt_digest,
                    field_summary,
                    field_summary_digest,
                ) = self._provider_receipt(
                    claim=claim,
                    quote=quote,
                    proof=proof,
                )
                typed_result = self._typed_result(
                    claim=claim,
                    quote=quote,
                    proof=proof,
                    provider_receipt_id=provider_receipt_id,
                    provider_receipt_digest=provider_receipt_digest,
                )
                result_payload = typed_result.to_public_dict()
                result_payload_digest = _sha256(result_payload)
                result_id = typed_result.result_id
                observation_id = _stable_id(
                    "vazero",
                    claim.action_digest,
                    "zero_order_observation",
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_zero_order_observations (
                        observation_id, claim_id, request_id,
                        owner_user_id, workspace_id,
                        action_digest, admission_id, admission_digest,
                        begin_snapshot_digest, end_snapshot_digest,
                        begin_table_counts, end_table_counts,
                        begin_table_digests, end_table_digests,
                        orders_created, delta_zero, capture_digest, captured_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                        0, TRUE, %s, %s
                    )
                    """,
                    (
                        observation_id,
                        claim.claim_id,
                        claim.request_id,
                        ROOT_USER_ID,
                        claim.workspace_id,
                        claim.action_digest,
                        claim.admission_id,
                        claim.admission_digest,
                        proof.begin.snapshot_digest,
                        proof.end.snapshot_digest,
                        _canonical_json(proof.begin.table_counts),
                        _canonical_json(proof.end.table_counts),
                        _canonical_json(proof.begin.table_digests),
                        _canonical_json(proof.end.table_digests),
                        proof.capture_digest,
                        clock,
                    ),
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_provider_receipts (
                        provider_receipt_id, claim_id, request_id,
                        owner_user_id, workspace_id,
                        action_digest, admission_id, admission_digest,
                        command_id, platform_session_id,
                        hermes_session_id, hermes_run_id,
                        capture_digest, provider, provider_request_id,
                        as_of, ticker, expiry, strike,
                        field_summary, field_summary_digest,
                        grant_id, grant_digest, receipt_digest, created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, 'futu', %s, %s, %s, %s, %s,
                        %s::jsonb, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        provider_receipt_id,
                        claim.claim_id,
                        claim.request_id,
                        ROOT_USER_ID,
                        claim.workspace_id,
                        claim.action_digest,
                        claim.admission_id,
                        claim.admission_digest,
                        UUID(claim.command_id),
                        claim.platform_session_id,
                        claim.hermes_session_id,
                        claim.hermes_run_id,
                        proof.capture_digest,
                        quote.request_id,
                        _timestamp_value(quote.as_of),
                        quote.ticker,
                        quote.expiry,
                        float(quote.strike),
                        _canonical_json(field_summary),
                        field_summary_digest,
                        claim.grant_id,
                        claim.grant_digest,
                        provider_receipt_digest,
                        clock,
                    ),
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_results (
                        result_id, request_id, claim_id,
                        owner_user_id, workspace_id,
                        command_id, platform_session_id,
                        hermes_session_id, hermes_run_id,
                        provider_receipt_id, status, sample_or_real,
                        public_payload, public_payload_digest, occurred_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, 'completed', 'real', %s::jsonb, %s, %s
                    )
                    """,
                    (
                        result_id,
                        claim.request_id,
                        claim.claim_id,
                        ROOT_USER_ID,
                        claim.workspace_id,
                        UUID(claim.command_id),
                        claim.platform_session_id,
                        claim.hermes_session_id,
                        claim.hermes_run_id,
                        provider_receipt_id,
                        _canonical_json(result_payload),
                        result_payload_digest,
                        _timestamp_value(quote.as_of),
                    ),
                )
                link_document = {
                    "command_id": claim.command_id,
                    "hermes_run_id": claim.hermes_run_id,
                    "hermes_session_id": claim.hermes_session_id,
                    "platform_resource_id": result_id,
                    "platform_resource_type": "options_result",
                    "relation": "output",
                }
                link_digest = _sha256(link_document)
                link_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"quant-system:vertical-a:{link_digest}",
                )
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.hermes_run_links (
                        link_id, command_id,
                        platform_resource_type, platform_resource_id,
                        relation, hermes_session_id, hermes_run_id,
                        link_digest, source_event_id, observed_at
                    )
                    VALUES (
                        %s, %s, 'options_result', %s, 'output',
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        link_id,
                        UUID(claim.command_id),
                        result_id,
                        claim.hermes_session_id,
                        claim.hermes_run_id,
                        link_digest,
                        quote.request_id,
                        _timestamp_value(quote.as_of),
                    ),
                )
                outcome_id = _stable_id(
                    "vaoutcome",
                    claim.action_digest,
                    "completed",
                )
                public_receipt = {
                    "capture_digest": proof.capture_digest,
                    "claim_id": claim.claim_id,
                    "domain_request_id": claim.request_id,
                    "provider_receipt_id": provider_receipt_id,
                    "result_id": result_id,
                    "run_ref": claim.run_ref,
                    "session_ref": claim.session_ref,
                    "status": "completed",
                }
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_outcomes (
                        outcome_id, request_id, claim_id,
                        owner_user_id, workspace_id,
                        status, result_id, error_code,
                        public_receipt, occurred_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        'completed', %s, NULL, %s::jsonb, %s
                    )
                    """,
                    (
                        outcome_id,
                        claim.request_id,
                        claim.claim_id,
                        ROOT_USER_ID,
                        claim.workspace_id,
                        result_id,
                        _canonical_json(public_receipt),
                        clock,
                    ),
                )
            return DurableVerticalACompleted(
                request_id=claim.request_id,
                claim_id=claim.claim_id,
                result_id=result_id,
                provider_receipt_id=provider_receipt_id,
                capture_digest=proof.capture_digest,
                session_ref=claim.session_ref,
                run_ref=claim.run_ref,
            )
        except VerticalADurableAuthorityError:
            raise
        except ZeroOrderObservationError as exc:
            raise VerticalADurableAuthorityError(exc.code, exc.message) from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise VerticalADurableAuthorityError(
                "durable_authority_unavailable",
                "Vertical-A result finalize failed",
            ) from exc

    def mark_outcome_unknown(
        self,
        *,
        claim_id: str,
        expected_claim_digest: str,
        error_code: str,
        now: datetime | None = None,
    ) -> None:
        """Seal an uncertain post-precall outcome; it is never retryable."""

        claim_value = _validate_id(claim_id, "claim_id")
        error = _validate_id(error_code, "error_code")
        if _DIGEST_RE.fullmatch(expected_claim_digest) is None:
            raise VerticalADurableAuthorityError(
                "validation",
                "expected_claim_digest must be lowercase SHA-256",
            )
        clock = now or datetime.now(UTC)
        if clock.tzinfo is None or clock.utcoffset() is None:
            clock = clock.replace(tzinfo=UTC)
        database = self._database()
        try:
            with database.connect() as conn, conn.transaction():
                self._validate_runtime(conn)
                self._lock(conn, claim_value)
                row = conn.execute(
                    f"""
                    SELECT request_id, workspace_id,
                           action_digest, claim_digest
                    FROM {SCHEMA}.agent_v02_vertical_a_claims
                    WHERE owner_user_id = %s AND claim_id = %s
                    """,
                    (ROOT_USER_ID, claim_value),
                ).fetchone()
                if row is None or str(row[3]).strip() != expected_claim_digest:
                    raise VerticalADurableAuthorityError(
                        "claim_binding_conflict",
                        "unknown-outcome seal does not match the durable claim",
                    )
                existing = conn.execute(
                    f"""
                    SELECT status
                    FROM {SCHEMA}.agent_v02_vertical_a_outcomes
                    WHERE owner_user_id = %s AND claim_id = %s
                    """,
                    (ROOT_USER_ID, claim_value),
                ).fetchone()
                if existing is not None:
                    if str(existing[0]) == "outcome_unknown":
                        return
                    raise VerticalADurableAuthorityError(
                        "domain_request_already_completed",
                        "completed result cannot be changed to outcome_unknown",
                    )
                public_receipt = {
                    "claim_id": claim_value,
                    "domain_request_id": str(row[0]),
                    "error_code": error,
                    "recovery_action": "operator_reconcile_no_provider_replay",
                    "status": "outcome_unknown",
                }
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_vertical_a_outcomes (
                        outcome_id, request_id, claim_id,
                        owner_user_id, workspace_id,
                        status, result_id, error_code,
                        public_receipt, occurred_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        'outcome_unknown', NULL, %s, %s::jsonb, %s
                    )
                    """,
                    (
                        _stable_id(
                            "vaoutcome",
                            str(row[2]).strip(),
                            "outcome_unknown",
                        ),
                        str(row[0]),
                        claim_value,
                        ROOT_USER_ID,
                        str(row[1]),
                        error,
                        _canonical_json(public_receipt),
                        clock,
                    ),
                )
        except VerticalADurableAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise VerticalADurableAuthorityError(
                "durable_authority_unavailable",
                "Vertical-A outcome_unknown seal failed",
            ) from exc

    def project_workspace(
        self,
        workspace_id: str,
    ) -> DurableVerticalAProjection:
        workspace = _validate_id(workspace_id, "workspace_id")
        self._validate_safety()
        database = self._database()
        try:
            with database.connect() as conn:
                self._validate_runtime(conn)
                rows = conn.execute(
                    f"""
                    SELECT request.request_id,
                           request.client_action_id,
                           request.action_digest,
                           request.admission_id,
                           request.admission_digest,
                           request.ticker,
                           request.expiry,
                           request.strike,
                           request.created_at,
                           claim.claim_id,
                           claim.platform_session_id,
                           claim.hermes_run_id,
                           outcome.status,
                           outcome.result_id,
                           result.public_payload
                    FROM {SCHEMA}.agent_v02_vertical_a_requests AS request
                    LEFT JOIN {SCHEMA}.agent_v02_vertical_a_claims AS claim
                      ON claim.request_id = request.request_id
                     AND claim.owner_user_id = request.owner_user_id
                     AND claim.workspace_id = request.workspace_id
                    LEFT JOIN {SCHEMA}.agent_v02_vertical_a_outcomes AS outcome
                      ON outcome.request_id = request.request_id
                     AND outcome.owner_user_id = request.owner_user_id
                     AND outcome.workspace_id = request.workspace_id
                    LEFT JOIN {SCHEMA}.agent_v02_vertical_a_results AS result
                      ON result.result_id = outcome.result_id
                     AND result.request_id = request.request_id
                    WHERE request.owner_user_id = %s
                      AND request.workspace_id = %s
                    ORDER BY request.created_at, request.request_id
                    """,
                    (ROOT_USER_ID, workspace),
                ).fetchall()
                latest = conn.execute(
                    f"""
                    SELECT max(created_at), clock_timestamp()
                    FROM {SCHEMA}.agent_v02_vertical_a_provider_receipts
                    WHERE owner_user_id = %s AND workspace_id = %s
                    """,
                    (ROOT_USER_ID, workspace),
                ).fetchone()
        except VerticalADurableAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise VerticalADurableAuthorityError(
                "durable_authority_unavailable",
                "Vertical-A durable projection is unavailable",
            ) from exc
        requests: list[dict[str, object]] = []
        results: list[dict[str, object]] = []
        for row in rows:
            outcome_status = None if row[12] is None else str(row[12])
            state = (
                outcome_status
                if outcome_status is not None
                else ("outcome_unknown" if row[9] is not None else "awaiting_run")
            )
            item: dict[str, object] = {
                "action_digest": str(row[2]).strip(),
                "admission_digest": str(row[4]).strip(),
                "admission_id": str(row[3]),
                "client_action_id": str(row[1]),
                "domain_request_id": str(row[0]),
                "domain_request_ref": f"options-request:{row[0]}",
                "expiry": str(row[6]),
                "recovery_action": (
                    "follow_workspace"
                    if state == "awaiting_run"
                    else (
                        "operator_reconcile_no_provider_replay"
                        if state == "outcome_unknown"
                        else None
                    )
                ),
                "state": state,
                "strike": float(row[7]),
                "ticker": str(row[5]),
                "created_at": _public_timestamp(row[8]),
            }
            if row[9] is not None:
                item["claim_id"] = str(row[9])
                item["session_ref"] = f"session:{row[10]}"
                item["run_ref"] = f"run:{row[11]}"
            if row[13] is not None:
                item["result_id"] = str(row[13])
            requests.append(item)
            if row[14] is not None:
                results.append(_json_mapping(row[14], field="result"))
        provider_health = "dark"
        if latest is not None and latest[0] is not None:
            provider_health = "ready" if latest[1] - latest[0] <= timedelta(minutes=15) else "stale"
        return DurableVerticalAProjection(
            options_requests=tuple(requests),
            results=tuple(results),
            provider_health=provider_health,
        )


def build_postgres_vertical_a_authority(
    settings: Settings,
) -> PostgresVerticalAAuthority | None:
    """Mount only when PostgreSQL is configured; all I/O remains lazy."""

    if not settings.database.enabled or settings.database.url is None:
        return None
    if not settings.database.url.get_secret_value().strip():
        return None
    return PostgresVerticalAAuthority(settings)


__all__ = [
    "DurableVerticalAClaim",
    "DurableVerticalACompleted",
    "DurableVerticalAProjection",
    "DurableVerticalASeedReceipt",
    "PostgresVerticalAAuthority",
    "VERTICAL_A_DURABLE_SCHEMA_VERSION",
    "VerticalAAdmissionBinding",
    "VerticalADurableAuthorityError",
    "build_postgres_vertical_a_authority",
    "vertical_a_runtime_security_is_ready_on_connection",
    "vertical_a_runtime_security_ready",
    "vertical_a_schema_is_ready_on_connection",
]
