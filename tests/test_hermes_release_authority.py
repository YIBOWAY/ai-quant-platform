from __future__ import annotations

import inspect
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.release_authority import (
    ClosePublicCutoverRequest,
    CloseReleaseStampRequest,
    CreatePublicCutoverRequest,
    CreateReleaseStampRequest,
    ReleaseAuthority,
    ReleaseAuthorityConflict,
    canonical_release_action_digest,
    release_authority_runtime_security_ready,
    release_authority_schema_is_ready_on_connection,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

NOW = datetime(2026, 7, 24, 10, 0, tzinfo=UTC)
PLATFORM = "1" * 64
HQA = "2" * 64
HERMES = "3" * 64
EVIDENCE = "4" * 64
RELEASE_MIGRATIONS = (
    "003_app_users_brief_ai_reports.sql",
    "012_agent_v0_2_release_authority.sql",
)
RUNTIME_LOGIN = "aqp_release_runtime_test"
RUNTIME_PASSWORD = "release-runtime-test-only"


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
            conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
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


def _url_as(url: str, *, user: str, password: str) -> str:
    params = conninfo_to_dict(url)
    params["user"] = user
    params["password"] = password
    return make_conninfo(**params)


def _reset(database: db.Database) -> None:
    with database.connect() as conn, conn.transaction():
        for table in (
            "agent_v02_release_actions",
            "agent_v02_release_events",
            "agent_v02_public_cutovers",
            "agent_v02_release_stamps",
        ):
            conn.execute(
                sql.SQL("ALTER TABLE quant_system.{} DISABLE TRIGGER USER").format(
                    sql.Identifier(table)
                )
            )
        conn.execute(
            """
            TRUNCATE TABLE
                quant_system.agent_v02_release_actions,
                quant_system.agent_v02_release_events,
                quant_system.agent_v02_public_cutovers,
                quant_system.agent_v02_release_stamps
            RESTART IDENTITY
            """
        )
        trigger_names = {
            "agent_v02_release_stamps": (
                "trg_agent_v02_release_stamps_update",
                "trg_agent_v02_release_stamps_delete",
                "trg_agent_v02_release_stamps_truncate",
            ),
            "agent_v02_public_cutovers": (
                "trg_agent_v02_cutovers_update",
                "trg_agent_v02_cutovers_delete",
                "trg_agent_v02_cutovers_truncate",
            ),
            "agent_v02_release_events": (
                "trg_agent_v02_release_events_update",
                "trg_agent_v02_release_events_delete",
                "trg_agent_v02_release_events_truncate",
            ),
            "agent_v02_release_actions": (
                "trg_agent_v02_release_actions_update",
                "trg_agent_v02_release_actions_delete",
                "trg_agent_v02_release_actions_truncate",
            ),
        }
        for table, names in trigger_names.items():
            for trigger_name in names:
                conn.execute(
                    sql.SQL("ALTER TABLE quant_system.{} ENABLE ALWAYS TRIGGER {}").format(
                        sql.Identifier(table),
                        sql.Identifier(trigger_name),
                    )
                )


def _recreate_test_database(settings: Settings) -> None:
    secret = settings.database.url
    assert secret is not None
    url = secret.get_secret_value() if hasattr(secret, "get_secret_value") else str(secret)
    parameters = conninfo_to_dict(url)
    database_name = parameters.get("dbname")
    assert database_name is not None
    maintenance = dict(parameters)
    maintenance["dbname"] = "postgres"
    db.reset_database_cache()
    with psycopg.connect(
        make_conninfo(**maintenance),
        autocommit=True,
    ) as conn:
        conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s
              AND pid <> pg_backend_pid()
            """,
            (database_name,),
        )
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))


def _authority() -> tuple[ReleaseAuthority, db.Database]:
    settings = _settings()
    _recreate_test_database(settings)
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database, only=RELEASE_MIGRATIONS)
    _reset(database)
    return ReleaseAuthority(settings), database


def test_legacy_release_authority_is_replay_safe_but_not_hardened_ready() -> None:
    settings = _settings()
    _recreate_test_database(settings)
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database, only=RELEASE_MIGRATIONS)
    db.run_migrations(
        database,
        only=("012_agent_v0_2_release_authority.sql",),
    )
    with database.connect() as conn:
        assert release_authority_schema_is_ready_on_connection(conn) is False
    db.reset_database_cache()


def test_release_authority_requires_the_constrained_runtime_role() -> None:
    admin_settings = _settings()
    _recreate_test_database(admin_settings)
    admin_url = admin_settings.database.url
    assert admin_url is not None
    plain_admin_url = (
        admin_url.get_secret_value() if hasattr(admin_url, "get_secret_value") else str(admin_url)
    )
    db.reset_database_cache()
    database = db.get_database(admin_settings)
    assert database is not None
    db.run_migrations(database, only=RELEASE_MIGRATIONS)
    with database.connect() as conn:
        for role_name in ("quant_migrator", "quant_runtime", "quant_readonly"):
            if (
                conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_name,)).fetchone()
                is None
            ):
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(sql.Identifier(role_name))
                )
        if (
            conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (RUNTIME_LOGIN,)).fetchone()
            is not None
        ):
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(RUNTIME_LOGIN)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(RUNTIME_LOGIN)))
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
                sql.Identifier(RUNTIME_LOGIN),
                sql.Literal(RUNTIME_PASSWORD),
            )
        )
        conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(RUNTIME_LOGIN)))

    # Replay after roles exist installs/repairs exact FORCE-RLS policy and grants.
    db.run_migrations(
        database,
        only=("012_agent_v0_2_release_authority.sql",),
    )
    assert release_authority_runtime_security_ready(admin_settings) is False
    runtime_settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url=_url_as(
                plain_admin_url,
                user=RUNTIME_LOGIN,
                password=RUNTIME_PASSWORD,
            ),
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )
    try:
        db.reset_database_cache()
        assert release_authority_runtime_security_ready(runtime_settings) is False
    finally:
        db.reset_database_cache()
        database = db.Database(plain_admin_url, connect_timeout=1)
        with database.connect() as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(RUNTIME_LOGIN)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(RUNTIME_LOGIN)))
        db.reset_database_cache()


def _issue_request(
    action_id: str = "release-open-1",
    *,
    note: str = "operator verified G1-G8 locally",
) -> CreateReleaseStampRequest:
    payload = {
        "workspace_id": "workspace-root",
        "route": "/hermes",
        "platform_runtime_digest": PLATFORM,
        "hqa_runtime_digest": HQA,
        "hermes_runtime_digest": HERMES,
        "evidence_digest": EVIDENCE,
        "note": note,
    }
    return CreateReleaseStampRequest(
        **payload,
        client_action_id=action_id,
        action_digest=canonical_release_action_digest("release.open", payload),
    )


def test_release_request_has_no_caller_supplied_build_digest() -> None:
    assert "build_digest" not in inspect.signature(CreateReleaseStampRequest).parameters
    assert "release_digest" not in inspect.signature(CreateReleaseStampRequest).parameters


def test_release_stamp_cutover_idempotency_and_restart_visibility() -> None:
    authority, database = _authority()
    try:
        stamp_receipt = authority.create_release_stamp(
            _issue_request(), now=NOW, stamp_id="stamp-1"
        )
        replay = ReleaseAuthority(_settings()).create_release_stamp(
            _issue_request(), now=NOW, stamp_id="ignored-on-replay"
        )
        assert replay == replace(stamp_receipt, idempotent_replay=True)
        assert replay.idempotent_replay is True

        stamp = authority.active_release_stamp("workspace-root")
        assert stamp is not None
        assert stamp.release_digest == stamp_receipt.resource_digest
        assert stamp.database_schema_fingerprint not in {
            "<db-disabled>",
            "<unavailable>",
        }

        cutover_payload = {
            "workspace_id": "workspace-root",
            "stamp_id": stamp.stamp_id,
            "expected_release_digest": stamp.release_digest,
            "route": "/hermes",
            "note": "public local cutover",
        }
        cutover_request = CreatePublicCutoverRequest(
            **cutover_payload,
            client_action_id="cutover-open-1",
            action_digest=canonical_release_action_digest("public_cutover.open", cutover_payload),
        )
        cutover_receipt = authority.create_public_cutover(
            cutover_request, now=NOW, cutover_id="cutover-1"
        )
        assert cutover_receipt.resource_id == "cutover-1"
        restarted = ReleaseAuthority(_settings())
        assert restarted.open_public_cutover("workspace-root") is not None
        assert restarted.current_event_cursor("workspace-root") == 2
        events = restarted.events_after("workspace-root", after_cursor=0)
        assert [event.event_type for event in events] == [
            "release.opened",
            "public_cutover.opened",
        ]
    finally:
        _reset(database)
        db.reset_database_cache()


def test_one_active_release_and_first_action_receipt_are_frozen() -> None:
    authority, database = _authority()
    try:
        first = authority.create_release_stamp(_issue_request(), now=NOW, stamp_id="stamp-1")
        with pytest.raises(ReleaseAuthorityConflict, match="action"):
            authority.create_release_stamp(
                _issue_request(
                    action_id="release-open-1",
                    note="a different but canonically valid operator action",
                ),
                now=NOW,
                stamp_id="stamp-2",
            )
        with pytest.raises(ReleaseAuthorityConflict, match="active"):
            authority.create_release_stamp(
                _issue_request(action_id="release-open-2"),
                now=NOW,
                stamp_id="stamp-2",
            )
        with database.connect() as conn:
            stored = conn.execute(
                """
                SELECT receipt
                FROM quant_system.agent_v02_release_actions
                WHERE workspace_id = %s AND client_action_id = %s
                """,
                ("workspace-root", "release-open-1"),
            ).fetchone()
        assert stored is not None
        assert stored[0]["resource_id"] == first.resource_id
        assert stored[0]["resource_digest"] == first.resource_digest
    finally:
        _reset(database)
        db.reset_database_cache()


def test_two_authority_instances_cannot_open_two_active_releases() -> None:
    authority, database = _authority()
    second = ReleaseAuthority(_settings())

    def issue(
        item: tuple[ReleaseAuthority, str, str],
    ) -> tuple[str, str]:
        instance, action_id, stamp_id = item
        try:
            receipt = instance.create_release_stamp(
                _issue_request(action_id=action_id),
                now=NOW,
                stamp_id=stamp_id,
            )
        except ReleaseAuthorityConflict as exc:
            return ("conflict", exc.code)
        return ("created", receipt.resource_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    issue,
                    (
                        (authority, "concurrent-release-a", "stamp-a"),
                        (second, "concurrent-release-b", "stamp-b"),
                    ),
                )
            )
        assert sorted(item[0] for item in outcomes) == ["conflict", "created"]
        assert authority.active_release_stamp("workspace-root") is not None
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT count(*)
                FROM quant_system.agent_v02_release_stamps
                WHERE workspace_id = %s AND status = 'active'
                """,
                ("workspace-root",),
            ).fetchone() == (1,)
    finally:
        _reset(database)
        db.reset_database_cache()


