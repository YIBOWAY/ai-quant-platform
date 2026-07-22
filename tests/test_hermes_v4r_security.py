"""V4-R least-privilege/RLS tests against an explicit throwaway PostgreSQL."""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.dark_identity_profile import PROVIDER_POLICY_DIGEST
from quant_system.hermes.session_registry import (
    HERMES_RUNTIME_ROLE,
    hermes_runtime_security_ready,
    session_registry_schema_is_ready_on_connection,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

MIGRATOR_ROLE = "quant_migrator"
READONLY_ROLE = "quant_readonly"
RUNTIME_LOGIN = "aqp_v4r_runtime_test"
RUNTIME_PASSWORD = "v4r-runtime-test-only"
READONLY_LOGIN = "aqp_v4r_readonly_test"
READONLY_PASSWORD = "v4r-readonly-test-only"
MIGRATOR_LOGIN = "aqp_v4r_migrator_test"
MIGRATOR_PASSWORD = "v4r-migrator-test-only"


def _test_url() -> str:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    dbname = conninfo_to_dict(url).get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            "QS_TEST_DATABASE_URL must point at a throwaway test database "
            f"(got {dbname!r})"
        )
    return url


def _settings(url: str) -> Settings:
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )


def _url_as(url: str, *, user: str, password: str) -> str:
    params = conninfo_to_dict(url)
    params["user"] = user
    params["password"] = password
    return make_conninfo(**params)


def _url_as_group_role(
    url: str, *, user: str, password: str, group: str
) -> str:
    params = conninfo_to_dict(_url_as(url, user=user, password=password))
    params["options"] = f"-c role={group}"
    return make_conninfo(**params)


def _drop_test_login(
    conn: psycopg.Connection, login: str = RUNTIME_LOGIN
) -> None:
    if conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)
    ).fetchone() is None:
        return
    conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(login)))
    conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))


def _provision_test_login(
    conn: psycopg.Connection, *, login: str, password: str, group: str
) -> None:
    _drop_test_login(conn, login)
    conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}"
        ).format(sql.Identifier(login), sql.Literal(password))
    )
    conn.execute(
        sql.SQL("GRANT {} TO {}").format(
            sql.Identifier(group), sql.Identifier(login)
        )
    )


