from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.api.routes.health import health as health_snapshot
from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes import workflow_binding as workflow_binding_module
from quant_system.hermes.command_ledger import (
    HermesCommandConflict,
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesCommandValidationError,
    command_ledger_schema_version,
)
from quant_system.hermes.workflow_binding import (
    PreparedWorkflowCommand,
    ensure_bound_command,
    get_workflow_binding_by_digest,
    get_workflow_binding_by_saga,
    iter_workflow_binding_inventory,
    workflow_binding_digest,
    workflow_binding_schema_version,
    workflow_binding_to_dict,
    workflow_preparation_digest,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _ensure_test_database(url: str) -> None:
    params = conninfo_to_dict(url)
    dbname = params.get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            f"QS_TEST_DATABASE_URL must point at a throwaway test database (got {dbname!r})"
        )
    maintenance_params = dict(params)
    maintenance_params["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**maintenance_params), autocommit=True) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (dbname,),
            ).fetchone()
            is None
        ):
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def _postgres_settings() -> Settings:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    _ensure_test_database(url)
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )


def _prepared(**overrides: object) -> PreparedWorkflowCommand:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "workflow_saga_id": "hqs_111111111111111111111111",
        "owner_user_id": ROOT_USER_ID,
        "platform_session_id": "platform-session-binding",
        "client_request_id": "req-binding-001",
        "command_kind": "research_chat",
        "canonical_request_digest": "a" * 64,
        "payload_ref": f"hqa-payload:sha256:{'b' * 64}",
        "payload_digest": "b" * 64,
        "payload_expires_at": datetime(2099, 7, 17, 4, 5, 6, tzinfo=UTC),
        "provider_policy_digest": "c" * 64,
        "task_id": "hqt_111111111111111111111111",
        "task_version": 1,
        "attempt_id": "hqa_111111111111111111111111",
        "attempt_number": 1,
        "prepared_event_id": "hqe_111111111111111111111111",
        "prepared_event_digest": "d" * 64,
        "plan_schema_version": 1,
        "plan_version": 1,
        "plan_digest": "e" * 64,
        "workflow_preparation_digest": "0" * 64,
    }
    values.update(overrides)
    draft = PreparedWorkflowCommand(**values)  # type: ignore[arg-type]
    return replace(
        draft,
        workflow_preparation_digest=workflow_preparation_digest(draft),
    )


def _reset_workflow_ledger(database: db.Database) -> None:
    with database.connect() as conn, conn.transaction():
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_workflow_bindings DISABLE TRIGGER USER"
        )
        conn.execute("ALTER TABLE quant_system.hermes_command_events DISABLE TRIGGER USER")
        conn.execute("ALTER TABLE quant_system.hermes_run_links DISABLE TRIGGER USER")
        conn.execute(
            """
            TRUNCATE TABLE
                quant_system.hermes_command_workflow_bindings,
                quant_system.hermes_run_links,
                quant_system.hermes_outbox,
                quant_system.hermes_command_events,
                quant_system.hermes_commands
            RESTART IDENTITY
            """
        )
        for trigger_name in (
            "trg_hermes_workflow_binding_validate",
            "trg_hermes_workflow_binding_append_only",
            "trg_hermes_workflow_binding_append_only_truncate",
        ):
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                f"ENABLE ALWAYS TRIGGER {trigger_name}"
            )
        conn.execute("ALTER TABLE quant_system.hermes_command_events ENABLE TRIGGER USER")
        conn.execute("ALTER TABLE quant_system.hermes_run_links ENABLE TRIGGER USER")