def test_rollback_remains_callable_and_facts_are_append_only() -> None:
    authority, database = _authority()
    try:
        authority.create_release_stamp(_issue_request(), now=NOW, stamp_id="stamp-1")
        stamp = authority.active_release_stamp("workspace-root")
        assert stamp is not None
        cutover_payload = {
            "workspace_id": "workspace-root",
            "stamp_id": stamp.stamp_id,
            "expected_release_digest": stamp.release_digest,
            "route": "/hermes",
            "note": "open",
        }
        authority.create_public_cutover(
            CreatePublicCutoverRequest(
                **cutover_payload,
                client_action_id="cutover-open-1",
                action_digest=canonical_release_action_digest(
                    "public_cutover.open", cutover_payload
                ),
            ),
            now=NOW,
            cutover_id="cutover-1",
        )
        cutover = authority.open_public_cutover("workspace-root")
        assert cutover is not None
        close_cutover_payload = {
            "workspace_id": "workspace-root",
            "cutover_id": cutover.cutover_id,
            "expected_cutover_digest": cutover.cutover_digest,
            "reason": "operator rollback",
        }
        authority.close_public_cutover(
            ClosePublicCutoverRequest(
                **close_cutover_payload,
                client_action_id="cutover-close-1",
                action_digest=canonical_release_action_digest(
                    "public_cutover.close", close_cutover_payload
                ),
            ),
            now=NOW,
        )
        close_release_payload = {
            "workspace_id": "workspace-root",
            "stamp_id": stamp.stamp_id,
            "expected_release_digest": stamp.release_digest,
            "reason": "operator rollback complete",
        }
        authority.close_release_stamp(
            CloseReleaseStampRequest(
                **close_release_payload,
                client_action_id="release-close-1",
                action_digest=canonical_release_action_digest(
                    "release.close", close_release_payload
                ),
            ),
            now=NOW,
        )
        assert authority.active_release_stamp("workspace-root") is None
        assert authority.open_public_cutover("workspace-root") is None
        assert authority.current_event_cursor("workspace-root") == 4

        with (
            pytest.raises(psycopg.errors.RaiseException, match="append-only"),
            database.connect() as conn,
        ):
            conn.execute(
                "DELETE FROM quant_system.agent_v02_release_events WHERE workspace_id = %s",
                ("workspace-root",),
            )
    finally:
        _reset(database)
        db.reset_database_cache()
