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


class Database:
    """Thin wrapper around per-operation psycopg connections."""

    def __init__(self, url: str, *, connect_timeout: int) -> None:
        self._url = url
        self._connect_timeout = connect_timeout

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        conn = psycopg.connect(
            self._url,
            connect_timeout=self._connect_timeout,
            autocommit=True,
        )
        try:
            yield conn
        finally:
            conn.close()

    def healthy(self) -> bool:
        try:
            with self.connect() as conn:
                conn.execute("SELECT 1")
            return True
        except Exception as exc:  # noqa: BLE001 - health probe must never raise
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
