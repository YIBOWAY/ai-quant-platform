from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.command_ledger import (
    HermesCommandConflict,
    HermesCommandLeaseConflict,
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesCommandStateConflict,
    HermesCommandVersionConflict,
    command_ledger_schema_version,
    hermes_run_link_digest,
)
from quant_system.hermes.workflow_binding import (
    PreparedWorkflowCommand,
    ensure_bound_command,
    workflow_preparation_digest,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg


def _ensure_test_database(url: str) -> None:
    params = conninfo_to_dict(url)
    dbname = params.get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            f"QS_TEST_DATABASE_URL must point at a throwaway test database (got {dbname!r})"
        )

    maintenance_params = dict(params)
    maintenance_params["dbname"] = "postgres"
    maintenance_url = make_conninfo(**maintenance_params)
    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (dbname,),
        ).fetchone()
        if exists is None:
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


def _create_bound_test_command(
    *,
    settings: Settings,
    ledger: HermesCommandLedger,
    platform_session_id: str,
    client_request_id: str,
    canonical_request_digest: str,
):
    seed = hashlib.sha256(f"{platform_session_id}\0{client_request_id}".encode()).hexdigest()
    payload_digest = hashlib.sha256(f"payload:{seed}".encode()).hexdigest()
    draft = PreparedWorkflowCommand(
        schema_version="1.0",
        workflow_saga_id=f"hqs_{seed[:24]}",
        owner_user_id=UUID("00000000-0000-0000-0000-000000000001"),
        platform_session_id=platform_session_id,
        client_request_id=client_request_id,
        command_kind="research_chat",
        canonical_request_digest=canonical_request_digest,
        payload_ref=f"hqa-payload:sha256:{payload_digest}",
        payload_digest=payload_digest,
        payload_expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        provider_policy_digest=hashlib.sha256(f"provider:{seed}".encode()).hexdigest(),
        task_id=f"hqt_{seed[:24]}",
        task_version=1,
        attempt_id=f"hqa_{seed[:24]}",
        attempt_number=1,
        prepared_event_id=f"hqe_{seed[:24]}",
        prepared_event_digest=hashlib.sha256(f"event:{seed}".encode()).hexdigest(),
        plan_schema_version=1,
        plan_version=1,
        plan_digest=hashlib.sha256(f"plan:{seed}".encode()).hexdigest(),
        workflow_preparation_digest="0" * 64,
    )
    prepared = replace(
        draft,
        workflow_preparation_digest=workflow_preparation_digest(draft),
    )
    result = ensure_bound_command(settings, prepared)
    return ledger.get_command(result.command_id)


def _reset_hermes_ledger(database: db.Database) -> None:
    with database.connect() as conn, conn.transaction():
        # Production roles must never truncate append-only evidence. Tests use
        # the table owner and disable only user triggers inside one rollback-safe
        # transaction to isolate cases.
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
        # V1.2A: writer readiness now requires ENABLE ALWAYS ('A') on the
        # migration-005 append-only triggers, so re-enable them in ALWAYS mode
        # (not ENABLE TRIGGER USER, which would leave them origin-only/'O').
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_events "
            "ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_events "
            "ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only_truncate"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links "
            "ENABLE ALWAYS TRIGGER trg_hermes_run_links_append_only"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links "
            "ENABLE ALWAYS TRIGGER trg_hermes_run_links_append_only_truncate"
        )


