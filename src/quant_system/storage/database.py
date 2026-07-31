"""Optional PostgreSQL connection helper for local metadata mirrors.

This module deliberately avoids a connection pool and an ORM. The platform is a
single-user local service, so short-lived ``psycopg`` connections (mirroring the
DuckDB cache style in ``storage/options_cache.py``) are simpler and survive a
container restart without stale pooled handles. The whole layer is optional:
``get_database`` returns ``None`` when ``QS_DATABASE_ENABLED`` is false or no URL
is configured, and every caller must treat ``None`` as "use files/live upstreams".
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg
from psycopg.pq import TransactionStatus

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

log = logging.getLogger(__name__)

# Schema the migrations create. Keep table details in scripts/sql/*.sql.
SCHEMA = "quant_system"
DEFAULT_FAILURE_COOLDOWN_SECONDS = 30.0
MAX_OPTIONAL_CONNECT_TIMEOUT_SECONDS = 1
HERMES_SCHEMA_RUNTIME_GATE = "quant_system:hermes_schema_runtime_gate"


class DatabaseUnavailable(RuntimeError):
    """Raised when the optional database should be skipped temporarily."""


class Database:
    """Thin wrapper around per-operation psycopg connections."""

    def __init__(
        self,
        url: str,
        *,
        connect_timeout: int,
        failure_cooldown_seconds: float = DEFAULT_FAILURE_COOLDOWN_SECONDS,
    ) -> None:
        self._url = url
        self._connect_timeout = min(connect_timeout, MAX_OPTIONAL_CONNECT_TIMEOUT_SECONDS)
        self._failure_cooldown_seconds = failure_cooldown_seconds
        self._lock = threading.Lock()
        self._failure_until = 0.0
        self._last_error: str | None = None

    def _begin_connect(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now < self._failure_until:
                remaining = max(self._failure_until - now, 0.0)
                raise DatabaseUnavailable(f"database recently failed; retry in {remaining:.1f}s")

    def _finish_connect(self) -> None:
        with self._lock:
            self._failure_until = 0.0
            self._last_error = None

    def _mark_failure(self, exc: BaseException) -> None:
        with self._lock:
            self._failure_until = time.monotonic() + self._failure_cooldown_seconds
            self._last_error = f"{exc.__class__.__name__}: {exc}"

    def can_attempt_connect(self) -> bool:
        with self._lock:
            return time.monotonic() >= self._failure_until

    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        self._begin_connect()
        try:
            conn = psycopg.connect(
                self._url,
                connect_timeout=self._connect_timeout,
                autocommit=True,
            )
        except Exception as exc:
            self._mark_failure(exc)
            raise
        self._finish_connect()
        try:
            yield conn
        finally:
            conn.close()

    def healthy(self) -> bool:
        if not self.can_attempt_connect():
            return False
        try:
            with self.connect() as conn:
                conn.execute("SELECT 1")
            return True
        except DatabaseUnavailable as exc:
            log.debug("database health check skipped: %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001 - health probe must never raise
            self._mark_failure(exc)
            log.warning("database health check failed: %s", exc)
            return False


_database: Database | None = None
_database_key: tuple[str, int] | None = None


def get_database(settings: Settings) -> Database | None:
    """Return a cached ``Database`` if the DB layer is enabled, else ``None``."""
    global _database, _database_key

    db_settings = settings.database
    if not db_settings.enabled or db_settings.url is None:
        return None
    url = db_settings.url.get_secret_value().strip()
    if not url:
        return None

    key = (url, db_settings.connect_timeout_seconds)
    if _database is None or _database_key != key:
        _database = Database(url, connect_timeout=db_settings.connect_timeout_seconds)
        _database_key = key
    return _database


def reset_database_cache() -> None:
    """Drop the cached connection helper (used by tests that swap settings)."""
    global _database, _database_key
    _database = None
    _database_key = None


def _sql_dir() -> Path:
    # src/quant_system/storage/database.py -> repo root / scripts / sql
    return Path(__file__).resolve().parents[3] / "scripts" / "sql"


def run_migrations(database: Database, *, only: Collection[str] | None = None) -> None:
    """Apply ``scripts/sql/*.sql`` files in lexical order (idempotent).

    By default every migration file is applied. When ``only`` is given it is an
    explicit allowlist of file *names* (used by the fail-closed ``migrate``
    command); the runner applies just those files and raises ``ValueError`` if
    the allowlist matches nothing, so an authorized apply can never silently
    no-op or widen beyond its allowlist.
    """
    sql_dir = _sql_dir()
    files = sorted(sql_dir.glob("*.sql"))
    if only is not None:
        allowed = set(only)
        files = [path for path in files if path.name in allowed]
        if not files:
            raise ValueError("no allowlisted migration files matched")
    if not files:
        log.warning("no SQL migration files found under %s", sql_dir)
        return
    with database.connect() as conn:
        runtime_gate_acquired = False
        primary_error: BaseException | None = None
        try:
            conn.execute(
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                (HERMES_SCHEMA_RUNTIME_GATE,),
            )
            runtime_gate_acquired = True
            for path in files:
                sql = path.read_text(encoding="utf-8")
                # psycopg3 runs multiple statements via the simple query protocol
                # when no parameters are supplied.
                conn.execute(sql)
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            cleanup_error: BaseException | None = None
            try:
                transaction_left_open = conn.info.transaction_status != TransactionStatus.IDLE
                if transaction_left_open:
                    conn.rollback()
                    if primary_error is None:
                        cleanup_error = RuntimeError("migration left a database transaction open")
            except BaseException as exc:
                cleanup_error = exc
            if runtime_gate_acquired:
                try:
                    unlocked = conn.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                        (HERMES_SCHEMA_RUNTIME_GATE,),
                    ).fetchone()
                    if unlocked != (True,):
                        raise RuntimeError("migration runtime gate was not held during release")
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
                    else:
                        log.warning(
                            "also failed to release migration runtime gate: %s",
                            exc,
                        )
            if cleanup_error is not None:
                if primary_error is None:
                    raise cleanup_error
                log.warning(
                    "migration cleanup failed while preserving the primary error: %s",
                    cleanup_error,
                )
    log.info("applied %d SQL migration file(s)", len(files))


def list_migration_files(*, only: Collection[str] | None = None) -> list[str]:
    """Return the sorted migration file names, optionally intersected with ``only``.

    This is the dry-run view used by the ``migrate`` command: it names exactly
    which files an apply *would* touch without connecting anywhere.
    """
    names = sorted(path.name for path in _sql_dir().glob("*.sql"))
    if only is None:
        return names
    allowed = set(only)
    return [name for name in names if name in allowed]


_SCHEMA_FINGERPRINT_SQL = """
WITH target_schema AS (
    SELECT oid, nspname, nspowner, nspacl
    FROM pg_namespace
    WHERE nspname = %s
),
fingerprint_rows(kind, identity, definition) AS (
    SELECT
        'schema',
        quote_ident(s.nspname),
        jsonb_build_object(
            'owner', pg_get_userbyid(s.nspowner),
            'acl', COALESCE(
                (
                    SELECT jsonb_agg(item.acl::text ORDER BY item.acl::text)
                    FROM unnest(COALESCE(s.nspacl, acldefault('n', s.nspowner))) AS item(acl)
                ),
                '[]'::jsonb
            )
        )::text
    FROM target_schema AS s

    UNION ALL

    SELECT
        'relation',
        format('%%I.%%I', s.nspname, c.relname),
        jsonb_build_object(
            'kind', c.relkind,
            'owner', pg_get_userbyid(c.relowner),
            'persistence', c.relpersistence,
            'row_security', c.relrowsecurity,
            'force_row_security', c.relforcerowsecurity,
            'replica_identity', c.relreplident,
            'is_partition', c.relispartition,
            'partition_key', CASE WHEN c.relkind = 'p' THEN pg_get_partkeydef(c.oid) END,
            'partition_bound', CASE
                WHEN c.relispartition THEN pg_get_expr(c.relpartbound, c.oid, true)
            END,
            'access_method', am.amname,
            'tablespace', tablespace.spcname,
            'options', COALESCE(
                (
                    SELECT jsonb_agg(option.value ORDER BY option.value)
                    FROM unnest(c.reloptions) AS option(value)
                ),
                '[]'::jsonb
            ),
            'acl', COALESCE(
                (
                    SELECT jsonb_agg(item.acl::text ORDER BY item.acl::text)
                    FROM unnest(
                        COALESCE(
                            c.relacl,
                            acldefault(
                                (CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END)::"char",
                                c.relowner
                            )
                        )
                    ) AS item(acl)
                ),
                '[]'::jsonb
            )
        )::text
    FROM pg_class AS c
    JOIN target_schema AS s ON s.oid = c.relnamespace
    LEFT JOIN pg_am AS am ON am.oid = c.relam
    LEFT JOIN pg_tablespace AS tablespace ON tablespace.oid = c.reltablespace
    WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')

    UNION ALL

    SELECT
        'column',
        format('%%I.%%I.%%s:%%I', s.nspname, c.relname, a.attnum, a.attname),
        jsonb_build_object(
            'type', format_type(a.atttypid, a.atttypmod),
            'not_null', a.attnotnull,
            'identity', a.attidentity,
            'generated', a.attgenerated,
            'storage', a.attstorage,
            'compression', a.attcompression,
            'statistics_target', a.attstattarget,
            'collation', CASE
                WHEN collation_row.oid IS NOT NULL
                THEN format('%%I.%%I', collation_schema.nspname, collation_row.collname)
            END,
            'default', pg_get_expr(default_value.adbin, default_value.adrelid, true),
            'acl', COALESCE(
                (
                    SELECT jsonb_agg(item.acl::text ORDER BY item.acl::text)
                    FROM unnest(COALESCE(a.attacl, '{}'::aclitem[])) AS item(acl)
                ),
                '[]'::jsonb
            )
        )::text
    FROM pg_attribute AS a
    JOIN pg_class AS c ON c.oid = a.attrelid
    JOIN target_schema AS s ON s.oid = c.relnamespace
    LEFT JOIN pg_attrdef AS default_value
        ON default_value.adrelid = a.attrelid AND default_value.adnum = a.attnum
    LEFT JOIN pg_collation AS collation_row ON collation_row.oid = a.attcollation
    LEFT JOIN pg_namespace AS collation_schema
        ON collation_schema.oid = collation_row.collnamespace
    WHERE a.attnum > 0
      AND NOT a.attisdropped
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')

    UNION ALL

    SELECT
        'constraint',
        CASE
            WHEN constraint_row.conrelid <> 0
            THEN format('%%I.%%I.%%I', s.nspname, relation.relname, constraint_row.conname)
            ELSE format('%%I.%%I.%%I', s.nspname, domain_type.typname, constraint_row.conname)
        END,
        jsonb_build_object(
            'type', constraint_row.contype,
            'definition', pg_get_constraintdef(constraint_row.oid, true),
            'deferrable', constraint_row.condeferrable,
            'initially_deferred', constraint_row.condeferred,
            'validated', constraint_row.convalidated,
            'no_inherit', constraint_row.connoinherit
        )::text
    FROM pg_constraint AS constraint_row
    JOIN target_schema AS s ON s.oid = constraint_row.connamespace
    LEFT JOIN pg_class AS relation ON relation.oid = constraint_row.conrelid
    LEFT JOIN pg_type AS domain_type ON domain_type.oid = constraint_row.contypid

    UNION ALL

    SELECT
        'index',
        format('%%I.%%I', s.nspname, index_relation.relname),
        jsonb_build_object(
            'definition', pg_get_indexdef(index_row.indexrelid, 0, true),
            'unique', index_row.indisunique,
            'primary', index_row.indisprimary,
            'exclusion', index_row.indisexclusion,
            'immediate', index_row.indimmediate,
            'valid', index_row.indisvalid,
            'ready', index_row.indisready,
            'replica_identity', index_row.indisreplident,
            'clustered', index_row.indisclustered,
            'options', COALESCE(
                (
                    SELECT jsonb_agg(option.value ORDER BY option.value)
                    FROM unnest(index_relation.reloptions) AS option(value)
                ),
                '[]'::jsonb
            )
        )::text
    FROM pg_index AS index_row
    JOIN pg_class AS index_relation ON index_relation.oid = index_row.indexrelid
    JOIN pg_class AS table_relation ON table_relation.oid = index_row.indrelid
    JOIN target_schema AS s ON s.oid = table_relation.relnamespace

    UNION ALL

    SELECT
        'view',
        format('%%I.%%I', s.nspname, c.relname),
        pg_get_viewdef(c.oid, true)
    FROM pg_class AS c
    JOIN target_schema AS s ON s.oid = c.relnamespace
    WHERE c.relkind IN ('v', 'm')

    UNION ALL

    SELECT
        'sequence',
        format('%%I.%%I', s.nspname, c.relname),
        jsonb_build_object(
            'type', format_type(sequence_row.seqtypid, NULL),
            'start', sequence_row.seqstart,
            'increment', sequence_row.seqincrement,
            'maximum', sequence_row.seqmax,
            'minimum', sequence_row.seqmin,
            'cache', sequence_row.seqcache,
            'cycle', sequence_row.seqcycle
        )::text
    FROM pg_sequence AS sequence_row
    JOIN pg_class AS c ON c.oid = sequence_row.seqrelid
    JOIN target_schema AS s ON s.oid = c.relnamespace

    UNION ALL

    SELECT
        'trigger',
        format('%%I.%%I.%%I', s.nspname, c.relname, trigger_row.tgname),
        jsonb_build_object(
            'definition', pg_get_triggerdef(trigger_row.oid, true),
            'enabled', trigger_row.tgenabled,
            'internal', trigger_row.tgisinternal
        )::text
    FROM pg_trigger AS trigger_row
    JOIN pg_class AS c ON c.oid = trigger_row.tgrelid
    JOIN target_schema AS s ON s.oid = c.relnamespace
    WHERE NOT trigger_row.tgisinternal

    UNION ALL

    SELECT
        'rule',
        format('%%I.%%I.%%I', s.nspname, c.relname, rule_row.rulename),
        jsonb_build_object(
            'definition', pg_get_ruledef(rule_row.oid, true),
            'enabled', rule_row.ev_enabled
        )::text
    FROM pg_rewrite AS rule_row
    JOIN pg_class AS c ON c.oid = rule_row.ev_class
    JOIN target_schema AS s ON s.oid = c.relnamespace

    UNION ALL

    SELECT
        'function',
        format(
            '%%I.%%I(%%s)',
            s.nspname,
            function_row.proname,
            pg_get_function_identity_arguments(function_row.oid)
        ),
        jsonb_build_object(
            'kind', function_row.prokind,
            'definition', CASE
                WHEN function_row.prokind IN ('f', 'p')
                THEN pg_get_functiondef(function_row.oid)
            END,
            'result', pg_get_function_result(function_row.oid),
            'arguments', pg_get_function_arguments(function_row.oid),
            'source', function_row.prosrc,
            'binary', function_row.probin,
            'owner', pg_get_userbyid(function_row.proowner),
            'security_definer', function_row.prosecdef,
            'leakproof', function_row.proleakproof,
            'volatility', function_row.provolatile,
            'parallel', function_row.proparallel,
            'configuration', COALESCE(
                (
                    SELECT jsonb_agg(setting.value ORDER BY setting.value)
                    FROM unnest(function_row.proconfig) AS setting(value)
                ),
                '[]'::jsonb
            ),
            'acl', COALESCE(
                (
                    SELECT jsonb_agg(item.acl::text ORDER BY item.acl::text)
                    FROM unnest(
                        COALESCE(
                            function_row.proacl,
                            acldefault('f', function_row.proowner)
                        )
                    ) AS item(acl)
                ),
                '[]'::jsonb
            )
        )::text
    FROM pg_proc AS function_row
    JOIN target_schema AS s ON s.oid = function_row.pronamespace

    UNION ALL

    SELECT
        'policy',
        format('%%I.%%I.%%I', s.nspname, c.relname, policy_row.polname),
        jsonb_build_object(
            'permissive', policy_row.polpermissive,
            'command', policy_row.polcmd,
            'roles', COALESCE(
                (
                    SELECT jsonb_agg(
                        CASE
                            WHEN role_row.role_oid = 0 THEN 'PUBLIC'
                            ELSE pg_get_userbyid(role_row.role_oid)
                        END
                        ORDER BY CASE
                            WHEN role_row.role_oid = 0 THEN 'PUBLIC'
                            ELSE pg_get_userbyid(role_row.role_oid)
                        END
                    )
                    FROM unnest(policy_row.polroles) AS role_row(role_oid)
                ),
                '[]'::jsonb
            ),
            'using', pg_get_expr(policy_row.polqual, policy_row.polrelid, true),
            'with_check', pg_get_expr(policy_row.polwithcheck, policy_row.polrelid, true)
        )::text
    FROM pg_policy AS policy_row
    JOIN pg_class AS c ON c.oid = policy_row.polrelid
    JOIN target_schema AS s ON s.oid = c.relnamespace

    UNION ALL

    SELECT
        'type',
        format('%%I.%%I', s.nspname, type_row.typname),
        jsonb_build_object(
            'kind', type_row.typtype,
            'category', type_row.typcategory,
            'preferred', type_row.typispreferred,
            'defined', type_row.typisdefined,
            'not_null', type_row.typnotnull,
            'default', type_row.typdefault,
            'delimiter', type_row.typdelim,
            'owner', pg_get_userbyid(type_row.typowner),
            'acl', COALESCE(
                (
                    SELECT jsonb_agg(item.acl::text ORDER BY item.acl::text)
                    FROM unnest(
                        COALESCE(type_row.typacl, acldefault('T', type_row.typowner))
                    ) AS item(acl)
                ),
                '[]'::jsonb
            )
        )::text
    FROM pg_type AS type_row
    JOIN target_schema AS s ON s.oid = type_row.typnamespace

    UNION ALL

    SELECT
        'enum_label',
        format('%%I.%%I.%%s', s.nspname, type_row.typname, enum_row.enumsortorder),
        enum_row.enumlabel
    FROM pg_enum AS enum_row
    JOIN pg_type AS type_row ON type_row.oid = enum_row.enumtypid
    JOIN target_schema AS s ON s.oid = type_row.typnamespace

    UNION ALL

    SELECT
        'default_acl',
        format(
            '%%I.%%s.%%s',
            s.nspname,
            pg_get_userbyid(default_acl.defaclrole),
            default_acl.defaclobjtype
        ),
        COALESCE(
            (
                SELECT jsonb_agg(item.acl::text ORDER BY item.acl::text)::text
                FROM unnest(default_acl.defaclacl) AS item(acl)
            ),
            '[]'
        )
    FROM pg_default_acl AS default_acl
    JOIN target_schema AS s ON s.oid = default_acl.defaclnamespace
)
SELECT kind, identity, definition
FROM fingerprint_rows
ORDER BY kind, identity, definition
"""


def schema_fingerprint_on_connection(conn: psycopg.Connection) -> str:
    """Fingerprint the schema on the caller's already-guarded connection.

    Runtime authorities use this form after acquiring the shared schema gate in
    their transaction, so a migration cannot change catalog bytes between the
    fingerprint observation and the authority write.
    """
    rows = conn.execute(_SCHEMA_FINGERPRINT_SQL, (SCHEMA,)).fetchall()
    digest = hashlib.sha256()
    canonical_rows = sorted(
        tuple("" if value is None else str(value) for value in row) for row in rows
    )
    for row in canonical_rows:
        digest.update(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def schema_fingerprint(database: Database | None) -> str:
    """Read-only SHA-256 fingerprint of the ``quant_system`` schema contents.

    Used by the ``migrate`` command to prove an authorized apply changed only
    what it claimed (and that a dry-run / startup changed nothing). Returns a
    stable placeholder when the database is unavailable rather than raising.
    """
    if database is None:
        return "<db-disabled>"
    try:
        with database.connect() as conn:
            return schema_fingerprint_on_connection(conn)
    except Exception as exc:  # noqa: BLE001 - fingerprint is best-effort/observational
        log.warning("schema fingerprint unavailable: %s", exc)
        return "<unavailable>"