def _workflow_business_counts(database: db.Database) -> tuple[int, int, int, int]:
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT count(*) FROM quant_system.hermes_commands),
                (SELECT count(*) FROM quant_system.hermes_command_events),
                (SELECT count(*) FROM quant_system.hermes_command_workflow_bindings),
                (SELECT count(*) FROM quant_system.hermes_outbox)
            """
        ).fetchone()
    assert row is not None
    return tuple(int(value) for value in row)  # type: ignore[return-value]


def test_inventory_empty_snapshot_has_exact_header_trailer_and_zero_writes() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        before = _workflow_business_counts(database)

        records = list(iter_workflow_binding_inventory(settings))

        assert records == [
            {
                "schema_version": "1.0",
                "kind": "workflow_binding_inventory_header",
                "binding_schema_version": 1,
            },
            {
                "schema_version": "1.0",
                "kind": "workflow_binding_inventory_trailer",
                "count": 0,
                "bindings_sha256": hashlib.sha256(b"").hexdigest(),
            },
        ]
        assert _workflow_business_counts(database) == before == (0, 0, 0, 0)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_inventory_orders_full_bindings_and_hashes_canonical_json_lines() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        created = []
        for marker in ("f", "1", "a"):
            created.append(
                ensure_bound_command(
                    settings,
                    _prepared(
                        workflow_saga_id=f"hqs_{marker * 24}",
                        platform_session_id="platform-session-inventory-order",
                        client_request_id=f"req-inventory-order-{marker}",
                        task_id=f"hqt_{marker * 24}",
                        attempt_id=f"hqa_{marker * 24}",
                        prepared_event_id=f"hqe_{marker * 24}",
                    ),
                )
            )
        before = _workflow_business_counts(database)

        records = list(iter_workflow_binding_inventory(settings))

        assert records[0] == {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_header",
            "binding_schema_version": 1,
        }
        items = records[1:-1]
        assert [set(item) for item in items] == [
            {"schema_version", "kind", "ordinal", "binding"}
        ] * 3
        assert [item["schema_version"] for item in items] == ["1.0"] * 3
        assert [item["kind"] for item in items] == ["workflow_binding_inventory_item"] * 3
        assert [item["ordinal"] for item in items] == [1, 2, 3]
        expected_bindings = sorted(
            (workflow_binding_to_dict(result.binding) for result in created),
            key=lambda binding: (binding["workflow_saga_id"], binding["command_id"]),
        )
        assert [item["binding"] for item in items] == expected_bindings
        canonical_lines = b"".join(
            json.dumps(
                binding,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
            for binding in expected_bindings
        )
        assert records[-1] == {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_trailer",
            "count": 3,
            "bindings_sha256": hashlib.sha256(canonical_lines).hexdigest(),
        }
        assert _workflow_business_counts(database) == before == (3, 3, 3, 3)
        serialized = json.dumps(records, sort_keys=True)
        assert "gpt-5" not in serialized
        assert "grok" not in serialized
        assert "prompt" not in serialized
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_inventory_uses_one_repeatable_snapshot_across_concurrent_insert() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        first = ensure_bound_command(settings, _prepared())
        inventory = iter_workflow_binding_inventory(settings)

        header = next(inventory)
        second = ensure_bound_command(
            settings,
            _prepared(
                workflow_saga_id="hqs_999999999999999999999999",
                platform_session_id="platform-session-inventory-concurrent",
                client_request_id="req-inventory-concurrent-002",
                task_id="hqt_999999999999999999999999",
                attempt_id="hqa_999999999999999999999999",
                prepared_event_id="hqe_999999999999999999999999",
            ),
        )
        remaining = list(inventory)

        assert header["kind"] == "workflow_binding_inventory_header"
        assert [record["binding"]["command_id"] for record in remaining[:-1]] == [
            str(first.command_id)
        ]
        assert remaining[-1]["count"] == 1

        fresh = list(iter_workflow_binding_inventory(settings))
        assert {record["binding"]["command_id"] for record in fresh[1:-1]} == {
            str(first.command_id),
            str(second.command_id),
        }
        assert fresh[-1]["count"] == 2
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_inventory_fails_closed_when_bound_command_is_missing() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    created = ensure_bound_command(settings, _prepared())

    try:
        with database.connect() as corrupt_conn:
            corrupt_conn.execute(
                """
                CREATE TEMP TABLE inventory_command_backup
                ON COMMIT PRESERVE ROWS
                AS SELECT *
                   FROM quant_system.hermes_commands
                   WHERE command_id = %s
                """,
                (created.command_id,),
            )
            corrupt_conn.execute("SET session_replication_role = replica")
            corrupt_conn.execute(
                "DELETE FROM quant_system.hermes_commands WHERE command_id = %s",
                (created.command_id,),
            )
            corrupt_conn.execute("SET session_replication_role = origin")
            corrupt_conn.commit()
            try:
                with pytest.raises(
                    HermesCommandLedgerUnavailable,
                    match="integrity verification",
                ):
                    list(iter_workflow_binding_inventory(settings))
            finally:
                corrupt_conn.execute(
                    """
                    INSERT INTO quant_system.hermes_commands
                    SELECT * FROM inventory_command_backup
                    """
                )
                corrupt_conn.commit()

        assert (
            get_workflow_binding_by_saga(
                settings,
                created.binding.workflow_saga_id,
            )
            == created.binding
        )
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_inventory_fails_closed_on_command_identity_mirror_drift() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    created = ensure_bound_command(settings, _prepared())

    try:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands DISABLE TRIGGER "
                "trg_hermes_command_intent_immutable"
            )
            conn.execute(
                """
                UPDATE quant_system.hermes_commands
                SET platform_session_id = 'platform-session-corrupt-mirror'
                WHERE command_id = %s
                """,
                (created.command_id,),
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands ENABLE ALWAYS TRIGGER "
                "trg_hermes_command_intent_immutable"
            )

        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="integrity verification",
        ):
            list(iter_workflow_binding_inventory(settings))
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands DISABLE TRIGGER "
                "trg_hermes_command_intent_immutable"
            )
            conn.execute(
                """
                UPDATE quant_system.hermes_commands
                SET platform_session_id = %s
                WHERE command_id = %s
                """,
                (created.binding.platform_session_id, created.command_id),
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands ENABLE ALWAYS TRIGGER "
                "trg_hermes_command_intent_immutable"
            )
        _reset_workflow_ledger(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    "digest_field",
    ["workflow_preparation_digest", "binding_digest"],
)
def test_inventory_fails_closed_on_stored_digest_drift(digest_field: str) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    created = ensure_bound_command(settings, _prepared())
    original = getattr(created.binding, digest_field)

    try:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "DISABLE TRIGGER trg_hermes_workflow_binding_append_only"
            )
            conn.execute(
                sql.SQL(
                    "UPDATE quant_system.hermes_command_workflow_bindings "
                    "SET {} = %s WHERE command_id = %s"
                ).format(sql.Identifier(digest_field)),
                ("f" * 64, created.command_id),
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_append_only"
            )

        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="integrity verification",
        ):
            list(iter_workflow_binding_inventory(settings))
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "DISABLE TRIGGER trg_hermes_workflow_binding_append_only"
            )
            conn.execute(
                sql.SQL(
                    "UPDATE quant_system.hermes_command_workflow_bindings "
                    "SET {} = %s WHERE command_id = %s"
                ).format(sql.Identifier(digest_field)),
                (original, created.command_id),
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_append_only"
            )
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_workflow_binding_migration_is_repeatable_and_independently_versioned() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    try:
        db.run_migrations(database)
        db.run_migrations(database)

        assert command_ledger_schema_version(settings) == 1
        assert workflow_binding_schema_version(settings) == 1
        with database.connect() as conn:
            tables = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'quant_system'
                  AND table_name = ANY(%s)
                ORDER BY table_name
                """,
                (
                    [
                        "hermes_workflow_binding_meta",
                        "hermes_command_workflow_bindings",
                    ],
                ),
            ).fetchall()
            binding_version = conn.execute(
                """
                SELECT schema_version
                FROM quant_system.hermes_workflow_binding_meta
                WHERE singleton IS TRUE
                """
            ).fetchone()
            ledger_version = conn.execute(
                """
                SELECT schema_version
                FROM quant_system.hermes_ledger_meta
                WHERE singleton IS TRUE
                """
            ).fetchone()

        assert [row[0] for row in tables] == [
            "hermes_command_workflow_bindings",
            "hermes_workflow_binding_meta",
        ]
        assert binding_version == (1,)
        assert ledger_version == (1,)

        rollback_sql = (
            Path(__file__).parents[1] / "scripts/sql/rollback/006_hermes_workflow_binding.down.sql"
        ).read_text()
        with database.connect() as conn:
            conn.execute(rollback_sql)
            conn.execute(rollback_sql)
        assert command_ledger_schema_version(settings) == 1
        assert workflow_binding_schema_version(settings) is None

        db.run_migrations(database)
        assert command_ledger_schema_version(settings) == 1
        assert workflow_binding_schema_version(settings) == 1
    finally:
        db.run_migrations(database)
        db.reset_database_cache()