def test_hermes_command_ledger_migration_is_repeatable() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    try:
        db.run_migrations(database)
        db.run_migrations(database)

        with database.connect() as conn:
            rows = conn.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'quant_system'
                  AND table_name = ANY(%s)
                ORDER BY table_name
                """,
                (
                    [
                        "hermes_commands",
                        "hermes_command_events",
                        "hermes_outbox",
                        "hermes_run_links",
                    ],
                ),
            ).fetchall()

        assert [row[0] for row in rows] == [
            "hermes_command_events",
            "hermes_commands",
            "hermes_outbox",
            "hermes_run_links",
        ]
    finally:
        db.reset_database_cache()


def test_old_migration_never_downgrades_a_future_ledger_schema_version() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        with database.connect() as conn:
            conn.execute("UPDATE quant_system.hermes_ledger_meta SET schema_version = 2")

        with pytest.raises(psycopg.Error, match="newer than this binary"):
            db.run_migrations(database)

        with database.connect() as conn:
            version = conn.execute(
                "SELECT schema_version FROM quant_system.hermes_ledger_meta"
            ).fetchone()
        assert version == (2,)
        assert command_ledger_schema_version(settings) is None
        with pytest.raises(HermesCommandLedgerUnavailable):
            HermesCommandLedger(settings).create_command(
                platform_session_id="platform-session-future-schema",
                client_request_id="req-ledger-future-schema-001",
                kind="research_chat",
                canonical_request_digest="0" * 64,
                payload_ref="platform-payload://research/future-schema-001",
            )
    finally:
        with database.connect() as conn:
            conn.execute("UPDATE quant_system.hermes_ledger_meta SET schema_version = 1")
        db.reset_database_cache()


def test_schema_readiness_rejects_column_and_trigger_drift() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "RENAME COLUMN payload_ref TO payload_ref_drifted"
            )
        assert command_ledger_schema_version(settings) is None
        with pytest.raises(HermesCommandLedgerUnavailable):
            HermesCommandLedger(settings).get_command(UUID("00000000-0000-0000-0000-000000000123"))

        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "RENAME COLUMN payload_ref_drifted TO payload_ref"
            )
            conn.execute(
                "DROP TRIGGER trg_hermes_command_events_append_only "
                "ON quant_system.hermes_command_events"
            )
        assert command_ledger_schema_version(settings) is None

        # A trigger with the expected name is not sufficient: its event mask
        # and bound function are part of the safety signature.
        with database.connect() as conn:
            conn.execute(
                """
                CREATE TRIGGER trg_hermes_command_events_append_only
                BEFORE INSERT ON quant_system.hermes_command_events
                FOR EACH ROW
                EXECUTE FUNCTION quant_system.reject_hermes_command_event_mutation()
                """
            )
        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute(
                "DROP TRIGGER IF EXISTS trg_hermes_command_events_append_only "
                "ON quant_system.hermes_command_events"
            )
            columns = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'quant_system'
                      AND table_name = 'hermes_commands'
                    """
                ).fetchall()
            }
            if "payload_ref_drifted" in columns:
                conn.execute(
                    "ALTER TABLE quant_system.hermes_commands "
                    "RENAME COLUMN payload_ref_drifted TO payload_ref"
                )
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_same_name_column_type_drift() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "ALTER COLUMN provider_policy_digest TYPE TEXT"
            )

        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "ALTER COLUMN provider_policy_digest TYPE CHAR(64)"
            )
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_same_name_column_nullability_drift() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands ALTER COLUMN payload_ref DROP NOT NULL"
            )

        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands ALTER COLUMN payload_ref SET NOT NULL"
            )
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_same_name_column_default_drift() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands ALTER COLUMN state SET DEFAULT 'failed'"
            )

        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands ALTER COLUMN state SET DEFAULT 'queued'"
            )
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_same_name_constraint_definition_drift() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands DROP CONSTRAINT ck_hermes_commands_state"
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "ADD CONSTRAINT ck_hermes_commands_state CHECK (state IS NOT NULL)"
            )

        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "DROP CONSTRAINT IF EXISTS ck_hermes_commands_state"
            )
            conn.execute(
                """
                ALTER TABLE quant_system.hermes_commands
                ADD CONSTRAINT ck_hermes_commands_state
                CHECK (state IN (
                    'queued',
                    'leased',
                    'delivered',
                    'outcome_unknown',
                    'succeeded',
                    'failed',
                    'cancelled'
                ))
                """
            )
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_requires_a_non_state_migration_check() -> None:
    """A table created by an older partial 005 must never be reported ready."""
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "DROP CONSTRAINT ck_hermes_commands_request_digest"
            )

        # CREATE TABLE IF NOT EXISTS cannot repair the missing check, so the
        # signature must remain fail-closed even after a migration rerun.
        db.run_migrations(database)
        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute(
                """
                ALTER TABLE quant_system.hermes_commands
                ADD CONSTRAINT ck_hermes_commands_request_digest
                CHECK (canonical_request_digest ~ '^[0-9a-f]{64}$')
                """
            )
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_unvalidated_same_name_constraint() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    state_check = """
        CHECK (state IN (
            'queued',
            'leased',
            'delivered',
            'outcome_unknown',
            'succeeded',
            'failed',
            'cancelled'
        ))
    """
    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands DROP CONSTRAINT ck_hermes_commands_state"
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                f"ADD CONSTRAINT ck_hermes_commands_state {state_check} NOT VALID"
            )

        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                "DROP CONSTRAINT IF EXISTS ck_hermes_commands_state"
            )
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands "
                f"ADD CONSTRAINT ck_hermes_commands_state {state_check}"
            )
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_same_name_index_definition_drift() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute("DROP INDEX quant_system.uq_hermes_commands_upstream_run")
            conn.execute(
                "CREATE INDEX uq_hermes_commands_upstream_run "
                "ON quant_system.hermes_commands (hermes_run_id, hermes_session_id)"
            )

        # IF NOT EXISTS keeps reruns non-destructive: the migration does not
        # silently replace a same-name object whose semantics are unknown.
        db.run_migrations(database)
        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute("DROP INDEX IF EXISTS quant_system.uq_hermes_commands_upstream_run")
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_invalid_same_name_index() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                """
                UPDATE pg_index
                SET indisvalid = FALSE
                WHERE indexrelid =
                    'quant_system.idx_hermes_outbox_available'::regclass
                """
            )

        assert command_ledger_schema_version(settings) is None
    finally:
        with database.connect() as conn:
            conn.execute("DROP INDEX IF EXISTS quant_system.idx_hermes_outbox_available")
        db.run_migrations(database)
        db.reset_database_cache()


def test_schema_readiness_rejects_replica_only_append_only_trigger() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    try:
        assert command_ledger_schema_version(settings) == 1
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_events "
                "ENABLE REPLICA TRIGGER trg_hermes_command_events_append_only"
            )

        assert command_ledger_schema_version(settings) is None

        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_events "
                "ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only"
            )

        assert command_ledger_schema_version(settings) == 1
    finally:
        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_events "
                "ENABLE TRIGGER trg_hermes_command_events_append_only"
            )
        db.run_migrations(database)
        db.reset_database_cache()


