from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from quant_system.storage import database as db

RUNTIME_GATE = "quant_system:hermes_schema_runtime_gate"


def _postgres_test_url() -> str:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    dbname = conninfo_to_dict(url).get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            f"QS_TEST_DATABASE_URL must point at a throwaway test database (got {dbname!r})"
        )
    return url


def test_run_migrations_only_filters_to_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # V1.1: the explicit migrate command selects files via ``only``; the runner
    # must apply just those files and reject an allowlist that matches nothing.
    (tmp_path / "001_alpha.sql").write_text("SELECT 'alpha';", encoding="utf-8")
    (tmp_path / "002_beta.sql").write_text("SELECT 'beta';", encoding="utf-8")
    (tmp_path / "003_gamma.sql").write_text("SELECT 'gamma';", encoding="utf-8")
    monkeypatch.setattr(db, "_sql_dir", lambda: tmp_path)

    executed: list[str] = []

    class Connection:
        def __init__(self) -> None:
            self.info = SimpleNamespace(transaction_status=psycopg.pq.TransactionStatus.IDLE)
            self.last_query = ""

        def execute(self, query: str, _params=None):
            self.last_query = query
            if "pg_advisory_lock" not in query and "pg_advisory_unlock" not in query:
                executed.append(query)
            return self

        def fetchone(self) -> tuple[bool]:
            return (True,)

    class Database:
        @contextmanager
        def connect(self):
            yield Connection()

    db.run_migrations(Database(), only={"002_beta.sql"})  # type: ignore[arg-type]
    assert executed == ["SELECT 'beta';"]


def test_run_migrations_only_rejects_unmatched_allowlist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "001_alpha.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(db, "_sql_dir", lambda: tmp_path)

    class Database:  # pragma: no cover - connect must not be reached
        @contextmanager
        def connect(self):
            raise AssertionError("connect must not run when the allowlist matches nothing")
            yield

    with pytest.raises(ValueError, match="no allowlisted migration files matched"):
        db.run_migrations(Database(), only={"999_missing.sql"})  # type: ignore[arg-type]


class _ObservedDatabase(db.Database):
    def __init__(self, url: str) -> None:
        super().__init__(url, connect_timeout=1, failure_cooldown_seconds=0)
        self.connected = threading.Event()
        self.backend_pid: int | None = None

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self._url, connect_timeout=1, autocommit=True) as conn:
            self.backend_pid = conn.info.backend_pid
            self.connected.set()
            yield conn


class _RetainedDatabase(db.Database):
    def __init__(self, url: str) -> None:
        super().__init__(url, connect_timeout=1, failure_cooldown_seconds=0)
        self.connection: psycopg.Connection | None = None

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        self.connection = psycopg.connect(
            self._url,
            connect_timeout=1,
            autocommit=True,
        )
        yield self.connection


def _wait_until_backend_waits_for_advisory_lock(
    url: str,
    backend_pid: int,
    *,
    migration_thread: threading.Thread,
    migration_errors: list[BaseException],
) -> None:
    deadline = time.monotonic() + 3
    with psycopg.connect(url, connect_timeout=1, autocommit=True) as observer:
        while time.monotonic() < deadline:
            if migration_errors:
                raise AssertionError(
                    "migration backend failed before blocking"
                ) from migration_errors[0]
            if not migration_thread.is_alive():
                pytest.fail("migration backend exited before reaching its blocking SQL statement")
            row = observer.execute(
                "SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE pid = %s",
                (backend_pid,),
            ).fetchone()
            if row == ("Lock", "advisory"):
                return
            time.sleep(0.01)
    pytest.fail("migration backend never reached its blocking SQL statement")


def test_database_health_failure_uses_cooldown(monkeypatch) -> None:
    calls = 0
    connect_timeouts: list[int] = []

    def fail_connect(*_args, **kwargs):
        nonlocal calls
        calls += 1
        connect_timeouts.append(kwargs["connect_timeout"])
        raise OSError("database is down")

    monkeypatch.setattr(db.psycopg, "connect", fail_connect)
    database = db.Database(
        "postgresql://quant:quantpass@127.0.0.1:5432/quantplatform",
        connect_timeout=5,
        failure_cooldown_seconds=60,
    )

    assert database.healthy() is False
    assert database.healthy() is False
    assert calls == 1
    assert connect_timeouts == [1]