def test_workflow_binding_rollback_is_reentrant_when_schema_is_missing() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    rollback_sql = (
        Path(__file__).parents[1] / "scripts/sql/rollback/006_hermes_workflow_binding.down.sql"
    ).read_text(encoding="utf-8")

    try:
        with database.connect() as conn:
            conn.execute("DROP SCHEMA quant_system CASCADE")
        with database.connect() as conn:
            conn.execute(rollback_sql)
            conn.execute(rollback_sql)
    finally:
        db.run_migrations(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    "missing_relation",
    [
        "hermes_command_workflow_bindings",
        "hermes_commands",
        "hermes_command_events",
    ],
)
def test_workflow_binding_rollback_is_reentrant_from_partial_relation_state(
    missing_relation: str,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    rollback_sql = (
        Path(__file__).parents[1] / "scripts/sql/rollback/006_hermes_workflow_binding.down.sql"
    ).read_text(encoding="utf-8")

    try:
        with database.connect() as conn:
            conn.execute(
                sql.SQL("DROP TABLE quant_system.{} CASCADE").format(
                    sql.Identifier(missing_relation)
                )
            )
        with database.connect() as conn:
            conn.execute(rollback_sql)
            conn.execute(rollback_sql)
            assert conn.execute(
                """
                SELECT
                    to_regclass(
                        'quant_system.hermes_command_workflow_bindings'
                    ),
                    to_regclass('quant_system.hermes_workflow_binding_meta')
                """
            ).fetchone() == (None, None)
    finally:
        with database.connect() as conn:
            conn.execute("DROP SCHEMA IF EXISTS quant_system CASCADE")
        db.run_migrations(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    ("duplicate_field", "constraint_name"),
    [
        ("task_id", "uq_hermes_workflow_binding_task"),
        ("attempt_id", "uq_hermes_workflow_binding_attempt"),
    ],
)
def test_workflow_binding_migration_rejects_duplicate_legacy_identity_data(
    duplicate_field: str,
    constraint_name: str,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    migration_sql = Path("scripts/sql/006_hermes_workflow_binding.sql").read_text(encoding="utf-8")

    try:
        first = ensure_bound_command(settings, _prepared())
        second = ensure_bound_command(
            settings,
            _prepared(
                workflow_saga_id="hqs_222222222222222222222222",
                platform_session_id="platform-session-legacy-duplicate",
                client_request_id="req-legacy-duplicate-002",
                task_id="hqt_222222222222222222222222",
                attempt_id="hqa_222222222222222222222222",
                prepared_event_id="hqe_222222222222222222222222",
            ),
        )
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "DISABLE TRIGGER trg_hermes_workflow_binding_append_only"
            )
            conn.execute(
                sql.SQL(
                    "ALTER TABLE quant_system.hermes_command_workflow_bindings DROP CONSTRAINT {}"
                ).format(sql.Identifier(constraint_name))
            )
            conn.execute(
                sql.SQL(
                    "UPDATE quant_system.hermes_command_workflow_bindings "
                    "SET {} = %s WHERE command_id = %s"
                ).format(sql.Identifier(duplicate_field)),
                (
                    getattr(first.binding, duplicate_field),
                    second.command_id,
                ),
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_append_only"
            )

        with pytest.raises(psycopg.errors.UniqueViolation), database.connect() as conn:
            conn.execute(migration_sql)

        assert workflow_binding_schema_version(settings) is None
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT count(*), count(DISTINCT task_id), count(DISTINCT attempt_id)
                FROM quant_system.hermes_command_workflow_bindings
                """
            ).fetchone() == (
                2,
                1 if duplicate_field == "task_id" else 2,
                1 if duplicate_field == "attempt_id" else 2,
            )
    finally:
        _reset_workflow_ledger(database)
        db.run_migrations(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    "drift",
    [
        "missing_attempt_constraint",
        "tampered_task_constraint",
        "invalid_task_index",
    ],
)
def test_task_attempt_uniqueness_drift_blocks_read_and_inventory_parity(
    drift: str,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        existing = ensure_bound_command(settings, _prepared())
        with database.connect() as conn:
            if drift == "missing_attempt_constraint":
                conn.execute(
                    "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                    "DROP CONSTRAINT uq_hermes_workflow_binding_attempt"
                )
            elif drift == "tampered_task_constraint":
                conn.execute(
                    "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                    "DROP CONSTRAINT uq_hermes_workflow_binding_task"
                )
                conn.execute(
                    "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                    "ADD CONSTRAINT uq_hermes_workflow_binding_task "
                    "UNIQUE (task_id, attempt_id)"
                )
            else:
                conn.execute(
                    """
                    UPDATE pg_index
                    SET indisvalid = FALSE
                    WHERE indexrelid =
                        'quant_system.uq_hermes_workflow_binding_task'::regclass
                    """
                )

        assert workflow_binding_schema_version(settings) is None
        with pytest.raises(HermesCommandLedgerUnavailable):
            list(iter_workflow_binding_inventory(settings))
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            get_workflow_binding_by_saga(
                settings,
                existing.binding.workflow_saga_id,
            )
    finally:
        with database.connect() as conn:
            if drift in {"tampered_task_constraint", "invalid_task_index"}:
                conn.execute(
                    "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                    "DROP CONSTRAINT IF EXISTS uq_hermes_workflow_binding_task"
                )
        db.run_migrations(database)
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_ensure_bound_command_is_atomic_idempotent_and_recoverable_by_exact_keys() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    prepared = _prepared()

    try:
        first = ensure_bound_command(settings, prepared)
        second = ensure_bound_command(settings, prepared)

        assert first.created is True
        assert second.created is False
        assert second.command_id == first.command_id
        assert second.binding == first.binding
        assert first.command_state == "queued"
        assert first.command_version == 1
        assert first.binding.workflow_preparation_digest == (prepared.workflow_preparation_digest)
        assert first.binding.payload_expires_at == prepared.payload_expires_at
        assert (
            get_workflow_binding_by_saga(
                settings,
                prepared.workflow_saga_id,
            )
            == first.binding
        )
        assert (
            get_workflow_binding_by_digest(
                settings,
                first.binding.binding_digest,
            )
            == first.binding
        )

        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_events),
                    (SELECT count(*) FROM quant_system.hermes_command_workflow_bindings),
                    (SELECT count(*) FROM quant_system.hermes_outbox)
                """
            ).fetchone()
            event_data = conn.execute(
                """
                SELECT event_data
                FROM quant_system.hermes_command_events
                WHERE command_id = %s AND command_version = 1
                """,
                (first.command_id,),
            ).fetchone()
            outbox = conn.execute(
                """
                SELECT command_version, topic, consumed_at
                FROM quant_system.hermes_outbox
                WHERE command_id = %s
                """,
                (first.command_id,),
            ).fetchone()

        assert counts == (1, 1, 1, 1)
        assert event_data == (
            {
                "binding_digest": first.binding.binding_digest,
                "workflow_preparation_digest": prepared.workflow_preparation_digest,
                "workflow_saga_id": prepared.workflow_saga_id,
            },
        )
        assert outbox == (1, "hermes.command.queued", None)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_concurrent_ensure_of_same_exact_receipt_creates_one_binding() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    prepared = _prepared()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _index: ensure_bound_command(settings, prepared),
                    range(2),
                )
            )

        assert {result.command_id for result in results} == {results[0].command_id}
        assert sorted(result.created for result in results) == [False, True]
        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_events),
                    (SELECT count(*) FROM quant_system.hermes_command_workflow_bindings),
                    (SELECT count(*) FROM quant_system.hermes_outbox)
                """
            ).fetchone()
        assert counts == (1, 1, 1, 1)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    "meta_table",
    ["hermes_ledger_meta", "hermes_workflow_binding_meta"],
)
def test_ensure_holds_both_meta_rows_until_the_write_transaction_finishes(
    monkeypatch,
    meta_table: str,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    gate_held = Event()
    release_gate = Event()
    original_signature = workflow_binding_module._workflow_binding_schema_signature_is_ready

    def pause_after_both_meta_locks(conn):
        ready = original_signature(conn)
        gate_held.set()
        if not release_gate.wait(timeout=5):
            raise AssertionError("test did not release the schema gate")
        return ready

    monkeypatch.setattr(
        workflow_binding_module,
        "_workflow_binding_schema_signature_is_ready",
        pause_after_both_meta_locks,
    )

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ensure_bound_command, settings, _prepared())
            assert gate_held.wait(timeout=5), "ensure never acquired both schema locks"
            try:
                with (
                    pytest.raises(psycopg.errors.LockNotAvailable),
                    database.connect() as drift_conn,
                    drift_conn.transaction(),
                ):
                    drift_conn.execute("SET LOCAL lock_timeout = '250ms'")
                    drift_conn.execute(
                        f"""
                        UPDATE quant_system.{meta_table}
                        SET schema_version = 2
                        WHERE singleton IS TRUE
                        """
                    )
            finally:
                release_gate.set()
            created = future.result(timeout=5)

        assert created.created is True
        with database.connect() as conn:
            assert conn.execute(
                f"SELECT schema_version FROM quant_system.{meta_table} WHERE singleton IS TRUE"
            ).fetchone() == (1,)
            conn.execute(
                f"UPDATE quant_system.{meta_table} SET schema_version = 2 WHERE singleton IS TRUE"
            )
            conn.execute(
                f"UPDATE quant_system.{meta_table} SET schema_version = 1 WHERE singleton IS TRUE"
            )
    finally:
        release_gate.set()
        with database.connect() as conn:
            conn.execute(
                f"UPDATE quant_system.{meta_table} SET schema_version = 1 WHERE singleton IS TRUE"
            )
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_claim_holds_both_meta_rows_from_candidate_lock_through_command_update(
    monkeypatch,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    ledger = HermesCommandLedger(settings)
    ensure_bound_command(settings, _prepared())
    claim_gate_held = Event()
    advisory_key = 930_016
    original_gate = workflow_binding_module.workflow_binding_schema_is_ready_on_connection

    def signal_claim_gate(conn):
        ready = original_gate(conn)
        claim_gate_held.set()
        return ready

    monkeypatch.setattr(
        workflow_binding_module,
        "workflow_binding_schema_is_ready_on_connection",
        signal_claim_gate,
    )

    try:
        with database.connect() as conn:
            conn.execute(
                f"""
                CREATE OR REPLACE FUNCTION quant_system.test_block_hermes_claim_update()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    PERFORM pg_advisory_xact_lock({advisory_key}::BIGINT);
                    RETURN NEW;
                END;
                $$
                """
            )
            conn.execute(
                """
                CREATE TRIGGER test_block_hermes_claim_update
                BEFORE UPDATE ON quant_system.hermes_commands
                FOR EACH ROW
                WHEN (OLD.state = 'queued' AND NEW.state = 'leased')
                EXECUTE FUNCTION quant_system.test_block_hermes_claim_update()
                """
            )

        with database.connect() as blocker:
            blocker.execute("SELECT pg_advisory_lock(%s)", (advisory_key,))
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        ledger.claim_next_command,
                        worker_id="worker-claim-schema-lock",
                        now=datetime.now(UTC),
                        lease_duration=timedelta(seconds=30),
                    )
                    if not claim_gate_held.wait(timeout=5):
                        future.result(timeout=1)
                        pytest.fail("claim never acquired the workflow schema gate")

                    deadline = monotonic() + 5
                    waiting = False
                    while monotonic() < deadline:
                        with database.connect() as observer:
                            waiting = bool(
                                observer.execute(
                                    """
                                    SELECT 1
                                    FROM pg_locks
                                    WHERE locktype = 'advisory'
                                      AND granted IS FALSE
                                      AND objid = %s
                                    """,
                                    (advisory_key,),
                                ).fetchone()
                            )
                        if waiting:
                            break
                        Event().wait(0.01)
                    assert waiting, "claim never reached its command UPDATE trigger"

                    for meta_table in (
                        "hermes_ledger_meta",
                        "hermes_workflow_binding_meta",
                    ):
                        with (
                            pytest.raises(psycopg.errors.LockNotAvailable),
                            database.connect() as drift_conn,
                            drift_conn.transaction(),
                        ):
                            drift_conn.execute("SET LOCAL lock_timeout = '250ms'")
                            drift_conn.execute(
                                f"""
                                UPDATE quant_system.{meta_table}
                                SET schema_version = 2
                                WHERE singleton IS TRUE
                                """
                            )

                    blocker.execute("SELECT pg_advisory_unlock(%s)", (advisory_key,))
                    claimed = future.result(timeout=5)
            finally:
                blocker.execute("SELECT pg_advisory_unlock(%s)", (advisory_key,))

        assert claimed is not None
        assert claimed.state == "leased"
        with database.connect() as conn:
            assert conn.execute(
                "SELECT schema_version FROM quant_system.hermes_ledger_meta WHERE singleton IS TRUE"
            ).fetchone() == (1,)
            assert conn.execute(
                "SELECT schema_version FROM quant_system.hermes_workflow_binding_meta "
                "WHERE singleton IS TRUE"
            ).fetchone() == (1,)
    finally:
        with database.connect() as conn:
            conn.execute(
                "DROP TRIGGER IF EXISTS test_block_hermes_claim_update "
                "ON quant_system.hermes_commands"
            )
            conn.execute("DROP FUNCTION IF EXISTS quant_system.test_block_hermes_claim_update()")
            conn.execute(
                "UPDATE quant_system.hermes_ledger_meta SET schema_version = 1 "
                "WHERE singleton IS TRUE"
            )
            conn.execute(
                "UPDATE quant_system.hermes_workflow_binding_meta SET schema_version = 1 "
                "WHERE singleton IS TRUE"
            )
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_claim_rechecks_expiry_after_candidate_before_lease_commit(monkeypatch) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    ledger = HermesCommandLedger(settings)
    advisory_key = 930_017

    with database.connect() as conn:
        server_now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    prepared = _prepared(payload_expires_at=server_now + timedelta(seconds=2))
    created = ensure_bound_command(settings, prepared)

    try:
        with database.connect() as conn:
            # Isolate the final UPDATE predicate from the AFTER-trigger defence.
            # Claim readiness is replaced only inside this test after a real
            # migration/readiness pass has established the baseline schema.
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands DISABLE TRIGGER "
                "trg_hermes_command_claim_binding_guard"
            )
            conn.execute(
                f"""
                CREATE OR REPLACE FUNCTION quant_system.test_block_expiring_claim_update()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    PERFORM pg_advisory_xact_lock({advisory_key}::BIGINT);
                    RETURN NEW;
                END;
                $$
                """
            )
            conn.execute(
                """
                CREATE TRIGGER test_block_expiring_claim_update
                BEFORE UPDATE ON quant_system.hermes_commands
                FOR EACH STATEMENT
                EXECUTE FUNCTION quant_system.test_block_expiring_claim_update()
                """
            )
        monkeypatch.setattr(
            workflow_binding_module,
            "workflow_binding_schema_is_ready_on_connection",
            lambda _conn: True,
        )

        with database.connect() as blocker:
            blocker.execute("SELECT pg_advisory_lock(%s)", (advisory_key,))
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(
                        ledger.claim_next_command,
                        worker_id="worker-expiring-between-select-update",
                        now=datetime.now(UTC),
                        lease_duration=timedelta(seconds=30),
                    )

                    deadline = monotonic() + 5
                    waiting = False
                    while monotonic() < deadline:
                        with database.connect() as observer:
                            waiting = bool(
                                observer.execute(
                                    """
                                    SELECT 1
                                    FROM pg_locks
                                    WHERE locktype = 'advisory'
                                      AND granted IS FALSE
                                      AND objid = %s
                                    """,
                                    (advisory_key,),
                                ).fetchone()
                            )
                        if waiting:
                            break
                        Event().wait(0.01)
                    assert waiting, "claim did not pass candidate selection before expiry"

                    with database.connect() as observer:
                        observer.execute(
                            """
                            SELECT pg_sleep(
                                GREATEST(
                                    EXTRACT(EPOCH FROM (%s::timestamptz - clock_timestamp())),
                                    0
                                ) + 0.05
                            )
                            """,
                            (prepared.payload_expires_at,),
                        )
                        assert observer.execute(
                            "SELECT clock_timestamp() > %s::timestamptz",
                            (prepared.payload_expires_at,),
                        ).fetchone() == (True,)

                    blocker.execute("SELECT pg_advisory_unlock(%s)", (advisory_key,))
                    claimed = future.result(timeout=5)
            finally:
                blocker.execute("SELECT pg_advisory_unlock(%s)", (advisory_key,))

        assert claimed is None
        assert ledger.get_command(created.command_id).state == "queued"
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT consumed_at
                FROM quant_system.hermes_outbox
                WHERE command_id = %s AND command_version = 1
                """,
                (created.command_id,),
            ).fetchone() == (None,)
    finally:
        with database.connect() as conn:
            conn.execute(
                "DROP TRIGGER IF EXISTS test_block_expiring_claim_update "
                "ON quant_system.hermes_commands"
            )
            conn.execute("DROP FUNCTION IF EXISTS quant_system.test_block_expiring_claim_update()")
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands ENABLE ALWAYS TRIGGER "
                "trg_hermes_command_claim_binding_guard"
            )
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_schema_readiness_fails_closed_when_required_trigger_is_not_always_enabled() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "ENABLE REPLICA TRIGGER trg_hermes_workflow_binding_validate"
            )
        assert workflow_binding_schema_version(settings) is None
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            ensure_bound_command(settings, _prepared())
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_validate"
            )
        _reset_workflow_ledger(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    "function_name",
    [
        "validate_hermes_workflow_binding",
        "reject_hermes_workflow_binding_mutation",
        "protect_hermes_command_intent_identity",
    ],
)
def test_security_function_body_drift_blocks_read_write_and_claim(
    function_name: str,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        existing = ensure_bound_command(settings, _prepared())
        with database.connect() as conn:
            conn.execute(
                f"""
                CREATE OR REPLACE FUNCTION quant_system.{function_name}()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$
                """
            )

        assert workflow_binding_schema_version(settings) is None
        with pytest.raises(HermesCommandLedgerUnavailable):
            list(iter_workflow_binding_inventory(settings))
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            ensure_bound_command(
                settings,
                _prepared(
                    workflow_saga_id="hqs_444444444444444444444444",
                    platform_session_id="platform-session-function-drift",
                    client_request_id="req-function-drift-001",
                    task_id="hqt_444444444444444444444444",
                    attempt_id="hqa_444444444444444444444444",
                    prepared_event_id="hqe_444444444444444444444444",
                ),
            )
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            get_workflow_binding_by_saga(settings, existing.binding.workflow_saga_id)
        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="schema version is not ready",
        ):
            ledger.claim_next_command(
                worker_id="worker-function-drift",
                now=datetime.now(UTC),
                lease_duration=timedelta(seconds=30),
            )
        assert ledger.get_command(existing.command_id).state == "queued"
    finally:
        db.run_migrations(database)
        assert workflow_binding_schema_version(settings) == 1
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_legacy_event_append_only_function_drift_fails_closed_and_006_restores_it() -> None:
    """Binding readiness includes the immutable event evidence it anchors."""

    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    ledger = HermesCommandLedger(settings)
    existing = ensure_bound_command(settings, _prepared())
    migration_006 = Path("scripts/sql/006_hermes_workflow_binding.sql").read_text(encoding="utf-8")

    try:
        with database.connect() as conn:
            conn.execute(
                """
                CREATE OR REPLACE FUNCTION quant_system.reject_hermes_command_event_mutation()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$
                """
            )

        # These two values are the exact facts rendered by /api/health.
        assert command_ledger_schema_version(settings) is None
        assert workflow_binding_schema_version(settings) is None
        with pytest.raises(HermesCommandLedgerUnavailable):
            list(iter_workflow_binding_inventory(settings))
        health_settings = settings.model_copy(
            update={"futu": settings.futu.model_copy(update={"enabled": False})}
        )
        health_payload = health_snapshot(health_settings)
        assert health_payload["hermes_command_ledger"] == {
            "database_configured": True,
            "schema_ready": False,
            "schema_version": None,
            "workflow_binding_schema_ready": False,
            "workflow_binding_schema_version": None,
            "mutation_enabled": False,
        }
        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="schema version is not ready",
        ):
            ledger.get_command(existing.command_id)
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            get_workflow_binding_by_saga(settings, existing.binding.workflow_saga_id)
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            ensure_bound_command(
                settings,
                _prepared(
                    workflow_saga_id="hqs_555555555555555555555555",
                    platform_session_id="platform-session-ledger-function-drift",
                    client_request_id="req-ledger-function-drift-001",
                    task_id="hqt_555555555555555555555555",
                    attempt_id="hqa_555555555555555555555555",
                    prepared_event_id="hqe_555555555555555555555555",
                ),
            )
        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="schema version is not ready",
        ):
            ledger.claim_next_command(
                worker_id="worker-ledger-function-drift",
                now=datetime.now(UTC),
                lease_duration=timedelta(seconds=30),
            )

        with database.connect() as conn:
            assert conn.execute(
                "SELECT state FROM quant_system.hermes_commands WHERE command_id = %s",
                (existing.command_id,),
            ).fetchone() == ("queued",)
            conn.execute(migration_006)

        assert command_ledger_schema_version(settings) == 1
        assert workflow_binding_schema_version(settings) == 1
        assert ledger.get_command(existing.command_id).state == "queued"
    finally:
        db.run_migrations(database)
        _reset_workflow_ledger(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    ("meta_state", "schema_version"),
    [
        ("missing", None),
        ("future", 2),
        ("incompatible", 0),
    ],
)
def test_meta_schema_drift_blocks_ensure_get_and_claim(
    meta_state: str,
    schema_version: int | None,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        existing = ensure_bound_command(settings, _prepared())
        with database.connect() as conn:
            if meta_state == "missing":
                conn.execute(
                    "DELETE FROM quant_system.hermes_workflow_binding_meta WHERE singleton IS TRUE"
                )
            else:
                if meta_state == "incompatible":
                    conn.execute(
                        "ALTER TABLE quant_system.hermes_workflow_binding_meta "
                        "DROP CONSTRAINT ck_hermes_workflow_binding_meta_version"
                    )
                conn.execute(
                    """
                    UPDATE quant_system.hermes_workflow_binding_meta
                    SET schema_version = %s
                    WHERE singleton IS TRUE
                    """,
                    (schema_version,),
                )

        assert workflow_binding_schema_version(settings) is None
        with pytest.raises(HermesCommandLedgerUnavailable):
            list(iter_workflow_binding_inventory(settings))
        new_receipt = _prepared(
            workflow_saga_id="hqs_333333333333333333333333",
            platform_session_id="platform-session-meta-drift",
            client_request_id="req-meta-drift-001",
            task_id="hqt_333333333333333333333333",
            attempt_id="hqa_333333333333333333333333",
            prepared_event_id="hqe_333333333333333333333333",
        )
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            ensure_bound_command(settings, new_receipt)
        with pytest.raises(HermesCommandLedgerUnavailable, match="schema is not ready"):
            get_workflow_binding_by_saga(settings, existing.binding.workflow_saga_id)
        with pytest.raises(
            HermesCommandLedgerUnavailable,
            match="schema version is not ready",
        ):
            ledger.claim_next_command(
                worker_id="worker-meta-drift",
                now=datetime.now(UTC),
                lease_duration=timedelta(seconds=30),
            )

        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_workflow_bindings)
                """
            ).fetchone()
            state = conn.execute(
                "SELECT state FROM quant_system.hermes_commands WHERE command_id = %s",
                (existing.command_id,),
            ).fetchone()
        assert counts == (1, 1)
        assert state == ("queued",)
    finally:
        with database.connect() as conn:
            conn.execute(
                """
                INSERT INTO quant_system.hermes_workflow_binding_meta (
                    singleton, schema_version
                )
                VALUES (TRUE, 1)
                ON CONFLICT (singleton) DO UPDATE
                SET schema_version = EXCLUDED.schema_version,
                    updated_at = clock_timestamp()
                """
            )
            conn.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'ck_hermes_workflow_binding_meta_version'
                          AND conrelid =
                              'quant_system.hermes_workflow_binding_meta'::regclass
                    ) THEN
                        ALTER TABLE quant_system.hermes_workflow_binding_meta
                            ADD CONSTRAINT ck_hermes_workflow_binding_meta_version
                            CHECK (schema_version > 0);
                    END IF;
                END $$
                """
            )
        assert workflow_binding_schema_version(settings) == 1
        _reset_workflow_ledger(database)
        db.reset_database_cache()