def test_create_command_is_idempotent_and_commits_event_with_outbox() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    client_request_id = "req-ledger-idempotent-001"

    try:
        _reset_hermes_ledger(database)

        ledger = HermesCommandLedger(settings)
        first = ledger.create_command(
            platform_session_id="platform-session-001",
            client_request_id=client_request_id,
            kind="research_chat",
            canonical_request_digest="a" * 64,
            payload_ref="platform-payload://research/001",
        )
        second = ledger.create_command(
            platform_session_id="platform-session-001",
            client_request_id=client_request_id,
            kind="research_chat",
            canonical_request_digest="a" * 64,
            payload_ref="platform-payload://research/001",
        )

        assert first.created is True
        assert second.created is False
        assert second.command == first.command
        assert first.command.state == "queued"

        with database.connect() as conn:
            command_count = conn.execute(
                "SELECT count(*) FROM quant_system.hermes_commands WHERE client_request_id = %s",
                (client_request_id,),
            ).fetchone()[0]
            event_rows = conn.execute(
                """
                SELECT command_version,
                       event_type,
                       actor,
                       from_state,
                       to_state,
                       canonical_request_digest
                FROM quant_system.hermes_command_events
                WHERE command_id = %s
                """,
                (first.command.command_id,),
            ).fetchall()
            outbox_rows = conn.execute(
                """
                SELECT command_version, topic, consumed_at
                FROM quant_system.hermes_outbox
                WHERE command_id = %s
                """,
                (first.command.command_id,),
            ).fetchall()

        assert command_count == 1
        assert event_rows == [(1, "command_created", "system", None, "queued", "a" * 64)]
        assert outbox_rows == [(1, "hermes.command.queued", None)]
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_same_session_request_id_with_different_digest_conflicts_without_writes() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        first = ledger.create_command(
            platform_session_id="platform-session-conflict",
            client_request_id="req-ledger-conflict-001",
            kind="research_chat",
            canonical_request_digest="a" * 64,
            payload_ref="platform-payload://research/conflict-001",
        )

        with pytest.raises(HermesCommandConflict):
            ledger.create_command(
                platform_session_id="platform-session-conflict",
                client_request_id="req-ledger-conflict-001",
                kind="research_chat",
                canonical_request_digest="b" * 64,
                payload_ref="platform-payload://research/conflict-001",
            )

        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_events),
                    (SELECT count(*) FROM quant_system.hermes_outbox)
                """
            ).fetchone()

        assert first.created is True
        assert counts == (1, 1, 1)
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_concurrent_same_intent_creates_one_command_event_and_outbox() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)

    def create_once() -> tuple[str, bool]:
        result = ledger.create_command(
            platform_session_id="platform-session-concurrent",
            client_request_id="req-ledger-concurrent-001",
            kind="research_chat",
            canonical_request_digest="c" * 64,
            payload_ref="platform-payload://research/concurrent-001",
        )
        return str(result.command.command_id), result.created

    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _index: create_once(), range(20)))

        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_events),
                    (SELECT count(*) FROM quant_system.hermes_outbox)
                """
            ).fetchone()

        assert len({command_id for command_id, _created in results}) == 1
        assert sum(created for _command_id, created in results) == 1
        assert counts == (1, 1, 1)
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_outbox_insert_failure_rolls_back_command_and_event() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    with database.connect() as conn:
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION quant_system.test_fail_hermes_outbox()
            RETURNS TRIGGER
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'injected outbox failure';
            END;
            $$
            """
        )
        conn.execute(
            """
            CREATE TRIGGER trg_test_fail_hermes_outbox
            BEFORE INSERT ON quant_system.hermes_outbox
            FOR EACH ROW
            EXECUTE FUNCTION quant_system.test_fail_hermes_outbox()
            """
        )

    try:
        ledger = HermesCommandLedger(settings)
        with pytest.raises(HermesCommandLedgerUnavailable):
            ledger.create_command(
                platform_session_id="platform-session-rollback",
                client_request_id="req-ledger-rollback-001",
                kind="research_chat",
                canonical_request_digest="d" * 64,
                payload_ref="platform-payload://research/rollback-001",
            )

        with database.connect() as conn:
            counts = conn.execute(
                """
                SELECT
                    (SELECT count(*) FROM quant_system.hermes_commands),
                    (SELECT count(*) FROM quant_system.hermes_command_events),
                    (SELECT count(*) FROM quant_system.hermes_outbox)
                """
            ).fetchone()
        assert counts == (0, 0, 0)
    finally:
        with database.connect() as conn:
            conn.execute(
                "DROP TRIGGER IF EXISTS trg_test_fail_hermes_outbox ON quant_system.hermes_outbox"
            )
            conn.execute("DROP FUNCTION IF EXISTS quant_system.test_fail_hermes_outbox()")
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_cancel_queued_command_uses_expected_version_and_appends_snapshot_event() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        created = ledger.create_command(
            platform_session_id="platform-session-cancel",
            client_request_id="req-ledger-cancel-001",
            kind="research_chat",
            canonical_request_digest="e" * 64,
            payload_ref="platform-payload://research/cancel-001",
        ).command

        cancelled = ledger.cancel_queued_command(
            command_id=created.command_id,
            expected_version=created.version,
        )

        assert cancelled.state == "cancelled"
        assert cancelled.version == 2
        with pytest.raises(HermesCommandVersionConflict):
            ledger.cancel_queued_command(
                command_id=created.command_id,
                expected_version=created.version,
            )

        with database.connect() as conn:
            event = conn.execute(
                """
                SELECT command_version,
                       event_type,
                       actor,
                       from_state,
                       to_state,
                       attempt_count,
                       lease_token,
                       hermes_run_id,
                       error_code
                FROM quant_system.hermes_command_events
                WHERE command_id = %s
                ORDER BY command_version DESC
                LIMIT 1
                """,
                (created.command_id,),
            ).fetchone()
            outbox = conn.execute(
                """
                SELECT consumed_by, consumed_at
                FROM quant_system.hermes_outbox
                WHERE command_id = %s AND topic = 'hermes.command.queued'
                """,
                (created.command_id,),
            ).fetchone()

        assert event == (
            2,
            "command_cancelled",
            "system",
            "queued",
            "cancelled",
            0,
            None,
            None,
            None,
        )
        assert outbox[0] == "system:command_cancelled"
        assert outbox[1] is not None
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_command_events_reject_update_and_delete() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        command = ledger.create_command(
            platform_session_id="platform-session-append-only",
            client_request_id="req-ledger-append-only-001",
            kind="research_chat",
            canonical_request_digest="f" * 64,
            payload_ref="platform-payload://research/append-only-001",
        ).command

        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_command_events
                SET actor = 'worker'
                WHERE command_id = %s
                """,
                (command.command_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.hermes_command_events WHERE command_id = %s",
                (command.command_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                "TRUNCATE quant_system.hermes_command_workflow_bindings, "
                "quant_system.hermes_command_events"
            )
        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute("TRUNCATE quant_system.hermes_run_links")
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_manual_rollback_and_reapply_preserve_preexisting_platform_schema() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    rollback_sql = Path("scripts/sql/rollback/005_hermes_command_ledger.down.sql").read_text(
        encoding="utf-8"
    )
    binding_rollback_sql = Path(
        "scripts/sql/rollback/006_hermes_workflow_binding.down.sql"
    ).read_text(encoding="utf-8")

    try:
        with database.connect() as conn:
            root_before = conn.execute(
                "SELECT username FROM quant_system.app_users WHERE username = 'root'"
            ).fetchone()
            conn.execute(binding_rollback_sql)
            conn.execute(rollback_sql)
            ledger_table_after_rollback = conn.execute(
                "SELECT to_regclass('quant_system.hermes_commands')"
            ).fetchone()[0]

        assert root_before == ("root",)
        assert ledger_table_after_rollback is None

        db.run_migrations(database)
        with database.connect() as conn:
            root_after = conn.execute(
                "SELECT username FROM quant_system.app_users WHERE username = 'root'"
            ).fetchone()
            schema_version = conn.execute(
                "SELECT schema_version FROM quant_system.hermes_ledger_meta"
            ).fetchone()

        assert root_after == ("root",)
        assert schema_version == (1,)
    finally:
        db.run_migrations(database)
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_claim_next_uses_lease_token_and_consumes_matching_outbox_wakeup() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 9, 30, tzinfo=UTC)

    try:
        created = _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-claim",
            client_request_id="req-ledger-claim-001",
            canonical_request_digest="1" * 64,
        )

        claimed = ledger.claim_next_command(
            worker_id="worker-a",
            now=now,
            lease_duration=timedelta(seconds=30),
        )

        assert claimed is not None
        assert claimed.command_id == created.command_id
        assert claimed.state == "leased"
        assert claimed.version == 2
        assert claimed.lease_owner == "worker-a"
        assert claimed.lease_token is not None
        assert claimed.lease_until is not None
        assert (claimed.lease_until - claimed.updated_at).total_seconds() == pytest.approx(
            30,
            abs=0.01,
        )
        assert claimed.dispatch_started_at is None

        with database.connect() as conn:
            event = conn.execute(
                """
                SELECT event_type, from_state, to_state, lease_owner, lease_token
                FROM quant_system.hermes_command_events
                WHERE command_id = %s AND command_version = 2
                """,
                (created.command_id,),
            ).fetchone()
            outbox = conn.execute(
                """
                SELECT consumed_by, consumed_at
                FROM quant_system.hermes_outbox
                WHERE command_id = %s AND command_version = 1
                """,
                (created.command_id,),
            ).fetchone()

        assert event == (
            "command_leased",
            "queued",
            "leased",
            "worker-a",
            claimed.lease_token,
        )
        assert outbox[0] == "worker-a"
        assert outbox[1] >= claimed.updated_at
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_concurrent_workers_claim_distinct_commands() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 9, 40, tzinfo=UTC)

    try:
        created_ids = {
            _create_bound_test_command(
                settings=settings,
                ledger=ledger,
                platform_session_id="platform-session-multi-claim",
                client_request_id=f"req-ledger-multi-claim-{index}",
                canonical_request_digest=str(index) * 64,
            ).command_id
            for index in (2, 3)
        }

        def claim(worker_id: str):
            return ledger.claim_next_command(
                worker_id=worker_id,
                now=now,
                lease_duration=timedelta(seconds=30),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(claim, ("worker-a", "worker-b")))

        assert all(command is not None for command in claimed)
        assert {command.command_id for command in claimed if command is not None} == created_ids
        assert {command.lease_owner for command in claimed if command is not None} == {
            "worker-a",
            "worker-b",
        }
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_heartbeat_requires_current_version_and_lease_token() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 9, 50, tzinfo=UTC)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-heartbeat",
            client_request_id="req-ledger-heartbeat-001",
            canonical_request_digest="4" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-heartbeat",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None

        with pytest.raises(HermesCommandLeaseConflict):
            ledger.heartbeat_lease(
                command_id=claimed.command_id,
                expected_version=claimed.version,
                lease_token=UUID("00000000-0000-0000-0000-000000000099"),
                now=now + timedelta(seconds=5),
                lease_duration=timedelta(seconds=30),
            )

        heartbeat = ledger.heartbeat_lease(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=5),
            lease_duration=timedelta(seconds=30),
        )

        assert heartbeat.version == 3
        assert heartbeat.state == "leased"
        assert heartbeat.lease_token == claimed.lease_token
        assert heartbeat.lease_until is not None
        assert (heartbeat.lease_until - heartbeat.updated_at).total_seconds() == pytest.approx(
            30, abs=0.01
        )
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_database_clock_owns_lease_and_caller_time_cannot_bypass_expiry() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-db-clock",
            client_request_id="req-ledger-db-clock-001",
            canonical_request_digest="0" * 64,
        )
        with database.connect() as conn:
            before = conn.execute("SELECT clock_timestamp()").fetchone()[0]

        claimed = ledger.claim_next_command(
            worker_id="worker-db-clock",
            now=datetime(2099, 1, 1, tzinfo=UTC),
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None

        with database.connect() as conn:
            after = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            conn.execute(
                """
                UPDATE quant_system.hermes_commands
                SET lease_until = clock_timestamp() - interval '1 second'
                WHERE command_id = %s
                """,
                (claimed.command_id,),
            )

        assert claimed.lease_until is not None
        assert before + timedelta(seconds=29) <= claimed.lease_until
        assert claimed.lease_until <= after + timedelta(seconds=31)
        with pytest.raises(HermesCommandLeaseConflict):
            ledger.mark_dispatch_started(
                command_id=claimed.command_id,
                expected_version=claimed.version,
                lease_token=claimed.lease_token,
                now=datetime(1999, 1, 1, tzinfo=UTC),
            )
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_blocked_heartbeat_cannot_cross_the_real_lease_deadline() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-lock-fencing",
            client_request_id="req-ledger-lock-fencing-001",
            canonical_request_digest="9" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-lock-fencing",
            now=datetime(2099, 1, 1, tzinfo=UTC),
            lease_duration=timedelta(seconds=1),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        assert claimed.lease_until is not None

        with ThreadPoolExecutor(max_workers=1) as pool:
            with database.connect() as lock_conn, lock_conn.transaction():
                lock_conn.execute(
                    "SELECT 1 FROM quant_system.hermes_commands WHERE command_id = %s FOR UPDATE",
                    (claimed.command_id,),
                )
                heartbeat = pool.submit(
                    ledger.heartbeat_lease,
                    command_id=claimed.command_id,
                    expected_version=claimed.version,
                    lease_token=claimed.lease_token,
                    now=datetime(1999, 1, 1, tzinfo=UTC),
                    lease_duration=timedelta(seconds=30),
                )

                deadline = time.monotonic() + 1.0
                blocked = False
                while time.monotonic() < deadline:
                    with database.connect() as observer:
                        blocked = bool(
                            observer.execute(
                                """
                                SELECT 1
                                FROM pg_stat_activity
                                WHERE datname = current_database()
                                  AND wait_event_type = 'Lock'
                                  AND query LIKE '%%quant_system.hermes_commands%%'
                                  AND query LIKE '%%FOR UPDATE%%'
                                """
                            ).fetchone()
                        )
                    if blocked:
                        break
                    time.sleep(0.01)
                assert blocked, "heartbeat UPDATE did not block on the held command row"

                with database.connect() as observer:
                    server_now = observer.execute("SELECT clock_timestamp()").fetchone()[0]
                remaining = (claimed.lease_until - server_now).total_seconds()
                if remaining > 0:
                    time.sleep(remaining + 0.15)

                # Exiting the transaction releases the row lock only after the
                # real server-side lease deadline has passed.

            with pytest.raises(HermesCommandLeaseConflict):
                heartbeat.result(timeout=2)
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_expired_lease_requeues_only_before_dispatch_and_reconciles_after_dispatch() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)

    try:
        for index in (5, 6):
            _create_bound_test_command(
                settings=settings,
                ledger=ledger,
                platform_session_id="platform-session-expiry",
                client_request_id=f"req-ledger-expiry-{index}",
                canonical_request_digest=str(index) * 64,
            )

        dispatched_claim = ledger.claim_next_command(
            worker_id="worker-expiry-a",
            now=now,
            lease_duration=timedelta(seconds=10),
        )
        untouched_claim = ledger.claim_next_command(
            worker_id="worker-expiry-b",
            now=now,
            lease_duration=timedelta(seconds=10),
        )
        assert dispatched_claim is not None
        assert dispatched_claim.lease_token is not None
        assert untouched_claim is not None

        dispatch_started = ledger.mark_dispatch_started(
            command_id=dispatched_claim.command_id,
            expected_version=dispatched_claim.version,
            lease_token=dispatched_claim.lease_token,
            now=now + timedelta(seconds=1),
        )
        assert dispatch_started.attempt_count == 1
        assert dispatch_started.dispatch_started_at == dispatch_started.updated_at

        with database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_commands
                SET lease_until = statement_timestamp() - interval '1 second'
                WHERE command_id = ANY(%s)
                """,
                ([dispatched_claim.command_id, untouched_claim.command_id],),
            )

        recovered = ledger.reconcile_expired_leases(
            now=now + timedelta(seconds=20),
            limit=10,
        )

        assert [command.command_id for command in recovered.requeued] == [
            untouched_claim.command_id
        ]
        assert [command.command_id for command in recovered.outcome_unknown] == [
            dispatched_claim.command_id
        ]
        assert recovered.requeued[0].state == "queued"
        assert recovered.requeued[0].dispatch_started_at is None
        assert recovered.outcome_unknown[0].state == "outcome_unknown"
        assert recovered.outcome_unknown[0].last_error_code == "lease_expired_after_dispatch"

        with database.connect() as conn:
            wakeups = conn.execute(
                """
                SELECT command_id, command_version, topic
                FROM quant_system.hermes_outbox
                WHERE command_version > 1
                ORDER BY command_id, command_version
                """
            ).fetchall()
        assert {(row[0], row[2]) for row in wakeups} == {
            (untouched_claim.command_id, "hermes.command.queued"),
            (dispatched_claim.command_id, "hermes.command.reconcile"),
        }
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_command_commit_emits_postgres_wakeup_after_durable_outbox() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)

    try:
        with database.connect() as listener:
            listener.execute("LISTEN quant_system_hermes_commands")
            command = ledger.create_command(
                platform_session_id="platform-session-notify",
                client_request_id="req-ledger-notify-001",
                kind="research_chat",
                canonical_request_digest="7" * 64,
                payload_ref="platform-payload://research/notify-001",
            ).command
            notifications = list(listener.notifies(timeout=1.0, stop_after=1))

        assert len(notifications) == 1
        assert notifications[0].channel == "quant_system_hermes_commands"
        assert notifications[0].payload == str(command.command_id)
        with database.connect() as conn:
            assert conn.execute(
                "SELECT count(*) FROM quant_system.hermes_outbox WHERE command_id = %s",
                (command.command_id,),
            ).fetchone() == (1,)
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_delivered_transition_requires_dispatch_and_fences_the_worker_lease() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 10, 10, tzinfo=UTC)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-delivered",
            client_request_id="req-ledger-delivered-001",
            canonical_request_digest="8" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-delivered",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None

        with pytest.raises(HermesCommandStateConflict):
            ledger.mark_delivered(
                command_id=claimed.command_id,
                expected_version=claimed.version,
                lease_token=claimed.lease_token,
                now=now + timedelta(seconds=1),
                hermes_session_id="hermes-session-delivered",
                hermes_run_id="hermes-run-delivered",
            )

        dispatch = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )
        delivered = ledger.mark_delivered(
            command_id=dispatch.command_id,
            expected_version=dispatch.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
            hermes_session_id="hermes-session-delivered",
            hermes_run_id="hermes-run-delivered",
        )

        assert delivered.state == "delivered"
        assert delivered.version == 4
        assert delivered.hermes_session_id == "hermes-session-delivered"
        assert delivered.hermes_run_id == "hermes-run-delivered"
        assert delivered.lease_owner is None
        assert delivered.lease_token is None
        assert delivered.lease_until is None

        with pytest.raises(HermesCommandStateConflict):
            ledger.mark_delivered(
                command_id=delivered.command_id,
                expected_version=delivered.version,
                lease_token=claimed.lease_token,
                now=now + timedelta(seconds=3),
                hermes_session_id="hermes-session-delivered",
                hermes_run_id="hermes-run-delivered",
            )

        with database.connect() as conn:
            event = conn.execute(
                """
                SELECT command_version, event_type, from_state, to_state,
                       hermes_session_id, hermes_run_id, lease_token
                FROM quant_system.hermes_command_events
                WHERE command_id = %s AND command_version = 4
                """,
                (delivered.command_id,),
            ).fetchone()
        assert event == (
            4,
            "command_delivered",
            "leased",
            "delivered",
            "hermes-session-delivered",
            "hermes-run-delivered",
            None,
        )
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_dispatch_timeout_becomes_outcome_unknown_and_cannot_be_blindly_reclaimed() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 10, 20, tzinfo=UTC)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-timeout",
            client_request_id="req-ledger-timeout-001",
            canonical_request_digest="9" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-timeout",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        dispatched = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )

        unknown = ledger.mark_dispatch_timeout(
            command_id=dispatched.command_id,
            expected_version=dispatched.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
            error_code="hermes_response_timeout",
        )

        assert unknown.state == "outcome_unknown"
        assert unknown.version == 4
        assert unknown.last_error_code == "hermes_response_timeout"
        assert unknown.next_attempt_at is None
        assert unknown.lease_token is None
        assert (
            ledger.claim_next_command(
                worker_id="worker-must-not-retry",
                now=now + timedelta(hours=1),
                lease_duration=timedelta(seconds=30),
            )
            is None
        )

        with database.connect() as conn:
            event = conn.execute(
                """
                SELECT event_type, from_state, to_state, error_code
                FROM quant_system.hermes_command_events
                WHERE command_id = %s AND command_version = 4
                """,
                (unknown.command_id,),
            ).fetchone()
            reconcile = conn.execute(
                """
                SELECT topic, consumed_at
                FROM quant_system.hermes_outbox
                WHERE command_id = %s AND command_version = 4
                """,
                (unknown.command_id,),
            ).fetchone()
        assert event == (
            "dispatch_timed_out",
            "leased",
            "outcome_unknown",
            "hermes_response_timeout",
        )
        assert reconcile == ("hermes.command.reconcile", None)
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_delivered_run_can_reach_succeeded_terminal_state_with_evidence() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-success",
            client_request_id="req-ledger-success-001",
            canonical_request_digest="a" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-success",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        dispatched = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )
        delivered = ledger.mark_delivered(
            command_id=dispatched.command_id,
            expected_version=dispatched.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
            hermes_session_id="hermes-session-success",
            hermes_run_id="hermes-run-success",
        )

        succeeded = ledger.mark_succeeded(
            command_id=delivered.command_id,
            expected_version=delivered.version,
            now=now + timedelta(seconds=3),
            hermes_session_id="hermes-session-success",
            hermes_run_id="hermes-run-success",
            evidence_digest="b" * 64,
        )

        assert succeeded.state == "succeeded"
        assert succeeded.version == 5
        assert succeeded.last_error_code is None
        with pytest.raises(HermesCommandStateConflict):
            ledger.mark_succeeded(
                command_id=succeeded.command_id,
                expected_version=succeeded.version,
                now=now + timedelta(seconds=4),
                hermes_session_id="hermes-session-success",
                hermes_run_id="hermes-run-success",
                evidence_digest="b" * 64,
            )

        with database.connect() as conn:
            event = conn.execute(
                """
                SELECT event_type, from_state, to_state, event_data
                FROM quant_system.hermes_command_events
                WHERE command_id = %s AND command_version = 5
                """,
                (succeeded.command_id,),
            ).fetchone()
        assert event == (
            "command_succeeded",
            "delivered",
            "succeeded",
            {"evidence_digest": "b" * 64},
        )
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_reconciler_can_resolve_outcome_unknown_as_failed_without_requeue() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 10, 40, tzinfo=UTC)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-failure",
            client_request_id="req-ledger-failure-001",
            canonical_request_digest="c" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-failure",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        dispatched = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )
        unknown = ledger.mark_dispatch_timeout(
            command_id=dispatched.command_id,
            expected_version=dispatched.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
        )

        failed = ledger.mark_failed(
            command_id=unknown.command_id,
            expected_version=unknown.version,
            now=now + timedelta(seconds=3),
            hermes_session_id="hermes-session-failure",
            hermes_run_id="hermes-run-failure",
            evidence_digest="d" * 64,
            error_code="hermes_run_failed",
        )

        assert failed.state == "failed"
        assert failed.version == 5
        assert failed.hermes_session_id == "hermes-session-failure"
        assert failed.hermes_run_id == "hermes-run-failure"
        assert failed.last_error_code == "hermes_run_failed"
        assert failed.next_attempt_at is None

        with database.connect() as conn:
            event = conn.execute(
                """
                SELECT event_type, actor, from_state, to_state, error_code, event_data
                FROM quant_system.hermes_command_events
                WHERE command_id = %s AND command_version = 5
                """,
                (failed.command_id,),
            ).fetchone()
            reconcile_outbox = conn.execute(
                """
                SELECT consumed_by, consumed_at
                FROM quant_system.hermes_outbox
                WHERE command_id = %s
                  AND topic = 'hermes.command.reconcile'
                """,
                (failed.command_id,),
            ).fetchone()
        assert event == (
            "command_failed",
            "reconciler",
            "outcome_unknown",
            "failed",
            "hermes_run_failed",
            {"evidence_digest": "d" * 64},
        )
        assert reconcile_outbox[0] == "reconciler:resolved"
        assert reconcile_outbox[1] is not None
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_authoritative_dispatch_rejection_is_terminal_and_lease_fenced() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 10, 50, tzinfo=UTC)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-rejected",
            client_request_id="req-ledger-rejected-001",
            canonical_request_digest="e" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-rejected",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        dispatched = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )

        with pytest.raises(HermesCommandLeaseConflict):
            ledger.mark_dispatch_rejected(
                command_id=dispatched.command_id,
                expected_version=dispatched.version,
                lease_token=UUID("00000000-0000-0000-0000-000000000099"),
                now=now + timedelta(seconds=2),
                evidence_digest="f" * 64,
                error_code="hermes_request_rejected",
            )

        failed = ledger.mark_dispatch_rejected(
            command_id=dispatched.command_id,
            expected_version=dispatched.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
            evidence_digest="f" * 64,
            error_code="hermes_request_rejected",
        )

        assert failed.state == "failed"
        assert failed.version == 4
        assert failed.hermes_run_id is None
        assert failed.lease_token is None
        assert failed.last_error_code == "hermes_request_rejected"
        assert (
            ledger.claim_next_command(
                worker_id="worker-no-retry-after-reject",
                now=now + timedelta(hours=1),
                lease_duration=timedelta(seconds=30),
            )
            is None
        )
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_exact_run_link_is_digest_bound_idempotent_and_queryable_by_both_sides() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 11, 0, tzinfo=UTC)
    other_user_id = UUID("00000000-0000-0000-0000-000000000002")
    other_command_id = UUID("00000000-0000-0000-0000-000000000102")

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-link",
            client_request_id="req-ledger-link-001",
            canonical_request_digest="1" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-link",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        dispatched = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )
        delivered = ledger.mark_delivered(
            command_id=dispatched.command_id,
            expected_version=dispatched.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
            hermes_session_id="hermes-session-link",
            hermes_run_id="hermes-run-link",
        )
        digest = hermes_run_link_digest(
            command_id=delivered.command_id,
            platform_resource_type="experiment",
            platform_resource_id="experiment-20260715-001",
            relation="output",
            hermes_session_id="hermes-session-link",
            hermes_run_id="hermes-run-link",
            source_event_id="event-terminal-001",
        )

        first = ledger.record_run_link(
            command_id=delivered.command_id,
            expected_version=delivered.version,
            platform_resource_type="experiment",
            platform_resource_id="experiment-20260715-001",
            relation="output",
            hermes_session_id="hermes-session-link",
            hermes_run_id="hermes-run-link",
            link_digest=digest,
            source_event_id="event-terminal-001",
            observed_at=now + timedelta(seconds=3),
        )
        second = ledger.record_run_link(
            command_id=delivered.command_id,
            expected_version=delivered.version,
            platform_resource_type="experiment",
            platform_resource_id="experiment-20260715-001",
            relation="output",
            hermes_session_id="hermes-session-link",
            hermes_run_id="hermes-run-link",
            link_digest=digest,
            source_event_id="event-terminal-001",
            observed_at=now + timedelta(seconds=4),
        )

        assert first.created is True
        assert second.created is False
        assert second.link == first.link
        assert first.link.link_digest == digest
        assert ledger.list_run_links_for_command(delivered.command_id) == (first.link,)
        assert ledger.list_run_links_for_resource(
            platform_resource_type="experiment",
            platform_resource_id="experiment-20260715-001",
        ) == (first.link,)

        second_digest = hermes_run_link_digest(
            command_id=delivered.command_id,
            platform_resource_type="experiment",
            platform_resource_id="experiment-20260715-001",
            relation="context",
            hermes_session_id="hermes-session-link",
            hermes_run_id="hermes-run-link",
            source_event_id="event-terminal-002",
        )
        context_link = ledger.record_run_link(
            command_id=delivered.command_id,
            expected_version=delivered.version,
            platform_resource_type="experiment",
            platform_resource_id="experiment-20260715-001",
            relation="context",
            hermes_session_id="hermes-session-link",
            hermes_run_id="hermes-run-link",
            link_digest=second_digest,
            source_event_id="event-terminal-002",
            observed_at=now + timedelta(seconds=5),
        ).link

        with database.connect() as conn, conn.transaction():
            conn.execute(
                """
                INSERT INTO quant_system.app_users (id, username, role, is_active)
                VALUES (%s, 'run-link-isolation-user', 'user', TRUE)
                ON CONFLICT (id) DO UPDATE
                SET username = EXCLUDED.username,
                    role = EXCLUDED.role,
                    is_active = TRUE
                """,
                (other_user_id,),
            )
            conn.execute(
                """
                INSERT INTO quant_system.hermes_commands (
                    command_id,
                    owner_user_id,
                    platform_session_id,
                    client_request_id,
                    kind,
                    canonical_request_digest,
                    payload_ref,
                    state,
                    version,
                    hermes_session_id,
                    hermes_run_id
                )
                VALUES (
                    %s, %s, 'other-platform-session', 'other-request-001',
                    'research_chat', %s, 'platform-payload://other/link-001',
                    'delivered', 1, 'other-hermes-session', 'other-hermes-run'
                )
                """,
                (other_command_id, other_user_id, "e" * 64),
            )
            conn.execute(
                """
                INSERT INTO quant_system.hermes_run_links (
                    link_id,
                    command_id,
                    platform_resource_type,
                    platform_resource_id,
                    relation,
                    hermes_session_id,
                    hermes_run_id,
                    link_digest,
                    source_event_id,
                    observed_at
                )
                VALUES (
                    %s, %s, 'experiment', 'experiment-20260715-001',
                    'input', 'other-hermes-session', 'other-hermes-run',
                    %s, 'other-event-001', %s
                )
                """,
                (
                    UUID("00000000-0000-0000-0000-000000000202"),
                    other_command_id,
                    "f" * 64,
                    now + timedelta(seconds=6),
                ),
            )

        batch = ledger.list_run_links_for_resources(
            resources=(
                ("experiment", "experiment-20260715-001"),
                ("experiment", "experiment-with-no-links"),
            ),
            limit_per_resource=1,
        )
        assert batch[("experiment", "experiment-20260715-001")].links == (first.link,)
        assert batch[("experiment", "experiment-20260715-001")].has_more is True
        assert batch[("experiment", "experiment-with-no-links")].links == ()
        assert batch[("experiment", "experiment-with-no-links")].has_more is False
        complete_owner_batch = ledger.list_run_links_for_resources(
            resources=(("experiment", "experiment-20260715-001"),),
            limit_per_resource=100,
        )
        assert complete_owner_batch[("experiment", "experiment-20260715-001")].links == (
            first.link,
            context_link,
        )
        assert complete_owner_batch[("experiment", "experiment-20260715-001")].has_more is False
        assert ledger.list_run_links_for_resource(
            platform_resource_type="experiment",
            platform_resource_id="experiment-20260715-001",
        ) == (first.link, context_link)

        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_run_links
                SET platform_resource_id = 'experiment-tampered'
                WHERE link_id = %s
                """,
                (first.link.link_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.hermes_run_links WHERE link_id = %s",
                (first.link.link_id,),
            )
    finally:
        _reset_hermes_ledger(database)
        with database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.app_users WHERE id = %s",
                (other_user_id,),
            )
        db.reset_database_cache()