def _fingerprint_database(rows: list[tuple[str, str, str]]):
    class Cursor:
        def fetchall(self) -> list[tuple[str, str, str]]:
            return rows

    class Connection:
        def execute(self, _query: str, _params: object = None) -> Cursor:
            return Cursor()

    class Database:
        @contextmanager
        def connect(self):
            yield Connection()

    return Database()


def test_schema_fingerprint_is_order_independent_and_content_sensitive() -> None:
    catalog = [
        ("column", "quant_system.runs.status", "text/not-null"),
        ("trigger", "quant_system.runs.append_only", "enabled=always"),
        ("policy", "quant_system.runs.runtime", "role=quant_runtime/read-only"),
    ]

    original = db.schema_fingerprint(_fingerprint_database(catalog))  # type: ignore[arg-type]
    reordered = db.schema_fingerprint(  # type: ignore[arg-type]
        _fingerprint_database(list(reversed(catalog)))
    )
    trigger_mode_changed = db.schema_fingerprint(  # type: ignore[arg-type]
        _fingerprint_database(
            [
                catalog[0],
                ("trigger", "quant_system.runs.append_only", "enabled=origin"),
                catalog[2],
            ]
        )
    )

    assert original == reordered
    assert original != trigger_mode_changed


@pytest.mark.pg
def test_schema_fingerprint_detects_postgres_schema_semantics() -> None:
    url = _postgres_test_url()
    database = db.Database(url, connect_timeout=1, failure_cooldown_seconds=0)
    suffix = uuid.uuid4().hex[:12]
    table_name = f"schema_fp_{suffix}"
    function_name = f"schema_fp_guard_{suffix}"
    index_name = f"schema_fp_value_idx_{suffix}"
    trigger_name = f"schema_fp_trigger_{suffix}"
    policy_name = f"schema_fp_policy_{suffix}"
    constraint_name = f"schema_fp_value_nonnegative_{suffix}"
    table = f'{db.SCHEMA}."{table_name}"'
    function = f'{db.SCHEMA}."{function_name}"'
    schema_preexisted = True

    try:
        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            schema_preexisted = (
                conn.execute(
                    "SELECT 1 FROM pg_namespace WHERE nspname = %s",
                    (db.SCHEMA,),
                ).fetchone()
                is not None
            )
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {db.SCHEMA}")
            conn.execute(
                f"CREATE TABLE {table} ("
                "id BIGSERIAL PRIMARY KEY, "
                "identity_id BIGINT GENERATED ALWAYS AS IDENTITY, "
                "value INTEGER)"
            )
            conn.execute(f'CREATE INDEX "{index_name}" ON {table} (value)')
            conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            conn.execute(
                f'CREATE POLICY "{policy_name}" ON {table} USING (id > 0)'
            )
            conn.execute(
                f"""
                CREATE FUNCTION {function}() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RETURN NEW;
                END
                $$
                """
            )
            conn.execute(
                f'CREATE TRIGGER "{trigger_name}" '
                f"BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"
            )

        baseline = db.schema_fingerprint(database)
        assert baseline not in {"<db-disabled>", "<unavailable>"}
        assert db.schema_fingerprint(database) == baseline

        # NULL relacl and an explicit owner-only default ACL are semantically
        # equivalent for both BIGSERIAL and identity-owned sequences.
        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(
                f'GRANT ALL PRIVILEGES ON SEQUENCE {db.SCHEMA}."{table_name}_id_seq" '
                "TO CURRENT_USER"
            )
            conn.execute(
                f'GRANT ALL PRIVILEGES ON SEQUENCE '
                f'{db.SCHEMA}."{table_name}_identity_id_seq" TO CURRENT_USER'
            )
        assert db.schema_fingerprint(database) == baseline

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN note TEXT")
        after_column = db.schema_fingerprint(database)
        assert after_column != baseline

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(
                f'ALTER TABLE {table} ADD CONSTRAINT "{constraint_name}" '
                "CHECK (value >= 0)"
            )
        after_constraint = db.schema_fingerprint(database)
        assert after_constraint != after_column

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(f'DROP INDEX {db.SCHEMA}."{index_name}"')
            conn.execute(
                f'CREATE INDEX "{index_name}" ON {table} (value DESC) '
                "WHERE value IS NOT NULL"
            )
        after_index = db.schema_fingerprint(database)
        assert after_index != after_constraint

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(
                f"CREATE OR REPLACE FUNCTION {function}() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN NEW.value := COALESCE(NEW.value, 0); "
                "RETURN NEW; END $$"
            )
        after_function = db.schema_fingerprint(database)
        assert after_function != after_index

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(
                f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER "
                f'"{trigger_name}"'
            )
        trigger_always = db.schema_fingerprint(database)
        assert trigger_always != after_function

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(f'ALTER TABLE {table} ENABLE TRIGGER "{trigger_name}"')
        trigger_origin = db.schema_fingerprint(database)
        assert trigger_origin != trigger_always

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            conn.execute(
                f'ALTER POLICY "{policy_name}" ON {table} USING (id >= 0)'
            )
        after_policy = db.schema_fingerprint(database)
        assert after_policy != trigger_origin

        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            public_has_select = conn.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_class AS relation
                    CROSS JOIN LATERAL aclexplode(
                        COALESCE(relation.relacl, acldefault('r', relation.relowner))
                    ) AS grant_row
                    WHERE relation.oid = %s::regclass
                      AND grant_row.grantee = 0
                      AND grant_row.privilege_type = 'SELECT'
                )
                """,
                (table,),
            ).fetchone()
            assert public_has_select is not None
            if public_has_select[0]:
                conn.execute(f"REVOKE SELECT ON {table} FROM PUBLIC")
            else:
                conn.execute(f"GRANT SELECT ON {table} TO PUBLIC")
        after_grant = db.schema_fingerprint(database)
        assert after_grant != after_policy
    finally:
        with psycopg.connect(url, connect_timeout=1, autocommit=True) as conn:
            schema_exists = conn.execute(
                "SELECT 1 FROM pg_namespace WHERE nspname = %s",
                (db.SCHEMA,),
            ).fetchone()
            if schema_exists is not None:
                conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
                conn.execute(f"DROP FUNCTION IF EXISTS {function}() CASCADE")
                if not schema_preexisted:
                    # Another parallel PostgreSQL test may now share the schema.
                    with suppress(psycopg.errors.DependentObjectsStillExist):
                        conn.execute(f"DROP SCHEMA IF EXISTS {db.SCHEMA}")


def test_successful_migration_reports_runtime_gate_release_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "001_success.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(db, "_sql_dir", lambda: tmp_path)

    class Connection:
        def __init__(self) -> None:
            self.info = SimpleNamespace(transaction_status=psycopg.pq.TransactionStatus.IDLE)
            self.last_query = ""

        def execute(self, query: str, _params=None):
            self.last_query = query
            return self

        def fetchone(self) -> tuple[bool]:
            return ("pg_advisory_unlock" not in self.last_query,)

    class Database:
        @contextmanager
        def connect(self):
            yield Connection()

    with pytest.raises(RuntimeError, match="runtime gate was not held"):
        db.run_migrations(Database())  # type: ignore[arg-type]


def test_successful_migration_cannot_silently_leave_transaction_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "001_missing_commit.sql").write_text(
        "BEGIN; SELECT 1;",
        encoding="utf-8",
    )
    monkeypatch.setattr(db, "_sql_dir", lambda: tmp_path)

    class Connection:
        def __init__(self) -> None:
            self.info = SimpleNamespace(transaction_status=psycopg.pq.TransactionStatus.IDLE)
            self.last_query = ""
            self.rollback_attempted = False

        def execute(self, query: str, _params=None):
            self.last_query = query
            if query == "BEGIN; SELECT 1;":
                self.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
            return self

        def fetchone(self) -> tuple[bool]:
            return (True,)

        def rollback(self) -> None:
            self.rollback_attempted = True
            self.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    connection = Connection()

    class Database:
        @contextmanager
        def connect(self):
            yield connection

    with pytest.raises(RuntimeError, match="left a database transaction open"):
        db.run_migrations(Database())  # type: ignore[arg-type]

    assert connection.rollback_attempted is True
    assert connection.info.transaction_status is psycopg.pq.TransactionStatus.IDLE


def test_migration_cleanup_failures_do_not_mask_primary_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "001_primary_failure.sql").write_text(
        "SELECT primary_failure;",
        encoding="utf-8",
    )
    monkeypatch.setattr(db, "_sql_dir", lambda: tmp_path)

    class Connection:
        def __init__(self) -> None:
            self.info = SimpleNamespace(transaction_status=psycopg.pq.TransactionStatus.IDLE)
            self.rollback_attempted = False
            self.unlock_attempted = False

        def execute(self, query: str, _params=None):
            if "pg_advisory_lock" in query:
                return self
            if "pg_advisory_unlock" in query:
                self.unlock_attempted = True
                raise RuntimeError("unlock cleanup failed")
            self.info.transaction_status = psycopg.pq.TransactionStatus.INERROR
            raise ValueError("primary migration failure")

        def rollback(self) -> None:
            self.rollback_attempted = True
            raise RuntimeError("rollback cleanup failed")

    connection = Connection()

    class Database:
        @contextmanager
        def connect(self):
            yield connection

    with pytest.raises(ValueError, match="primary migration failure"):
        db.run_migrations(Database())  # type: ignore[arg-type]

    assert connection.rollback_attempted is True
    assert connection.unlock_attempted is True


@pytest.mark.pg
def test_migrations_hold_runtime_gate_for_the_entire_file_batch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    url = _postgres_test_url()
    block_key = int(time.time_ns() % (2**62))
    (tmp_path / "001_before_block.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "002_blocked.sql").write_text(
        f"SELECT pg_advisory_xact_lock({block_key}::BIGINT);",
        encoding="utf-8",
    )
    monkeypatch.setattr(db, "_sql_dir", lambda: tmp_path)
    database = _ObservedDatabase(url)
    migration_errors: list[BaseException] = []

    def migrate() -> None:
        try:
            db.run_migrations(database)
        except BaseException as exc:  # pragma: no cover - asserted below
            migration_errors.append(exc)

    with psycopg.connect(url, connect_timeout=1, autocommit=True) as blocker:
        blocker.execute("SELECT pg_advisory_lock(%s)", (block_key,))
        thread = threading.Thread(target=migrate)
        thread.start()
        try:
            assert database.connected.wait(timeout=2)
            assert database.backend_pid is not None
            _wait_until_backend_waits_for_advisory_lock(
                url,
                database.backend_pid,
                migration_thread=thread,
                migration_errors=migration_errors,
            )
            with psycopg.connect(url, connect_timeout=1) as reader:
                reader.execute("SET LOCAL lock_timeout = '200ms'")
                with pytest.raises(psycopg.errors.LockNotAvailable):
                    reader.execute(
                        "SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))",
                        (RUNTIME_GATE,),
                    )
        finally:
            blocker.execute("SELECT pg_advisory_unlock(%s)", (block_key,))
            thread.join(timeout=3)

    assert not thread.is_alive()
    assert migration_errors == []


@pytest.mark.pg
def test_migration_failure_rolls_back_and_releases_runtime_gate_before_disconnect(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    url = _postgres_test_url()
    (tmp_path / "001_fails_in_explicit_transaction.sql").write_text(
        "BEGIN; SELECT 1 / 0;",
        encoding="utf-8",
    )
    monkeypatch.setattr(db, "_sql_dir", lambda: tmp_path)
    database = _RetainedDatabase(url)

    try:
        with pytest.raises(psycopg.errors.DivisionByZero):
            db.run_migrations(database)

        assert database.connection is not None
        assert database.connection.info.transaction_status is psycopg.pq.TransactionStatus.IDLE
        with psycopg.connect(url, connect_timeout=1, autocommit=True) as reader:
            acquired = reader.execute(
                "SELECT pg_try_advisory_lock_shared(hashtextextended(%s, 0))",
                (RUNTIME_GATE,),
            ).fetchone()
            assert acquired == (True,)
            reader.execute(
                "SELECT pg_advisory_unlock_shared(hashtextextended(%s, 0))",
                (RUNTIME_GATE,),
            )
    finally:
        if database.connection is not None:
            database.connection.close()
