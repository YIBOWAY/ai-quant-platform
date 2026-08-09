from __future__ import annotations

import os
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace_actions import CreateManagedSession, WorkspaceRef
from quant_system.hermes.command_ledger import HermesCommandLedger
from quant_system.hermes.dark_identity_profile import PROVIDER_POLICY_DIGEST
from quant_system.hermes.session_registry import (
    HermesSessionActionConflict,
    HermesSessionNotWritable,
    HermesSessionRegistryConflict,
    HermesSessionRegistryUnavailable,
    HermesSessionRegistryValidationError,
    RegisterWorkspaceSession,
    get_workspace_session,
    register_workspace_session,
    require_web_writable_session,
    session_registry_schema_version,
)
from quant_system.hermes.submission_saga import submit_create_managed_session
from quant_system.storage import database as db
from tests.postgres_reset import truncate_with_fk_dependents

pytestmark = pytest.mark.pg

ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
DIGEST_B = "b" * 64
ACTION_DIGEST_A = "a" * 64
ACTION_DIGEST_C = "c" * 64


def test_managed_session_policy_is_server_owned_before_database_access() -> None:
    settings = Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))
    with pytest.raises(HermesSessionRegistryValidationError):
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="web-policy-rejected",
                hermes_session_id=f"web_{ACTION_DIGEST_A[:40]}",
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=DIGEST_B,
                payload_ttl_days=7,
                creation_client_action_id="policy-rejected",
                creation_action_digest=ACTION_DIGEST_A,
            ),
        )

    # Canonical server policy passes validation and reaches the DB boundary.
    with pytest.raises(HermesSessionRegistryUnavailable):
        register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="web-policy-canonical",
                hermes_session_id=f"web_{ACTION_DIGEST_A[:40]}",
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="policy-canonical",
                creation_action_digest=ACTION_DIGEST_A,
            ),
        )


def test_create_rejects_browser_policy_before_command_write() -> None:
    policy_action = CreateManagedSession(
        client_action_id="reject-browser-policy",
        workspace=WorkspaceRef(workspace_id="workspace-root"),
        provider_policy_digest=DIGEST_B,
        payload_ttl_days=7,
    )
    ttl_action = CreateManagedSession(
        client_action_id="reject-browser-ttl",
        workspace=WorkspaceRef(workspace_id="workspace-root"),
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
        payload_ttl_days=14,
    )
    with (
        patch("quant_system.hermes.submission_saga._ensure_ready", return_value=True),
        patch("quant_system.hermes.submission_saga._create_idempotent_command") as create,
    ):
        policy_receipt = submit_create_managed_session(
            Settings(database=DatabaseSettings(enabled=False, auto_migrate=False)),
            policy_action,
            mutation_enabled=True,
        )
        ttl_receipt = submit_create_managed_session(
            Settings(database=DatabaseSettings(enabled=False, auto_migrate=False)),
            ttl_action,
            mutation_enabled=True,
        )

    assert policy_receipt.status == "unavailable"
    assert policy_receipt.reason_code == "server_managed_session_policy_required"
    assert ttl_receipt.status == "unavailable"
    assert ttl_receipt.reason_code == "server_managed_session_policy_required"
    create.assert_not_called()


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
    truncate_with_fk_dependents(
        database,
        ("quant_system.hermes_workspace_sessions",),
        restart_identity=False,
    )


def test_session_registry_migration_is_ready_and_repeatable() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    assert session_registry_schema_version(settings) == 3
    db.run_migrations(database)
    assert session_registry_schema_version(settings) == 3


def test_session_registry_migration_rejects_unknown_future_version() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    try:
        with database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_session_registry_meta
                SET schema_version = 4
                WHERE singleton IS TRUE
                """
            )
        with pytest.raises(psycopg.errors.RaiseException, match="newer"):
            db.run_migrations(
                database,
                only={"007_hermes_session_registry.sql"},
            )
    finally:
        with database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_session_registry_meta
                SET schema_version = 3
                WHERE singleton IS TRUE
                """
            )
        db.reset_database_cache()


