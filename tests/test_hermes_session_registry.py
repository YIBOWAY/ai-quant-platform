from __future__ import annotations

import os
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.session_registry import (
    HermesSessionNotWritable,
    HermesSessionRegistryConflict,
    HermesSessionRegistryValidationError,
    RegisterWorkspaceSession,
    get_workspace_session,
    register_workspace_session,
    require_web_writable_session,
    session_registry_schema_version,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


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


def _reset_sessions(database: db.Database) -> None:
    with database.connect() as conn, conn.transaction():
        conn.execute(
            "ALTER TABLE quant_system.hermes_workspace_sessions DISABLE TRIGGER USER"
        )
        conn.execute("TRUNCATE TABLE quant_system.hermes_workspace_sessions")
        conn.execute(
            "ALTER TABLE quant_system.hermes_workspace_sessions "
            "ENABLE ALWAYS TRIGGER trg_hermes_workspace_session_immutability"
        )


def test_session_registry_migration_is_ready_and_repeatable() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    assert session_registry_schema_version(settings) == 1
    db.run_migrations(database)
    assert session_registry_schema_version(settings) == 1


def test_register_external_and_managed_sessions_with_idempotency_and_fork() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)

    try:
        external, created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="ext-session-001",
                hermes_session_id="20260720_ext_001",
                workspace_id="workspace-root",
                kind="observed_external_session",
                source_channel="discord",
            ),
        )
        assert created is True
        assert external.web_writable is False
        again, created_again = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="ext-session-001",
                hermes_session_id="20260720_ext_001",
                workspace_id="workspace-root",
                kind="observed_external_session",
                source_channel="discord",
            ),
        )
        assert created_again is False
        assert again.platform_session_id == external.platform_session_id

        managed, managed_created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="web-session-001",
                hermes_session_id="20260720_web_001",
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=DIGEST_A,
            ),
        )
        assert managed_created is True
        assert managed.web_writable is True

        forked, fork_created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="web-session-fork-001",
                hermes_session_id="20260720_web_fork_001",
                workspace_id="workspace-root",
                kind="web_managed_session",
                source_channel="discord",
                parent_platform_session_id="ext-session-001",
                fork_point="msg:discord:abc123",
                provider_policy_digest=DIGEST_B,
            ),
        )
        assert fork_created is True
        assert forked.parent_platform_session_id == "ext-session-001"
        assert require_web_writable_session(
            settings, platform_session_id="web-session-001"
        ).platform_session_id == "web-session-001"
    finally:
        _reset_sessions(database)
        db.reset_database_cache()


def test_external_session_rejects_web_write_gate_and_db_mutation() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)

    try:
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="ext-session-ro",
                hermes_session_id="20260720_ext_ro",
                workspace_id="workspace-root",
                kind="observed_external_session",
                source_channel="historical",
            ),
        )
        with pytest.raises(HermesSessionNotWritable):
            require_web_writable_session(settings, platform_session_id="ext-session-ro")

        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_workspace_sessions
                SET source_channel = 'discord'
                WHERE platform_session_id = %s
                """,
                ("ext-session-ro",),
            )
        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                """
                DELETE FROM quant_system.hermes_workspace_sessions
                WHERE platform_session_id = %s
                """,
                ("ext-session-ro",),
            )
    finally:
        _reset_sessions(database)
        db.reset_database_cache()


def test_conflicting_identity_and_invalid_shapes_fail_closed() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_sessions(database)

    try:
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="web-session-conflict",
                hermes_session_id="20260720_web_conflict",
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=DIGEST_A,
            ),
        )
        with pytest.raises(HermesSessionRegistryConflict):
            register_workspace_session(
                settings,
                RegisterWorkspaceSession(
                    platform_session_id="web-session-conflict",
                    hermes_session_id="20260720_web_conflict",
                    workspace_id="workspace-root",
                    kind="web_managed_session",
                    provider_policy_digest=DIGEST_B,
                ),
            )
        with pytest.raises(HermesSessionRegistryConflict):
            register_workspace_session(
                settings,
                RegisterWorkspaceSession(
                    platform_session_id="web-session-other",
                    hermes_session_id="20260720_web_conflict",
                    workspace_id="workspace-root",
                    kind="web_managed_session",
                    provider_policy_digest=DIGEST_A,
                ),
            )
        with pytest.raises(HermesSessionRegistryValidationError):
            register_workspace_session(
                settings,
                RegisterWorkspaceSession(
                    platform_session_id="bad-external",
                    hermes_session_id="20260720_bad_ext",
                    workspace_id="workspace-root",
                    kind="observed_external_session",
                    provider_policy_digest=DIGEST_A,
                ),
            )
        with pytest.raises(HermesSessionRegistryValidationError):
            register_workspace_session(
                settings,
                RegisterWorkspaceSession(
                    platform_session_id="bad-managed",
                    hermes_session_id="20260720_bad_managed",
                    workspace_id="workspace-root",
                    kind="web_managed_session",
                ),
            )
        # still only the first durable row
        record = get_workspace_session(
            settings, platform_session_id="web-session-conflict"
        )
        assert record.provider_policy_digest == DIGEST_A
        with database.connect() as conn:
            assert conn.execute(
                "SELECT count(*) FROM quant_system.hermes_workspace_sessions"
            ).fetchone() == (1,)
    finally:
        _reset_sessions(database)
        db.reset_database_cache()
