"""V1.2A adversarial append-only hardening tests (isolated PostgreSQL only).

These tests prove the migration-005 append-only triggers on
``hermes_command_events`` / ``hermes_run_links`` are pinned ``ENABLE ALWAYS``
and therefore enforce the append-only guarantee against a role that *has* DML
privileges. They never touch a live database: they run against the throwaway
``QS_TEST_DATABASE_URL`` database only.

The point of the adversarial role is specifically to prove the *trigger* (not
the GRANT) rejects mutation: the role is granted SELECT/INSERT/UPDATE/DELETE,
yet UPDATE/DELETE/TRUNCATE still fail with the trigger's append-only error, and
the role cannot escalate (disable triggers, ALTER TABLE, or set
session_replication_role).

Scope note: migration 009 now adds FORCE RLS in source. The adversarial LOGIN is
therefore made a member of the NOLOGIN ``quant_runtime`` policy role while still
receiving explicit DML grants. This lets the test reach the exact root-owned row
and prove that the append-only trigger, rather than RLS invisibility or a missing
privilege, rejects mutation. No live schema or role is changed.
"""

from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.command_ledger import (
    LEDGER_SCHEMA_VERSION,
    command_ledger_schema_version,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

ADVERSARY_ROLE = "hermes_adv_v1"
ROOT_USER_ID = "00000000-0000-0000-0000-000000000001"


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


def _test_url() -> str:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    _ensure_test_database(url)
    return url


def _postgres_settings() -> Settings:
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=_test_url(),
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )


def _url_as(url: str, user: str, password: str) -> str:
    params = conninfo_to_dict(url)
    params["user"] = user
    params["password"] = password
    return make_conninfo(**params)


def _plain_url(settings: Settings) -> str:
    url = settings.database.url
    return url.get_secret_value() if hasattr(url, "get_secret_value") else str(url)


def _apply_schema(settings: Settings) -> db.Database:
    """Apply all migrations (incl. the V1.2A ENABLE ALWAYS pinning) to the
    isolated throwaway DB and return the connected Database helper."""
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    return database


def _drop_adversary(database: db.Database) -> None:
    """Idempotently remove the adversarial role and all its privileges/objects."""
    with database.connect() as conn, conn.transaction():
        exists = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s",
            (ADVERSARY_ROLE,),
        ).fetchone()
        if exists is None:
            return
        # DROP OWNED revokes every privilege/object the role holds in this DB,
        # so DROP ROLE cannot fail on leftover GRANTs.
        conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(ADVERSARY_ROLE)))
        conn.execute(
            sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(ADVERSARY_ROLE))
        )


def _provision_adversary(database: db.Database) -> None:
    """Create the adversarial role with full DML on the append-only tables.

    The role is NOSUPERUSER and gets SELECT/INSERT/UPDATE/DELETE plus
    TRUNCATE-ish ability via table privileges, so a successful mutation cannot
    be attributed to a missing GRANT — only to the trigger.
    """
    _drop_adversary(database)
    with database.connect() as conn, conn.transaction():
        conn.execute(
            sql.SQL("CREATE ROLE {} NOSUPERUSER INHERIT LOGIN PASSWORD {}").format(
                sql.Identifier(ADVERSARY_ROLE),
                sql.Literal("adv-pass"),
            )
        )
        conn.execute(
            sql.SQL("GRANT quant_runtime TO {}").format(
                sql.Identifier(ADVERSARY_ROLE)
            )
        )
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA quant_system TO {}").format(
                sql.Identifier(ADVERSARY_ROLE)
            )
        )
        conn.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON "
                "quant_system.hermes_command_events, "
                "quant_system.hermes_run_links, "
                "quant_system.hermes_commands "
                "TO {}"
            ).format(sql.Identifier(ADVERSARY_ROLE))
        )
        conn.execute(
            sql.SQL(
                "GRANT SELECT ON quant_system.app_users TO {}"
            ).format(sql.Identifier(ADVERSARY_ROLE))
        )


