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
from quant_system.hermes.dark_identity_profile import (
    DarkIdentityProfileError,
    require_server_managed_session_policy,
)
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

SESSION_REGISTRY_SCHEMA_VERSION = 3
HERMES_MIGRATOR_ROLE = "quant_migrator"
HERMES_RUNTIME_ROLE = "quant_runtime"
HERMES_READONLY_ROLE = "quant_readonly"
HERMES_SECURITY_SCHEMA_VERSION = 1

_HERMES_RLS_TABLES = (
    "app_users",
    "hermes_commands",
    "hermes_command_events",
    "hermes_outbox",
    "hermes_run_links",
    "hermes_command_workflow_bindings",
    "hermes_workspace_sessions",
)

_ROOT_USER_ID_SQL = "'00000000-0000-0000-0000-000000000001'::uuid"
_DIRECT_ROOT_POLICY_TABLES = {
    "hermes_command_workflow_bindings",
    "hermes_commands",
    "hermes_workspace_sessions",
}
_COMMAND_CHILD_POLICY_TABLES = {
    "hermes_command_events",
    "hermes_outbox",
    "hermes_run_links",
}
_SESSION_IMMUTABILITY_FUNCTION_BODY = """
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'Hermes workspace session rows are immutable once registered';
    END IF;

    IF NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.hermes_session_id IS DISTINCT FROM OLD.hermes_session_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.writer IS DISTINCT FROM OLD.writer
       OR NEW.provider_policy_digest IS DISTINCT FROM OLD.provider_policy_digest
       OR NEW.payload_ttl_days IS DISTINCT FROM OLD.payload_ttl_days
       OR NEW.creation_client_action_id IS DISTINCT FROM OLD.creation_client_action_id
       OR NEW.creation_action_digest IS DISTINCT FROM OLD.creation_action_digest
       OR NEW.parent_platform_session_id IS DISTINCT FROM OLD.parent_platform_session_id
       OR NEW.fork_point IS DISTINCT FROM OLD.fork_point
       OR NEW.source_channel IS DISTINCT FROM OLD.source_channel
       OR NEW.platform_session_id IS DISTINCT FROM OLD.platform_session_id
    THEN
        RAISE EXCEPTION
            'Hermes workspace session identity, lineage, action and payload policy are immutable';
    END IF;

    IF NEW.provision_state = 'leased'
       AND OLD.provision_state IN ('pending', 'retryable', 'leased')
       AND NEW.provision_version = OLD.provision_version + 1
       AND NEW.provision_attempt_count = OLD.provision_attempt_count + 1
       AND NEW.provision_lease_owner IS NOT NULL
       AND NEW.provision_lease_token IS NOT NULL
       AND NEW.provision_lease_until IS NOT NULL
       AND (
            OLD.provision_state <> 'leased'
            OR NEW.provision_lease_token IS DISTINCT FROM OLD.provision_lease_token
       )
       AND NEW.provision_next_attempt_at IS NULL
       AND NEW.provision_last_error_code IS NULL
       AND NEW.provisioning_receipt_digest IS NULL
       AND NEW.provisioned_at IS NULL
    THEN
        NULL;
    ELSIF OLD.provision_state = 'leased'
       AND NEW.provision_state IN ('retryable', 'ready', 'failed')
       AND NEW.provision_version = OLD.provision_version + 1
       AND NEW.provision_attempt_count = OLD.provision_attempt_count
       AND NEW.provision_lease_owner IS NULL
       AND NEW.provision_lease_token IS NULL
       AND NEW.provision_lease_until IS NULL
       AND (
            (
                NEW.provision_state = 'retryable'
                AND NEW.provision_next_attempt_at IS NOT NULL
                AND NEW.provision_last_error_code IS NOT NULL
                AND NEW.provisioning_receipt_digest IS NULL
                AND NEW.provisioned_at IS NULL
            )
            OR
            (
                NEW.provision_state = 'ready'
                AND NEW.provision_next_attempt_at IS NULL
                AND NEW.provision_last_error_code IS NULL
                AND NEW.provisioning_receipt_digest IS NOT NULL
                AND NEW.provisioned_at IS NOT NULL
            )
            OR
            (
                NEW.provision_state = 'failed'
                AND NEW.provision_next_attempt_at IS NULL
                AND NEW.provision_last_error_code IS NOT NULL
                AND NEW.provisioning_receipt_digest IS NULL
                AND NEW.provisioned_at IS NULL
            )
       )
    THEN
        NULL;
    ELSE
        RAISE EXCEPTION
            'Hermes workspace session provisioning requires an exact lease/CAS transition';
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
"""
_SESSION_TTL_CONSTRAINT = (
    "CHECK ((((kind = 'observed_external_session'::text) AND "
    "(payload_ttl_days IS NULL)) OR ((kind = 'web_managed_session'::text) "
    "AND (payload_ttl_days = 7))))"
)
_SESSION_CREATION_ACTION_CONSTRAINT = (
    "CHECK ((((creation_client_action_id IS NULL) AND "
    "(creation_action_digest IS NULL)) OR ((kind = "
    "'web_managed_session'::text) AND (creation_client_action_id IS NOT NULL) "
    "AND ((char_length(creation_client_action_id) >= 1) AND "
    "(char_length(creation_client_action_id) <= 200)) AND "
    "(creation_client_action_id ~ "
    "'^[A-Za-z0-9][A-Za-z0-9._:-]*$'::text) AND "
    "(creation_action_digest IS NOT NULL) AND "
    "(creation_action_digest ~ '^[0-9a-f]{64}$'::text))))"
)
SessionKind = Literal["observed_external_session", "web_managed_session"]
SessionWriter = Literal["external_channel", "web_control_plane"]
SourceChannel = Literal["discord", "historical", "web_managed"]
ProvisionState = Literal[
    "observed",
    "pending",
    "leased",
    "retryable",
    "ready",
    "failed",
]

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_HERMES_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_MANAGED_HERMES_ID_RE = re.compile(r"^web_[0-9a-f]{40}$")
_FORK_POINT_RE = re.compile(r"^message:[1-9][0-9]*$")


