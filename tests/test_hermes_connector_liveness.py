from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.connector_liveness import (
    CONNECTOR_LIVENESS_SCHEMA_VERSION,
    ConnectorLivenessAuthority,
    ConnectorLivenessConflict,
    ConnectorLivenessLeaseLost,
    ConnectorWorkerRecord,
    connector_liveness_runtime_security_is_ready_on_connection,
    connector_liveness_schema_is_ready_on_connection,
    evaluate_connector_liveness,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
PLATFORM_DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
WORKSPACE = "root"
RUNTIME_LOGIN = "aqp_connector_liveness_runtime_test"
READONLY_LOGIN = "aqp_connector_liveness_readonly_test"
TEST_PASSWORD = "connector-liveness-test-only"
MIGRATIONS = (
    "003_app_users_brief_ai_reports.sql",
    "014_agent_v02_connector_liveness.sql",
)


def _ensure_test_database(url: str) -> None:
    params = conninfo_to_dict(url)
    dbname = params.get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            f"QS_TEST_DATABASE_URL must point at a throwaway test database (got {dbname!r})"
        )
    maintenance = dict(params)
    maintenance["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**maintenance), autocommit=True) as conn:
        if (
            conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (dbname,),
            ).fetchone()
            is None
        ):
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def _settings() -> Settings:
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


def _url_as(url: str, *, user: str) -> str:
    params = conninfo_to_dict(url)
    params["user"] = user
    params["password"] = TEST_PASSWORD
    return make_conninfo(**params)


def _ensure_roles_and_replay(database: db.Database) -> None:
    with database.connect() as conn:
        for role_name in ("quant_migrator", "quant_runtime", "quant_readonly"):
            if (
                conn.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s",
                    (role_name,),
                ).fetchone()
                is None
            ):
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role_name))
                )
        for login, group in (
            (RUNTIME_LOGIN, "quant_runtime"),
            (READONLY_LOGIN, "quant_readonly"),
        ):
            if (
                conn.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s",
                    (login,),
                ).fetchone()
                is not None
            ):
                conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)))
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(TEST_PASSWORD))
            )
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier(group),
                    sql.Identifier(login),
                )
            )
    db.run_migrations(
        database,
        only=("014_agent_v02_connector_liveness.sql",),
    )


def _authority() -> tuple[ConnectorLivenessAuthority, db.Database, Settings]:
    settings = _settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database, only=MIGRATIONS)
    _ensure_roles_and_replay(database)
    with database.connect() as conn:
        conn.execute("TRUNCATE quant_system.agent_v02_connector_workers")
    return ConnectorLivenessAuthority(settings), database, settings


def _record(**overrides: object) -> ConnectorWorkerRecord:
    base = ConnectorWorkerRecord(
        generation_token="11111111-1111-4111-8111-111111111111",
        workspace_id=WORKSPACE,
        worker_id="connector-1",
        mode="supervised_dispatch",
        runtime_digest=PLATFORM_DIGEST,
        status="active",
        started_at=NOW - timedelta(seconds=10),
        heartbeat_at=NOW - timedelta(seconds=1),
        stopped_at=None,
        stop_reason=None,
    )
    return replace(base, **overrides)


@pytest.mark.parametrize(
    ("record", "expected_digest", "lock_held", "reason"),
    [
        (
            _record(heartbeat_at=NOW - timedelta(seconds=31)),
            PLATFORM_DIGEST,
            True,
            "connector_heartbeat_stale",
        ),
        (
            _record(status="stopped", stopped_at=NOW),
            PLATFORM_DIGEST,
            True,
            "connector_not_active",
        ),
        (
            _record(mode="reconcile_only"),
            PLATFORM_DIGEST,
            True,
            "connector_mode_not_supervised",
        ),
        (_record(), OTHER_DIGEST, True, "connector_runtime_digest_mismatch"),
        (_record(), PLATFORM_DIGEST, False, "connector_session_lock_missing"),
    ],
)
def test_gate_decision_fails_closed(
    record: ConnectorWorkerRecord,
    expected_digest: str,
    lock_held: bool,
    reason: str,
) -> None:
    probe = evaluate_connector_liveness(
        record,
        expected_runtime_digest=expected_digest,
        now=NOW,
        max_heartbeat_age_seconds=30,
        session_lock_held=lock_held,
    )

    assert probe.ready is False
    assert probe.reason == reason


def test_gate_decision_accepts_only_exact_fresh_supervised_worker() -> None:
    probe = evaluate_connector_liveness(
        _record(),
        expected_runtime_digest=PLATFORM_DIGEST,
        now=NOW,
        max_heartbeat_age_seconds=30,
        session_lock_held=True,
    )

    assert probe.ready is True
    assert probe.reason == "ready"
    assert probe.generation_token == "11111111-1111-4111-8111-111111111111"