def _seed_run_link(database: db.Database) -> str:
    """Seed app_users -> hermes_commands -> hermes_run_links; return link_id."""
    command_id = str(uuid.uuid4())
    link_id = str(uuid.uuid4())
    # Unique per seed so repeated runs/tests never collide on the
    # (owner_user_id, platform_session_id, client_request_id) constraint.
    marker = uuid.uuid4().hex[:12]
    digest = "a" * 64
    with database.connect() as conn, conn.transaction():
        conn.execute(
            """
            INSERT INTO quant_system.hermes_commands (
                command_id, owner_user_id, platform_session_id, client_request_id,
                kind, canonical_request_digest, payload_ref
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                command_id,
                ROOT_USER_ID,
                f"adv-session-{marker}",
                f"adv-req-{marker}",
                "chat_turn",
                digest,
                "payload-ref-1",
            ),
        )
        conn.execute(
            """
            INSERT INTO quant_system.hermes_run_links (
                link_id, command_id, platform_resource_type, platform_resource_id,
                relation, hermes_session_id, hermes_run_id, link_digest, observed_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                link_id,
                command_id,
                "research_task",
                f"resource-{marker}",
                "output",
                f"hermes-session-{marker}",
                f"hermes-run-{marker}",
                digest,
            ),
        )
    return link_id


@pytest.fixture()
def hardened_db():
    settings = _postgres_settings()
    db.reset_database_cache()
    database = _apply_schema(settings)
    try:
        yield settings, database
    finally:
        _drop_adversary(database)
        db.reset_database_cache()


def test_append_only_trigger_fires_even_with_dml_grants(hardened_db) -> None:
    """A role WITH DML privileges is still rejected by the append-only trigger."""
    settings, database = hardened_db
    _provision_adversary(database)
    link_id = _seed_run_link(database)

    adv_url = _url_as(_plain_url(settings), ADVERSARY_ROLE, "adv-pass")
    with psycopg.connect(adv_url, autocommit=True) as conn:
        # Sanity: the role CAN read (GRANT works), so rejection below is the
        # trigger, not a missing privilege. Rows accumulate across tests, so
        # assert the seeded row is present rather than an exact count.
        present = conn.execute(
            "SELECT count(*) FROM quant_system.hermes_run_links WHERE link_id = %s",
            (link_id,),
        ).fetchone()[0]
        assert present == 1

        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(
                "UPDATE quant_system.hermes_run_links SET relation='input' "
                "WHERE link_id = %s",
                (link_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(
                "DELETE FROM quant_system.hermes_run_links WHERE link_id = %s",
                (link_id,),
            )
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute("TRUNCATE TABLE quant_system.hermes_run_links")


def test_adversary_cannot_disable_trigger_or_alter_table(hardened_db) -> None:
    """A non-owner role cannot disable/enable triggers or ALTER the table."""
    settings, database = hardened_db
    _provision_adversary(database)

    adv_url = _url_as(_plain_url(settings), ADVERSARY_ROLE, "adv-pass")
    with psycopg.connect(adv_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "ALTER TABLE quant_system.hermes_run_links DISABLE TRIGGER USER"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "ALTER TABLE quant_system.hermes_run_links "
                "ENABLE TRIGGER trg_hermes_run_links_append_only"
            )


def test_adversary_cannot_set_session_replication_role(hardened_db) -> None:
    """Setting session_replication_role is superuser-only; the role cannot."""
    settings, database = hardened_db
    _provision_adversary(database)

    adv_url = _url_as(_plain_url(settings), ADVERSARY_ROLE, "adv-pass")
    with (
        psycopg.connect(adv_url, autocommit=True) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SET session_replication_role = replica")


def test_enable_always_fires_under_replica_mode(hardened_db) -> None:
    """Even a superuser in replica mode is rejected: ENABLE ALWAYS bypasses the
    session_replication_role skip that an origin-only ('O') trigger would allow.
    This is the regression that proves the V1.2A hardening matters."""
    settings, database = hardened_db
    link_id = _seed_run_link(database)

    # `quant` (the test URL role) is a superuser, so it may set replica mode.
    with database.connect() as conn, conn.transaction():
        conn.execute("SET LOCAL session_replication_role = replica")
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            conn.execute(
                "UPDATE quant_system.hermes_run_links SET relation='input' "
                "WHERE link_id = %s",
                (link_id,),
            )


def test_readiness_requires_enable_always(hardened_db) -> None:
    """Writer readiness accepts only ENABLE ALWAYS ('A'), not origin-only ('O')."""
    settings, database = hardened_db
    assert command_ledger_schema_version(settings) == LEDGER_SCHEMA_VERSION

    # Downgrade one append-only trigger to origin-only ('O'); readiness must drop.
    with database.connect() as conn, conn.transaction():
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links "
            "ENABLE TRIGGER trg_hermes_run_links_append_only"
        )
    try:
        assert command_ledger_schema_version(settings) is None
    finally:
        # Restore ENABLE ALWAYS via the idempotent replay.
        db.run_migrations(database)
    assert command_ledger_schema_version(settings) == LEDGER_SCHEMA_VERSION