class HermesSessionRegistryUnavailable(RuntimeError):
    """Raised when the session registry cannot safely accept identity."""


class HermesSessionRegistryConflict(RuntimeError):
    """Raised when an identity key is reused for different session facts."""


class HermesSessionActionConflict(HermesSessionRegistryConflict):
    """Raised when one create/fork action key is reused with another digest."""


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
    payload_ttl_days: int | None
    creation_client_action_id: str | None
    creation_action_digest: str | None
    writer: SessionWriter
    provisioning_state: ProvisionState
    provisioning_version: int
    provisioning_attempt_count: int
    provisioning_lease_owner: str | None
    provisioning_lease_token: UUID | None
    provisioning_lease_until: datetime | None
    provisioning_next_attempt_at: datetime | None
    provisioning_last_error_code: str | None
    provisioning_receipt_digest: str | None
    provisioned_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @property
    def web_writable(self) -> bool:
        return (
            self.kind == "web_managed_session"
            and self.writer == "web_control_plane"
            and self.provisioning_state == "ready"
        )


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
    payload_ttl_days: int | None = None
    creation_client_action_id: str | None = None
    creation_action_digest: str | None = None
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
    creation_fields_present = (
        request.creation_client_action_id is not None,
        request.creation_action_digest is not None,
    )
    if creation_fields_present[0] != creation_fields_present[1]:
        raise HermesSessionRegistryValidationError(
            "creation action id and digest must be supplied together"
        )
    if request.creation_client_action_id is not None and (
        _ACTION_ID_RE.fullmatch(request.creation_client_action_id) is None
        or request.creation_action_digest is None
        or _DIGEST_RE.fullmatch(request.creation_action_digest) is None
    ):
        raise HermesSessionRegistryValidationError("invalid creation action identity")
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
        if request.payload_ttl_days is not None:
            raise HermesSessionRegistryValidationError(
                "observed_external_session cannot carry payload_ttl_days"
            )
        if request.creation_client_action_id is not None:
            raise HermesSessionRegistryValidationError(
                "observed_external_session cannot carry creation action identity"
            )
        return "external_channel"

    if request.kind != "web_managed_session":
        raise HermesSessionRegistryValidationError("invalid session kind")
    if request.creation_client_action_id is None:
        raise HermesSessionRegistryValidationError(
            "web_managed_session requires creation action identity"
        )
    if (
        request.creation_action_digest is None
        or _MANAGED_HERMES_ID_RE.fullmatch(request.hermes_session_id) is None
        or request.hermes_session_id != f"web_{request.creation_action_digest[:40]}"
    ):
        raise HermesSessionRegistryValidationError(
            "web_managed_session requires its exact action-derived Hermes Session"
        )
    if (
        request.provider_policy_digest is None
        or _DIGEST_RE.fullmatch(request.provider_policy_digest) is None
    ):
        raise HermesSessionRegistryValidationError(
            "web_managed_session requires provider_policy_digest"
        )
    try:
        require_server_managed_session_policy(
            provider_policy_digest=request.provider_policy_digest,
            payload_ttl_days=request.payload_ttl_days,
        )
    except DarkIdentityProfileError as exc:
        raise HermesSessionRegistryValidationError(
            "web_managed_session requires the server-owned payload policy"
        ) from exc
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
        if request.fork_point is None or _FORK_POINT_RE.fullmatch(request.fork_point) is None:
            raise HermesSessionRegistryValidationError(
                "forked web_managed_session requires exact message:<id> fork_point"
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
        payload_ttl_days=int(row[9]) if row[9] is not None else None,
        creation_client_action_id=str(row[10]) if row[10] is not None else None,
        creation_action_digest=str(row[11]) if row[11] is not None else None,
        writer=row[12],  # type: ignore[arg-type]
        provisioning_state=row[13],  # type: ignore[arg-type]
        provisioning_version=int(row[14]),
        provisioning_attempt_count=int(row[15]),
        provisioning_lease_owner=str(row[16]) if row[16] is not None else None,
        provisioning_lease_token=UUID(str(row[17])) if row[17] is not None else None,
        provisioning_lease_until=row[18],  # type: ignore[arg-type]
        provisioning_next_attempt_at=row[19],  # type: ignore[arg-type]
        provisioning_last_error_code=(str(row[20]) if row[20] is not None else None),
        provisioning_receipt_digest=(str(row[21]) if row[21] is not None else None),
        provisioned_at=row[22],  # type: ignore[arg-type]
        created_at=row[23],  # type: ignore[arg-type]
        updated_at=row[24],  # type: ignore[arg-type]
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
    payload_ttl_days,
    creation_client_action_id,
    creation_action_digest,
    writer,
    provision_state,
    provision_version,
    provision_attempt_count,
    provision_lease_owner,
    provision_lease_token,
    provision_lease_until,
    provision_next_attempt_at,
    provision_last_error_code,
    provisioning_receipt_digest,
    provisioned_at,
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
            ),
            EXISTS (
                SELECT 1
                FROM pg_attribute
                WHERE attrelid = %s::regclass
                  AND attname = 'payload_ttl_days'
                  AND atttypid = 'smallint'::regtype
                  AND NOT attisdropped
            ),
            EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_hermes_workspace_session_payload_ttl'
                  AND conrelid = %s::regclass
                  AND contype = 'c'
                  AND convalidated
                  AND pg_get_constraintdef(oid) = %s
            ),
            EXISTS (
                SELECT 1
                FROM pg_attribute
                WHERE attrelid = %s::regclass
                  AND attname = 'creation_client_action_id'
                  AND atttypid = 'text'::regtype
                  AND NOT attnotnull
                  AND NOT attisdropped
            ),
            EXISTS (
                SELECT 1
                FROM pg_attribute
                WHERE attrelid = %s::regclass
                  AND attname = 'creation_action_digest'
                  AND atttypid = 'character'::regtype
                  AND atttypmod = 68
                  AND NOT attnotnull
                  AND NOT attisdropped
            ),
            EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_hermes_workspace_session_creation_action'
                  AND conrelid = %s::regclass
                  AND contype = 'c'
                  AND convalidated
                  AND pg_get_constraintdef(oid) = %s
            ),
            EXISTS (
                SELECT 1
                FROM pg_index AS index
                JOIN pg_class AS relation ON relation.oid = index.indexrelid
                WHERE relation.relname =
                    'uq_hermes_workspace_session_creation_action'
                  AND index.indrelid = %s::regclass
                  AND index.indisunique
                  AND index.indisvalid
                  AND index.indisready
                  AND pg_get_indexdef(index.indexrelid) = %s
            )
        """,
        (
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
            _SESSION_TTL_CONSTRAINT,
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
            _SESSION_CREATION_ACTION_CONSTRAINT,
            f"{SCHEMA}.hermes_workspace_sessions",
            (
                "CREATE UNIQUE INDEX "
                "uq_hermes_workspace_session_creation_action ON "
                f"{SCHEMA}.hermes_workspace_sessions USING btree "
                "(owner_user_id, workspace_id, creation_client_action_id) "
                "WHERE (creation_client_action_id IS NOT NULL)"
            ),
        ),
    ).fetchone()
    if required is None or not all(bool(value) for value in required):
        return False

    provisioning_required = conn.execute(
        """
        SELECT
            (
                SELECT count(*) = 10
                FROM pg_attribute
                WHERE attrelid = %s::regclass
                  AND attname = ANY(%s)
                  AND NOT attisdropped
            ),
            (
                SELECT count(*) = 7
                FROM pg_constraint
                WHERE conrelid = %s::regclass
                  AND conname = ANY(%s)
                  AND contype = 'c'
                  AND convalidated
            ),
            EXISTS (
                SELECT 1
                FROM pg_index AS index
                JOIN pg_class AS relation ON relation.oid = index.indexrelid
                WHERE relation.relname =
                    'idx_hermes_workspace_sessions_provision_claim'
                  AND index.indrelid = %s::regclass
                  AND index.indisvalid
                  AND index.indisready
                  AND index.indpred IS NOT NULL
            )
        """,
        (
            f"{SCHEMA}.hermes_workspace_sessions",
            [
                "provision_state",
                "provision_version",
                "provision_attempt_count",
                "provision_lease_owner",
                "provision_lease_token",
                "provision_lease_until",
                "provision_next_attempt_at",
                "provision_last_error_code",
                "provisioning_receipt_digest",
                "provisioned_at",
            ],
            f"{SCHEMA}.hermes_workspace_sessions",
            [
                "ck_hermes_workspace_session_provision_state",
                "ck_hermes_workspace_session_provision_counters",
                "ck_hermes_workspace_session_provision_error",
                "ck_hermes_workspace_session_provision_receipt",
                "ck_hermes_workspace_session_provision_shape",
                "ck_hermes_workspace_session_managed_exact_identity",
                "ck_hermes_workspace_session_exact_fork_point",
            ],
            f"{SCHEMA}.hermes_workspace_sessions",
        ),
    ).fetchone()
    if provisioning_required is None or not all(bool(value) for value in provisioning_required):
        return False

    trigger_signature = conn.execute(
        """
        SELECT
            trigger.tgtype,
            trigger.tgenabled,
            procedure.prosrc,
            procedure.prosecdef,
            procedure.provolatile,
            language.lanname
        FROM pg_trigger AS trigger
        JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language ON language.oid = procedure.prolang
        WHERE trigger.tgrelid = %s::regclass
          AND trigger.tgname = 'trg_hermes_workspace_session_immutability'
          AND NOT trigger.tgisinternal
          AND namespace.nspname = %s
          AND procedure.proname = 'reject_hermes_external_session_mutation'
        """,
        (f"{SCHEMA}.hermes_workspace_sessions", SCHEMA),
    ).fetchone()
    if trigger_signature is None:
        return False
    trigger_type, enabled, body, security_definer, volatility, language = trigger_signature
    return (
        int(trigger_type) == 27  # BEFORE + ROW + UPDATE + DELETE
        and str(enabled) == "A"
        and " ".join(str(body).split()) == " ".join(_SESSION_IMMUTABILITY_FUNCTION_BODY.split())
        and security_definer is False
        and str(volatility) == "v"
        and str(language) == "plpgsql"
    )


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


def hermes_runtime_security_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    """Verify the V4-R role/RLS signature and the effective login principal."""

    if not session_registry_schema_is_ready_on_connection(conn):
        return False
    row = conn.execute(
        f"""
        SELECT
            EXISTS (
                SELECT 1
                FROM {SCHEMA}.hermes_security_meta
                WHERE singleton IS TRUE
                  AND schema_version = %s
            ),
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
            pg_has_role(session_user, %s, 'MEMBER'),
            NOT pg_has_role(session_user, %s, 'MEMBER'),
            has_schema_privilege(session_user, %s, 'USAGE'),
            NOT has_schema_privilege(session_user, %s, 'CREATE'),
            (
                SELECT count(*) = %s
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = %s
                  AND relation.relname = ANY(%s)
                  AND relation.relrowsecurity
                  AND relation.relforcerowsecurity
            ),
            (
                has_table_privilege(session_user, %s, 'SELECT')
                AND has_table_privilege(session_user, %s, 'INSERT')
                AND has_table_privilege(session_user, %s, 'UPDATE')
            ),
            NOT has_table_privilege(session_user, %s, 'DELETE'),
            (
                has_table_privilege(session_user, %s, 'SELECT')
                AND has_table_privilege(session_user, %s, 'INSERT')
            ),
            (
                NOT has_table_privilege(session_user, %s, 'UPDATE')
                AND NOT has_table_privilege(session_user, %s, 'DELETE')
            )
        """,
        (
            HERMES_SECURITY_SCHEMA_VERSION,
            [HERMES_MIGRATOR_ROLE, HERMES_RUNTIME_ROLE, HERMES_READONLY_ROLE],
            HERMES_RUNTIME_ROLE,
            HERMES_MIGRATOR_ROLE,
            SCHEMA,
            SCHEMA,
            len(_HERMES_RLS_TABLES),
            SCHEMA,
            list(_HERMES_RLS_TABLES),
            f"{SCHEMA}.hermes_commands",
            f"{SCHEMA}.hermes_commands",
            f"{SCHEMA}.hermes_commands",
            f"{SCHEMA}.hermes_commands",
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
            f"{SCHEMA}.hermes_workspace_sessions",
        ),
    ).fetchone()
    if row is None or not all(bool(value) for value in row):
        return False

    policy_rows = conn.execute(
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
                JOIN pg_roles AS role ON role.oid = policy_role.role_oid
                ORDER BY role.rolname::text
            )
        FROM pg_policy AS policy
        JOIN pg_class AS relation ON relation.oid = policy.polrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
          AND policy.polname = ANY(%s)
        """,
        (
            SCHEMA,
            list(_HERMES_RLS_TABLES),
            ["v4r_root_scope", "v4r_migrator_all"],
        ),
    ).fetchall()
    expected_keys = {
        (table_name, policy_name)
        for table_name in _HERMES_RLS_TABLES
        for policy_name in ("v4r_root_scope", "v4r_migrator_all")
    }
    observed_keys = {(str(item[0]), str(item[1])) for item in policy_rows}
    if observed_keys != expected_keys or len(policy_rows) != len(expected_keys):
        return False

    for table_name, policy_name, command, using, with_check, roles in policy_rows:
        if str(command) != "*":
            return False
        normalized_using = " ".join(str(using).split())
        normalized_check = " ".join(str(with_check).split())
        normalized_roles = tuple(str(role) for role in roles)
        if policy_name == "v4r_migrator_all":
            if (
                normalized_using != "true"
                or normalized_check != "true"
                or normalized_roles != (HERMES_MIGRATOR_ROLE,)
            ):
                return False
            continue

        if normalized_roles != (
            HERMES_READONLY_ROLE,
            HERMES_RUNTIME_ROLE,
        ):
            return False
        expected_expression = _expected_root_policy_expression(str(table_name))
        if normalized_using != expected_expression or normalized_check != expected_expression:
            return False
    return True


