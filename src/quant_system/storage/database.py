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
            rows = conn.execute(
                """
                SELECT c.relname
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE n.nspname = %s
                  AND c.relkind IN ('r', 'v', 'm', 'S', 'i')
                ORDER BY c.relname
                """,
                (SCHEMA,),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - fingerprint is best-effort/observational
        log.warning("schema fingerprint unavailable: %s", exc)
        return "<unavailable>"
    digest = hashlib.sha256()
    for (name,) in rows:
        digest.update(str(name).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()