def test_migration_retires_only_legacy_queued_session_control_commands() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    ledger = HermesCommandLedger(settings)
    created = ledger.create_command(
        platform_session_id="awctl_workspace-root",
        client_request_id=f"legacy-session-control-{uuid4().hex}",
        kind="managed_session_create",
        canonical_request_digest=ACTION_DIGEST_A,
        payload_ref=f"platform-payload://sha256/{ACTION_DIGEST_A}",
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
    ).command
    assert created.state == "queued"

    db.run_migrations(database, only={"011_hermes_session_action_idempotency.sql"})
    retired = ledger.get_command(created.command_id)
    assert retired.state == "cancelled"
    assert retired.last_error_code == "legacy_control_command_retired"
    with database.connect() as conn:
        events = conn.execute(
            """
            SELECT event_type, from_state, to_state
            FROM quant_system.hermes_command_events
            WHERE command_id = %s
            ORDER BY command_version
            """,
            (created.command_id,),
        ).fetchall()
        assert events == [
            ("command_created", None, "queued"),
            ("legacy_control_retired", "queued", "cancelled"),
        ]
        assert conn.execute(
            """
            SELECT consumed_by IS NOT NULL, consumed_at IS NOT NULL
            FROM quant_system.hermes_outbox
            WHERE command_id = %s
            """,
            (created.command_id,),
        ).fetchone() == (True, True)

    # Replay is a no-op for the already terminal row and emits no duplicate.
    db.run_migrations(database, only={"011_hermes_session_action_idempotency.sql"})
    with database.connect() as conn:
        assert conn.execute(
            """
            SELECT count(*)
            FROM quant_system.hermes_command_events
            WHERE command_id = %s
            """,
            (created.command_id,),
        ).fetchone() == (2,)
    db.run_migrations(database)
    assert session_registry_schema_version(settings) == 3


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
                hermes_session_id=f"web_{ACTION_DIGEST_A[:40]}",
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="registry-managed-root",
                creation_action_digest=ACTION_DIGEST_A,
            ),
        )
        assert managed_created is True
        assert managed.provisioning_state == "pending"
        assert managed.web_writable is False

        forked, fork_created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id="web-session-fork-001",
                hermes_session_id=f"web_{ACTION_DIGEST_C[:40]}",
                workspace_id="workspace-root",
                kind="web_managed_session",
                source_channel="discord",
                parent_platform_session_id="ext-session-001",
                fork_point="message:123",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="registry-managed-fork",
                creation_action_digest=ACTION_DIGEST_C,
            ),
        )
        assert fork_created is True
        assert forked.parent_platform_session_id == "ext-session-001"
        with pytest.raises(HermesSessionNotWritable):
            require_web_writable_session(settings, platform_session_id="web-session-001")
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
                hermes_session_id=f"web_{ACTION_DIGEST_A[:40]}",
                workspace_id="workspace-root",
                kind="web_managed_session",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
                payload_ttl_days=7,
                creation_client_action_id="registry-conflict",
                creation_action_digest=ACTION_DIGEST_A,
            ),
        )
        with pytest.raises(HermesSessionActionConflict):
            register_workspace_session(
                settings,
                RegisterWorkspaceSession(
                    platform_session_id="web-session-conflict",
                    hermes_session_id=f"web_{ACTION_DIGEST_C[:40]}",
                    workspace_id="workspace-root",
                    kind="web_managed_session",
                    provider_policy_digest=PROVIDER_POLICY_DIGEST,
                    payload_ttl_days=7,
                    creation_client_action_id="registry-conflict",
                    creation_action_digest=ACTION_DIGEST_C,
                ),
            )
        with pytest.raises(HermesSessionRegistryConflict):
            register_workspace_session(
                settings,
                RegisterWorkspaceSession(
                    platform_session_id="web-session-other",
                    hermes_session_id=f"web_{ACTION_DIGEST_A[:40]}",
                    workspace_id="workspace-root",
                    kind="web_managed_session",
                    provider_policy_digest=PROVIDER_POLICY_DIGEST,
                    payload_ttl_days=7,
                    creation_client_action_id="registry-other",
                    creation_action_digest=ACTION_DIGEST_A,
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
                    provider_policy_digest=DIGEST_B,
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
        record = get_workspace_session(settings, platform_session_id="web-session-conflict")
        assert record.provider_policy_digest == PROVIDER_POLICY_DIGEST
        assert record.payload_ttl_days == 7
        assert record.creation_client_action_id == "registry-conflict"
        assert record.creation_action_digest == ACTION_DIGEST_A
        with pytest.raises(psycopg.errors.RaiseException), database.connect() as conn:
            conn.execute(
                """
                UPDATE quant_system.hermes_workspace_sessions
                SET creation_action_digest = %s
                WHERE platform_session_id = %s
                """,
                (ACTION_DIGEST_C, "web-session-conflict"),
            )
        with database.connect() as conn:
            assert conn.execute(
                "SELECT count(*) FROM quant_system.hermes_workspace_sessions"
            ).fetchone() == (1,)
    finally:
        _reset_sessions(database)
        db.reset_database_cache()