def _expected_root_policy_expression(table_name: str) -> str:
    if table_name == "app_users":
        return f"(id = {_ROOT_USER_ID_SQL})"
    if table_name in _DIRECT_ROOT_POLICY_TABLES:
        return f"(owner_user_id = {_ROOT_USER_ID_SQL})"
    if table_name in _COMMAND_CHILD_POLICY_TABLES:
        return (
            f"(EXISTS ( SELECT 1 FROM {SCHEMA}.hermes_commands command "
            f"WHERE ((command.command_id = {table_name}.command_id) AND "
            f"(command.owner_user_id = {_ROOT_USER_ID_SQL}))))"
        )
    raise ValueError(f"unsupported V4-R policy table: {table_name}")


def hermes_runtime_security_ready(settings: Settings) -> bool:
    """Return whether this process uses the constrained V4-R runtime role."""

    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            return hermes_runtime_security_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error, TypeError, ValueError):
        return False


def _facts_match(
    existing: WorkspaceSessionRecord,
    request: RegisterWorkspaceSession,
    writer: SessionWriter,
) -> bool:
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
        and existing.payload_ttl_days == request.payload_ttl_days
        and existing.creation_client_action_id == request.creation_client_action_id
        and existing.creation_action_digest == request.creation_action_digest
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
            if request.creation_client_action_id is not None:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (
                        "hermes-session-action:"
                        f"{request.owner_user_id}:"
                        f"{request.workspace_id}:"
                        f"{request.creation_client_action_id}",
                    ),
                )
                action_row = conn.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM {SCHEMA}.hermes_workspace_sessions
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND creation_client_action_id = %s
                    """,
                    (
                        request.owner_user_id,
                        request.workspace_id,
                        request.creation_client_action_id,
                    ),
                ).fetchone()
                if action_row is not None:
                    action_record = _row_to_record(action_row)
                    if not _facts_match(action_record, request, writer):
                        raise HermesSessionActionConflict(
                            "session creation action key reused with different facts"
                        )
                    return action_record, False
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
                    payload_ttl_days,
                    creation_client_action_id,
                    creation_action_digest,
                    writer,
                    provision_state,
                    provision_version,
                    provision_attempt_count
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, 0, 0
                )
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
                    request.payload_ttl_days,
                    request.creation_client_action_id,
                    request.creation_action_digest,
                    writer,
                    ("observed" if request.kind == "observed_external_session" else "pending"),
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
        raise HermesSessionRegistryUnavailable("Hermes session registry lookup failed") from exc


def require_web_writable_session(
    settings: Settings,
    *,
    platform_session_id: str,
) -> WorkspaceSessionRecord:
    """Application-layer fail-closed gate for external/read-only sessions."""

    record = get_workspace_session(settings, platform_session_id=platform_session_id)
    if not record.web_writable:
        raise HermesSessionNotWritable("session is not a provisioned web_managed_session")
    return record