def test_v4r_migration_provisions_roles_rls_and_safe_runtime_probe() -> None:
    admin_url = _test_url()
    admin_settings = _settings(admin_url)
    db.reset_database_cache()
    database = db.get_database(admin_settings)
    assert database is not None
    db.run_migrations(database)
    db.run_migrations(database)

    try:
        with database.connect() as conn:
            roles = {
                row[0]: (row[1], row[2], row[3])
                for row in conn.execute(
                    """
                    SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
                    FROM pg_roles
                    WHERE rolname = ANY(%s)
                    """,
                    ([MIGRATOR_ROLE, HERMES_RUNTIME_ROLE, READONLY_ROLE],),
                ).fetchall()
            }
            assert set(roles) == {MIGRATOR_ROLE, HERMES_RUNTIME_ROLE, READONLY_ROLE}
            assert all(value == (False, False, False) for value in roles.values())

            ttl = conn.execute(
                """
                SELECT data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'quant_system'
                  AND table_name = 'hermes_workspace_sessions'
                  AND column_name = 'payload_ttl_days'
                """
            ).fetchone()
            assert ttl == ("smallint", "YES", None)

            rls_tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT relname
                    FROM pg_class
                    JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace
                    WHERE nspname = 'quant_system'
                      AND relname = ANY(%s)
                      AND relrowsecurity
                      AND relforcerowsecurity
                    """,
                    (
                        [
                            "app_users",
                            "hermes_commands",
                            "hermes_command_events",
                            "hermes_outbox",
                            "hermes_run_links",
                            "hermes_command_workflow_bindings",
                            "hermes_workspace_sessions",
                        ],
                    ),
                ).fetchall()
            }
            assert len(rls_tables) == 7

            _provision_test_login(
                conn,
                login=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
                group=HERMES_RUNTIME_ROLE,
            )

        assert hermes_runtime_security_ready(admin_settings) is False
        runtime_settings = _settings(
            _url_as(
                admin_url,
                user=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
            )
        )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(runtime_settings) is True

        # The runtime must execute as its dedicated LOGIN. A connection-level
        # SET ROLE would make current_user diverge from the attested principal.
        switched_settings = _settings(
            _url_as_group_role(
                admin_url,
                user=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
                group=HERMES_RUNTIME_ROLE,
            )
        )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(switched_settings) is False
    finally:
        db.reset_database_cache()
        database = db.Database(admin_url, connect_timeout=1)
        with database.connect() as conn:
            _drop_test_login(conn)
        db.reset_database_cache()


def test_v4r_migration_repairs_drifted_group_role_attributes() -> None:
    database = db.Database(_test_url(), connect_timeout=1)
    db.run_migrations(database)
    try:
        with database.connect() as conn:
            conn.execute("ALTER ROLE quant_runtime LOGIN BYPASSRLS")
            assert conn.execute(
                """
                SELECT rolcanlogin, rolbypassrls
                FROM pg_roles
                WHERE rolname = 'quant_runtime'
                """
            ).fetchone() == (True, True)

        db.run_migrations(database)
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT rolcanlogin, rolsuper, rolbypassrls,
                       rolcreatedb, rolcreaterole, rolinherit, rolreplication
                FROM pg_roles
                WHERE rolname = 'quant_runtime'
                """
            ).fetchone() == (False, False, False, False, False, False, False)
    finally:
        db.run_migrations(database)