def test_command_event_and_outbox_projections_are_readable_in_durable_order() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 11, 10, tzinfo=UTC)

    try:
        created = _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-projection",
            client_request_id="req-ledger-projection-001",
            canonical_request_digest="2" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-projection",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        dispatched = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )
        unknown = ledger.mark_dispatch_timeout(
            command_id=dispatched.command_id,
            expected_version=dispatched.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
        )

        assert ledger.get_command(created.command_id) == unknown
        events = ledger.list_command_events(created.command_id)
        assert [event.command_version for event in events] == [1, 2, 3, 4]
        assert [event.event_id for event in events] == sorted(event.event_id for event in events)
        assert (
            ledger.list_command_events(
                created.command_id,
                after_event_id=events[1].event_id,
            )
            == events[2:]
        )

        outbox = ledger.list_command_outbox(created.command_id)
        assert [(entry.command_version, entry.topic) for entry in outbox] == [
            (1, "hermes.command.queued"),
            (4, "hermes.command.reconcile"),
        ]
        assert outbox[0].consumed_by == "worker-projection"
        assert outbox[0].consumed_at is not None
        assert outbox[0].consumed_at >= claimed.updated_at
        assert outbox[1].consumed_by is None
        assert outbox[1].consumed_at is None
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()


def test_reconciliation_can_bind_a_recovered_active_run_without_retrying_dispatch() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_hermes_ledger(database)
    ledger = HermesCommandLedger(settings)
    now = datetime(2026, 7, 15, 11, 20, tzinfo=UTC)

    try:
        _create_bound_test_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-recovered",
            client_request_id="req-ledger-recovered-001",
            canonical_request_digest="3" * 64,
        )
        claimed = ledger.claim_next_command(
            worker_id="worker-recovered",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert claimed is not None
        assert claimed.lease_token is not None
        dispatched = ledger.mark_dispatch_started(
            command_id=claimed.command_id,
            expected_version=claimed.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=1),
        )
        unknown = ledger.mark_dispatch_timeout(
            command_id=dispatched.command_id,
            expected_version=dispatched.version,
            lease_token=claimed.lease_token,
            now=now + timedelta(seconds=2),
        )

        recovered = ledger.reconcile_outcome_as_delivered(
            command_id=unknown.command_id,
            expected_version=unknown.version,
            now=now + timedelta(seconds=3),
            hermes_session_id="hermes-session-recovered",
            hermes_run_id="hermes-run-recovered",
            evidence_digest="4" * 64,
        )

        assert recovered.state == "delivered"
        assert recovered.version == 5
        assert recovered.hermes_session_id == "hermes-session-recovered"
        assert recovered.hermes_run_id == "hermes-run-recovered"
        assert recovered.last_error_code is None
        assert recovered.attempt_count == 1
    finally:
        _reset_hermes_ledger(database)
        db.reset_database_cache()