@pytest.mark.parametrize(
    "changes",
    [
        {"plan_version": 2},
        {
            "workflow_saga_id": "hqs_222222222222222222222222",
            "prepared_event_id": "hqe_222222222222222222222222",
        },
        {
            "client_request_id": "req-binding-other",
            "payload_digest": "f" * 64,
            "payload_ref": f"hqa-payload:sha256:{'f' * 64}",
        },
    ],
)
def test_same_idempotency_key_saga_or_prepared_event_with_different_facts_conflicts_without_writes(
    changes: dict[str, object],
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        ensure_bound_command(settings, _prepared())

        with pytest.raises(HermesCommandConflict):
            ensure_bound_command(settings, _prepared(**changes))

        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_events),
                    (SELECT count(*) FROM quant_system.hermes_command_workflow_bindings),
                    (SELECT count(*) FROM quant_system.hermes_outbox)
                """
            ).fetchone()
        assert counts == (1, 1, 1, 1)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_distinct_binding_cannot_reuse_task_identity() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        ensure_bound_command(settings, _prepared())

        with pytest.raises(HermesCommandLedgerUnavailable):
            ensure_bound_command(
                settings,
                _prepared(
                    workflow_saga_id="hqs_222222222222222222222222",
                    platform_session_id="platform-session-task-reuse",
                    client_request_id="req-task-reuse-002",
                    attempt_id="hqa_222222222222222222222222",
                    prepared_event_id="hqe_222222222222222222222222",
                ),
            )

        assert _workflow_business_counts(database) == (1, 1, 1, 1)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_distinct_binding_cannot_reuse_attempt_identity() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        ensure_bound_command(settings, _prepared())

        with pytest.raises(HermesCommandLedgerUnavailable):
            ensure_bound_command(
                settings,
                _prepared(
                    workflow_saga_id="hqs_222222222222222222222222",
                    platform_session_id="platform-session-attempt-reuse",
                    client_request_id="req-attempt-reuse-002",
                    task_id="hqt_222222222222222222222222",
                    prepared_event_id="hqe_222222222222222222222222",
                ),
            )

        assert _workflow_business_counts(database) == (1, 1, 1, 1)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_expired_payload_is_rejected_by_database_clock_without_any_write() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        with pytest.raises(HermesCommandValidationError, match="expired"):
            ensure_bound_command(
                settings,
                _prepared(payload_expires_at=datetime(2000, 1, 1, tzinfo=UTC)),
            )
        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_workflow_bindings)
                """
            ).fetchone()
        assert counts == (0, 0)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_binding_failure_rolls_back_command_event_and_outbox() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        with database.connect() as conn:
            conn.execute(
                """
                CREATE OR REPLACE FUNCTION pg_temp.fail_workflow_binding_insert()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION 'injected binding failure';
                END $$
                """
            )
            conn.execute(
                """
                CREATE TRIGGER test_fail_workflow_binding_insert
                BEFORE INSERT ON quant_system.hermes_command_workflow_bindings
                FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_workflow_binding_insert()
                """
            )
            with pytest.raises(HermesCommandLedgerUnavailable):
                ensure_bound_command(settings, _prepared())
            conn.execute(
                "DROP TRIGGER test_fail_workflow_binding_insert "
                "ON quant_system.hermes_command_workflow_bindings"
            )

        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_events),
                    (SELECT count(*) FROM quant_system.hermes_command_workflow_bindings),
                    (SELECT count(*) FROM quant_system.hermes_outbox)
                """
            ).fetchone()
        assert counts == (0, 0, 0, 0)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_binding_rejects_command_event_with_divergent_workflow_evidence() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    prepared = _prepared()
    command_id = UUID("10000000-0000-0000-0000-000000000099")

    try:
        with database.connect() as conn:
            conn.execute(
                """
                INSERT INTO quant_system.hermes_commands (
                    command_id, owner_user_id, platform_session_id,
                    client_request_id, kind, intent_schema_version,
                    canonical_request_digest, payload_ref,
                    provider_policy_digest, state, version
                )
                VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s, 'queued', 1)
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
            )
            conn.execute(
                """
                INSERT INTO quant_system.hermes_command_events (
                    command_id, command_version, event_type, actor,
                    from_state, to_state, canonical_request_digest,
                    attempt_count, event_data
                )
                VALUES (%s, 1, 'command_created', 'system', NULL, 'queued', %s, 0,
                        '{}'::jsonb)
                """,
                (command_id, prepared.canonical_request_digest),
            )
        binding_digest = workflow_binding_digest(
            prepared,
            command_id=command_id,
        )

        with (
            pytest.raises(psycopg.errors.RaiseException, match="event anchor"),
            database.connect() as conn,
        ):
            conn.execute(
                """
                    INSERT INTO quant_system.hermes_command_workflow_bindings (
                        command_id, command_version, preparation_schema_version,
                        workflow_saga_id, owner_user_id, platform_session_id,
                        client_request_id, command_kind, canonical_request_digest,
                        payload_ref, payload_digest, payload_expires_at,
                        provider_policy_digest, task_id, task_version, attempt_id,
                        attempt_number, prepared_event_id, prepared_event_digest,
                        plan_schema_version, plan_version, plan_digest,
                        workflow_preparation_digest, binding_schema_version,
                        binding_digest
                    )
                    VALUES (
                        %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s
                    )
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
            )

        with database.connect() as conn:
            assert conn.execute(
                "SELECT count(*) FROM quant_system.hermes_command_workflow_bindings"
            ).fetchone() == (0,)
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_binding_and_command_intent_are_immutable() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)

    try:
        created = ensure_bound_command(settings, _prepared())

        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_command_workflow_bindings
                SET plan_version = plan_version + 1
                WHERE command_id = %s
                """,
                (created.command_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_commands
                SET payload_ref = 'platform-payload://tampered'
                WHERE command_id = %s
                """,
                (created.command_id,),
            )
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()


def test_claim_skips_unbound_command_and_claims_only_unexpired_exact_binding() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_workflow_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        unbound = ledger.create_command(
            platform_session_id="platform-session-unbound",
            client_request_id="req-unbound-001",
            kind="research_chat",
            canonical_request_digest="9" * 64,
            payload_ref="platform-payload://research/unbound-001",
            provider_policy_digest="8" * 64,
        ).command
        bound = ensure_bound_command(settings, _prepared())
        expired = ensure_bound_command(
            settings,
            _prepared(
                workflow_saga_id="hqs_222222222222222222222222",
                platform_session_id="platform-session-expired-binding",
                client_request_id="req-expired-binding-001",
                task_id="hqt_222222222222222222222222",
                attempt_id="hqa_222222222222222222222222",
                prepared_event_id="hqe_222222222222222222222222",
            ),
        )
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "DISABLE TRIGGER trg_hermes_workflow_binding_append_only"
            )
            conn.execute(
                """
                UPDATE quant_system.hermes_command_workflow_bindings
                SET payload_expires_at = clock_timestamp() - interval '1 second'
                WHERE command_id = %s
                """,
                (expired.command_id,),
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                "ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_append_only"
            )
        assert workflow_binding_schema_version(settings) == 1

        claimed = ledger.claim_next_command(
            worker_id="worker-binding-gate",
            now=datetime.now(UTC),
            lease_duration=timedelta(seconds=30),
        )

        assert claimed is not None
        assert claimed.command_id == bound.command_id
        assert ledger.get_command(unbound.command_id).state == "queued"
        assert ledger.get_command(expired.command_id).state == "queued"
    finally:
        _reset_workflow_ledger(database)
        db.reset_database_cache()
