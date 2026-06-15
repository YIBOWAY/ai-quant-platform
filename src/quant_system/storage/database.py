"""Optional PostgreSQL connection helper for the local run index.

This module deliberately avoids a connection pool and an ORM. The platform is a
single-user local service, so short-lived ``psycopg`` connections (mirroring the
DuckDB cache style in ``storage/options_cache.py``) are simpler and survive a
container restart without stale pooled handles. The whole layer is optional:
``get_database`` returns ``None`` when ``QS_DATABASE_ENABLED`` is false or no URL
is configured, and every caller must treat ``None`` as "use the filesystem".
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

log = logging.getLogger(__name__)

# Schema/table the migrations create. Kept in sync with scripts/sql/001_runs_index.sql.
SCHEMA = "quant_system"
DEFAULT_FAILURE_COOLDOWN_SECONDS = 30.0
MAX_OPTIONAL_CONNECT_TIMEOUT_SECONDS = 1


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
                raise DatabaseUnavailable(
                    f"database recently failed; retry in {remaining:.1f}s"
                )

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


def run_migrations(database: Database) -> None:
    """Apply every ``scripts/sql/*.sql`` file in lexical order (idempotent)."""
    sql_dir = _sql_dir()
    files = sorted(sql_dir.glob("*.sql"))
    if not files:
        log.warning("no SQL migration files found under %s", sql_dir)
        return
    with database.connect() as conn:
        for path in files:
            sql = path.read_text(encoding="utf-8")
            # psycopg3 runs multiple statements via the simple query protocol
            # when no parameters are supplied.
            conn.execute(sql)
    log.info("applied %d SQL migration file(s)", len(files))