def test_migration_replays_and_runtime_roles_are_least_privilege() -> None:
    _authority_instance, database, settings = _authority()
    db.run_migrations(
        database,
        only=("014_agent_v02_connector_liveness.sql",),
    )
    with database.connect() as conn:
        assert connector_liveness_schema_is_ready_on_connection(conn) is True
        version = conn.execute(
            """
            SELECT schema_version
            FROM quant_system.agent_v02_connector_liveness_meta
            WHERE singleton IS TRUE
            """
        ).fetchone()
        assert version == (CONNECTOR_LIVENESS_SCHEMA_VERSION,)

    admin_url = settings.database.url
    assert admin_url is not None
    plain_admin_url = (
        admin_url.get_secret_value() if hasattr(admin_url, "get_secret_value") else str(admin_url)
    )
    with psycopg.connect(
        _url_as(plain_admin_url, user=RUNTIME_LOGIN),
        autocommit=True,
    ) as runtime:
        assert connector_liveness_runtime_security_is_ready_on_connection(runtime)
        assert runtime.execute(
            """
            SELECT
                has_table_privilege(
                    session_user,
                    'quant_system.agent_v02_connector_workers',
                    'SELECT,INSERT,UPDATE'
                ),
                NOT has_table_privilege(
                    session_user,
                    'quant_system.agent_v02_connector_workers',
                    'DELETE,TRUNCATE'
                )
            """
        ).fetchone() == (True, True)
    with psycopg.connect(
        _url_as(plain_admin_url, user=READONLY_LOGIN),
        autocommit=True,
    ) as readonly:
        assert readonly.execute(
            """
            SELECT
                has_table_privilege(
                    session_user,
                    'quant_system.agent_v02_connector_workers',
                    'SELECT'
                ),
                NOT has_table_privilege(
                    session_user,
                    'quant_system.agent_v02_connector_workers',
                    'INSERT,UPDATE,DELETE,TRUNCATE'
                )
            """
        ).fetchone() == (True, True)


def test_full_migration_chain_replays_with_connector_liveness_ready() -> None:
    settings = _settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    db.run_migrations(database)
    db.run_migrations(database)

    with database.connect() as conn:
        assert connector_liveness_schema_is_ready_on_connection(conn) is True


def test_session_lock_is_single_active_and_probe_tracks_heartbeat_and_stop() -> None:
    authority, _database, _settings_instance = _authority()
    lease = authority.acquire(
        workspace_id=WORKSPACE,
        worker_id="worker-primary",
        mode="supervised_dispatch",
        runtime_digest=PLATFORM_DIGEST,
        now=NOW,
    )
    try:
        assert (
            authority.probe(
                workspace_id=WORKSPACE,
                expected_runtime_digest=PLATFORM_DIGEST,
                now=NOW + timedelta(seconds=1),
                max_heartbeat_age_seconds=30,
            ).ready
            is True
        )

        with pytest.raises(ConnectorLivenessConflict):
            authority.acquire(
                workspace_id=WORKSPACE,
                worker_id="worker-contender",
                mode="supervised_dispatch",
                runtime_digest=PLATFORM_DIGEST,
                now=NOW + timedelta(seconds=2),
            )

        heartbeat = lease.heartbeat(now=NOW + timedelta(seconds=20))
        assert heartbeat.generation_token == lease.generation_token
        assert heartbeat.heartbeat_at == NOW + timedelta(seconds=20)
        assert (
            authority.probe(
                workspace_id=WORKSPACE,
                expected_runtime_digest=PLATFORM_DIGEST,
                now=NOW + timedelta(seconds=45),
                max_heartbeat_age_seconds=30,
            ).ready
            is True
        )
    finally:
        lease.stop(now=NOW + timedelta(seconds=46), reason="test_complete")

    probe = authority.probe(
        workspace_id=WORKSPACE,
        expected_runtime_digest=PLATFORM_DIGEST,
        now=NOW + timedelta(seconds=47),
        max_heartbeat_age_seconds=30,
    )
    assert probe.ready is False
    assert probe.reason == "connector_not_active"


def test_restart_replaces_abandoned_generation_and_old_generation_cannot_heartbeat() -> None:
    authority, _database, _settings_instance = _authority()
    abandoned = authority.acquire(
        workspace_id=WORKSPACE,
        worker_id="worker-before-crash",
        mode="supervised_dispatch",
        runtime_digest=PLATFORM_DIGEST,
        now=NOW,
    )
    old_generation = abandoned.generation_token
    abandoned._disconnect_without_receipt_for_test()
    dead_probe = authority.probe(
        workspace_id=WORKSPACE,
        expected_runtime_digest=PLATFORM_DIGEST,
        now=NOW + timedelta(seconds=1),
        max_heartbeat_age_seconds=30,
    )
    assert dead_probe.ready is False
    assert dead_probe.reason == "connector_session_lock_missing"

    with authority.acquire(
        workspace_id=WORKSPACE,
        worker_id="worker-after-restart",
        mode="supervised_dispatch",
        runtime_digest=PLATFORM_DIGEST,
        now=NOW,
    ) as replacement:
        assert replacement.generation_token != old_generation
        with pytest.raises(ConnectorLivenessLeaseLost):
            authority._heartbeat_generation(
                workspace_id=WORKSPACE,
                worker_id="worker-before-crash",
                generation_token=old_generation,
                now=NOW + timedelta(seconds=1),
            )
        assert (
            authority.probe(
                workspace_id=WORKSPACE,
                expected_runtime_digest=PLATFORM_DIGEST,
                now=NOW + timedelta(seconds=1),
                max_heartbeat_age_seconds=30,
            ).ready
            is True
        )

    with authority._database().connect() as conn:
        rows = conn.execute(
            """
            SELECT generation_token::text, status, stopped_at IS NOT NULL
            FROM quant_system.agent_v02_connector_workers
            ORDER BY started_at, generation_token
            """
        ).fetchall()
    by_generation = {str(row[0]): (str(row[1]), bool(row[2])) for row in rows}
    assert by_generation[old_generation] == ("stale", True)
    assert by_generation[replacement.generation_token] == ("stopped", True)