def test_runtime_and_readonly_roles_are_root_scoped_and_cannot_escalate() -> None:
    admin_url = _test_url()
    database = db.Database(admin_url, connect_timeout=1)
    db.run_migrations(database)
    root_command_id = str(uuid.uuid4())
    other_command_id = str(uuid.uuid4())
    runtime_command_id = str(uuid.uuid4())
    denied_runtime_command_id = str(uuid.uuid4())
    other_owner = "10000000-0000-0000-0000-000000000001"

    try:
        with database.connect() as conn:
            _provision_test_login(
                conn,
                login=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
                group=HERMES_RUNTIME_ROLE,
            )
            _provision_test_login(
                conn,
                login=READONLY_LOGIN,
                password=READONLY_PASSWORD,
                group=READONLY_ROLE,
            )
            conn.execute(
                """
                INSERT INTO quant_system.app_users (id, username)
                VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (other_owner, "v4r-other-owner"),
            )
            for command_id, owner, marker in (
                (root_command_id, "00000000-0000-0000-0000-000000000001", "root"),
                (other_command_id, other_owner, "other"),
            ):
                conn.execute(
                    """
                    INSERT INTO quant_system.hermes_commands (
                        command_id, owner_user_id, platform_session_id,
                        client_request_id, kind, canonical_request_digest,
                        payload_ref
                    ) VALUES (%s, %s, %s, %s, 'conversation_turn', %s, %s)
                    """,
                    (
                        command_id,
                        owner,
                        f"v4r-{marker}-session",
                        f"v4r-{marker}-request",
                        "a" * 64,
                        f"platform-payload://sha256/{'b' * 64}",
                    ),
                )

        runtime_url = _url_as(
            admin_url, user=RUNTIME_LOGIN, password=RUNTIME_PASSWORD
        )
        with psycopg.connect(runtime_url, autocommit=True) as conn:
            visible = {
                str(row[0])
                for row in conn.execute(
                    "SELECT command_id FROM quant_system.hermes_commands"
                ).fetchall()
            }
            assert root_command_id in visible
            assert other_command_id not in visible

            conn.execute(
                """
                INSERT INTO quant_system.hermes_commands (
                    command_id, owner_user_id, platform_session_id,
                    client_request_id, kind, canonical_request_digest,
                    payload_ref
                ) VALUES (%s, %s, 'v4r-runtime-session', 'v4r-runtime-request',
                          'conversation_turn', %s, %s)
                """,
                (
                    runtime_command_id,
                    "00000000-0000-0000-0000-000000000001",
                    "c" * 64,
                    f"platform-payload://sha256/{'d' * 64}",
                ),
            )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    """
                    INSERT INTO quant_system.hermes_commands (
                        command_id, owner_user_id, platform_session_id,
                        client_request_id, kind, canonical_request_digest,
                        payload_ref
                    ) VALUES (%s, %s, 'v4r-denied-session',
                              'v4r-denied-request', 'conversation_turn', %s, %s)
                    """,
                    (
                        denied_runtime_command_id,
                        other_owner,
                        "e" * 64,
                        f"platform-payload://sha256/{'f' * 64}",
                    ),
                )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    "DELETE FROM quant_system.hermes_commands WHERE command_id = %s",
                    (runtime_command_id,),
                )
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    "ALTER TABLE quant_system.hermes_commands DISABLE ROW LEVEL SECURITY"
                )

        readonly_url = _url_as(
            admin_url, user=READONLY_LOGIN, password=READONLY_PASSWORD
        )
        with psycopg.connect(readonly_url, autocommit=True) as conn:
            visible = {
                str(row[0])
                for row in conn.execute(
                    "SELECT command_id FROM quant_system.hermes_commands"
                ).fetchall()
            }
            assert root_command_id in visible
            assert runtime_command_id in visible
            assert other_command_id not in visible
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    "UPDATE quant_system.hermes_commands SET updated_at = now()"
                )
    finally:
        with database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.hermes_commands WHERE command_id = ANY(%s)",
                (
                    [
                        root_command_id,
                        other_command_id,
                        runtime_command_id,
                        denied_runtime_command_id,
                    ],
                ),
            )
            conn.execute(
                "DELETE FROM quant_system.app_users WHERE id = %s", (other_owner,)
            )
            _drop_test_login(conn, RUNTIME_LOGIN)
            _drop_test_login(conn, READONLY_LOGIN)


def test_session_registry_readiness_rejects_missing_ttl_contract() -> None:
    database = db.Database(_test_url(), connect_timeout=1)
    db.run_migrations(database)
    try:
        with database.connect() as conn:
            assert session_registry_schema_is_ready_on_connection(conn) is True
            conn.execute(
                """
                ALTER TABLE quant_system.hermes_workspace_sessions
                DROP CONSTRAINT ck_hermes_workspace_session_payload_ttl
                """
            )
            assert session_registry_schema_is_ready_on_connection(conn) is False
    finally:
        db.run_migrations(database)


def test_session_registry_readiness_rejects_browser_selectable_ttl_range() -> None:
    database = db.Database(_test_url(), connect_timeout=1)
    db.run_migrations(database)
    try:
        with database.connect() as conn:
            conn.execute(
                """
                ALTER TABLE quant_system.hermes_workspace_sessions
                DROP CONSTRAINT ck_hermes_workspace_session_payload_ttl
                """
            )
            conn.execute(
                """
                ALTER TABLE quant_system.hermes_workspace_sessions
                ADD CONSTRAINT ck_hermes_workspace_session_payload_ttl
                CHECK (
                    (kind = 'observed_external_session'
                        AND payload_ttl_days IS NULL)
                    OR
                    (kind = 'web_managed_session'
                        AND payload_ttl_days BETWEEN 1 AND 30)
                )
                """
            )
            assert session_registry_schema_is_ready_on_connection(conn) is False
    finally:
        db.run_migrations(database)


def test_session_registry_readiness_rejects_trigger_body_drift() -> None:
    database = db.Database(_test_url(), connect_timeout=1)
    db.run_migrations(database)
    try:
        with database.connect() as conn:
            assert session_registry_schema_is_ready_on_connection(conn) is True
            conn.execute(
                """
                CREATE OR REPLACE FUNCTION
                    quant_system.reject_hermes_external_session_mutation()
                RETURNS TRIGGER
                LANGUAGE plpgsql
                VOLATILE
                SECURITY INVOKER
                AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$
                """
            )
            assert session_registry_schema_is_ready_on_connection(conn) is False
    finally:
        db.run_migrations(database)


def test_managed_session_ttl_and_row_are_immutable_in_postgres() -> None:
    database = db.Database(_test_url(), connect_timeout=1)
    db.run_migrations(database)
    marker = uuid.uuid4().hex
    platform_session_id = f"v4r-session-{marker}"
    noncanonical_session_id = f"v4r-session-noncanonical-{marker}"
    external_session_id = f"v4r-external-{marker}"
    try:
        with database.connect() as conn:
            conn.execute(
                """
                INSERT INTO quant_system.hermes_workspace_sessions (
                    platform_session_id, hermes_session_id, workspace_id,
                    owner_user_id, kind, provider_policy_digest,
                    payload_ttl_days, writer
                ) VALUES (
                    %s, %s, 'ws-local-main',
                    '00000000-0000-0000-0000-000000000001',
                    'web_managed_session', %s, 7, 'web_control_plane'
                )
                """,
                (platform_session_id, f"hermes-{marker}", PROVIDER_POLICY_DIGEST),
            )

            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    """
                    INSERT INTO quant_system.hermes_workspace_sessions (
                        platform_session_id, hermes_session_id, workspace_id,
                        owner_user_id, kind, provider_policy_digest,
                        payload_ttl_days, writer
                    ) VALUES (
                        %s, %s, 'ws-local-main',
                        '00000000-0000-0000-0000-000000000001',
                        'web_managed_session', %s, 14, 'web_control_plane'
                    )
                    """,
                    (
                        noncanonical_session_id,
                        f"hermes-noncanonical-{marker}",
                        PROVIDER_POLICY_DIGEST,
                    ),
                )

            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                conn.execute(
                    """
                    UPDATE quant_system.hermes_workspace_sessions
                    SET payload_ttl_days = 30
                    WHERE platform_session_id = %s
                    """,
                    (platform_session_id,),
                )
            with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
                conn.execute(
                    """
                    DELETE FROM quant_system.hermes_workspace_sessions
                    WHERE platform_session_id = %s
                    """,
                    (platform_session_id,),
                )
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    """
                    INSERT INTO quant_system.hermes_workspace_sessions (
                        platform_session_id, hermes_session_id, workspace_id,
                        owner_user_id, kind, source_channel,
                        payload_ttl_days, writer
                    ) VALUES (
                        %s, %s, 'ws-local-main',
                        '00000000-0000-0000-0000-000000000001',
                        'observed_external_session', 'discord', 7,
                        'external_channel'
                    )
                    """,
                    (external_session_id, f"hermes-external-{marker}"),
                )
    finally:
        with database.connect() as conn:
            conn.execute(
                """
                ALTER TABLE quant_system.hermes_workspace_sessions
                DISABLE TRIGGER USER
                """
            )
            conn.execute(
                """
                DELETE FROM quant_system.hermes_workspace_sessions
                WHERE platform_session_id = ANY(%s)
                """,
                (
                    [
                        platform_session_id,
                        noncanonical_session_id,
                        external_session_id,
                    ],
                ),
            )
            conn.execute(
                """
                ALTER TABLE quant_system.hermes_workspace_sessions
                ENABLE ALWAYS TRIGGER trg_hermes_workspace_session_immutability
                """
            )


def test_runtime_probe_fails_closed_when_rls_signature_drifts() -> None:
    admin_url = _test_url()
    database = db.Database(admin_url, connect_timeout=1)
    db.run_migrations(database)
    runtime_settings = _settings(
        _url_as(admin_url, user=RUNTIME_LOGIN, password=RUNTIME_PASSWORD)
    )
    try:
        with database.connect() as conn:
            _provision_test_login(
                conn,
                login=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
                group=HERMES_RUNTIME_ROLE,
            )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(runtime_settings) is True

        with database.connect() as conn:
            conn.execute(
                "ALTER TABLE quant_system.hermes_commands DISABLE ROW LEVEL SECURITY"
            )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(runtime_settings) is False
    finally:
        db.run_migrations(database)
        with database.connect() as conn:
            _drop_test_login(conn, RUNTIME_LOGIN)
        db.reset_database_cache()


def test_runtime_probe_rejects_missing_required_table_privilege() -> None:
    admin_url = _test_url()
    database = db.Database(admin_url, connect_timeout=1)
    db.run_migrations(database)
    runtime_settings = _settings(
        _url_as(admin_url, user=RUNTIME_LOGIN, password=RUNTIME_PASSWORD)
    )
    try:
        with database.connect() as conn:
            _provision_test_login(
                conn,
                login=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
                group=HERMES_RUNTIME_ROLE,
            )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(runtime_settings) is True

        with database.connect() as conn:
            conn.execute(
                "REVOKE UPDATE ON quant_system.hermes_commands FROM quant_runtime"
            )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(runtime_settings) is False
    finally:
        db.run_migrations(database)
        with database.connect() as conn:
            _drop_test_login(conn, RUNTIME_LOGIN)
        db.reset_database_cache()


def test_non_superuser_migrator_can_replay_the_full_migration_set() -> None:
    admin_url = _test_url()
    admin_database = db.Database(admin_url, connect_timeout=1)
    db.run_migrations(admin_database)
    try:
        with admin_database.connect() as conn:
            _provision_test_login(
                conn,
                login=MIGRATOR_LOGIN,
                password=MIGRATOR_PASSWORD,
                group=MIGRATOR_ROLE,
            )

        migrator_url = _url_as_group_role(
            admin_url,
            user=MIGRATOR_LOGIN,
            password=MIGRATOR_PASSWORD,
            group=MIGRATOR_ROLE,
        )
        migrator_database = db.Database(migrator_url, connect_timeout=1)
        db.run_migrations(migrator_database)
        db.run_migrations(migrator_database)

        with migrator_database.connect() as conn:
            identity = conn.execute(
                "SELECT session_user, current_user"
            ).fetchone()
            assert identity == (MIGRATOR_LOGIN, MIGRATOR_ROLE)
            attrs = conn.execute(
                """
                SELECT rolsuper, rolbypassrls
                FROM pg_roles WHERE rolname = session_user
                """
            ).fetchone()
            assert attrs == (False, False)
    finally:
        with admin_database.connect() as conn:
            _drop_test_login(conn, MIGRATOR_LOGIN)


def test_runtime_probe_rejects_fail_open_policy_body_drift() -> None:
    admin_url = _test_url()
    database = db.Database(admin_url, connect_timeout=1)
    db.run_migrations(database)
    runtime_settings = _settings(
        _url_as(admin_url, user=RUNTIME_LOGIN, password=RUNTIME_PASSWORD)
    )
    try:
        with database.connect() as conn:
            _provision_test_login(
                conn,
                login=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
                group=HERMES_RUNTIME_ROLE,
            )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(runtime_settings) is True

        with database.connect() as conn:
            conn.execute(
                """
                ALTER POLICY v4r_root_scope
                ON quant_system.hermes_commands
                USING (TRUE)
                WITH CHECK (TRUE)
                """
            )
        db.reset_database_cache()
        assert hermes_runtime_security_ready(runtime_settings) is False
    finally:
        db.run_migrations(database)
        with database.connect() as conn:
            _drop_test_login(conn, RUNTIME_LOGIN)
        db.reset_database_cache()
