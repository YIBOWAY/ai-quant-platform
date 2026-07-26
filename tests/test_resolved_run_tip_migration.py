from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from quant_system.hermes.command_ledger import (
    ROOT_USER_ID,
    command_ledger_schema_is_ready_on_connection,
)
from quant_system.storage import database as db
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg

MIGRATION = "023_agent_v02_resolved_run_tip.sql"


def test_023_triple_replay_backfills_exact_tip_and_preserves_security() -> None:
    base_url = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not base_url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")

    with isolated_test_database_url(base_url, purpose="resolved23") as url:
        database = db.Database(url, connect_timeout=2)
        sql_dir = Path(__file__).resolve().parents[1] / "scripts" / "sql"
        predecessors = tuple(
            path.name
            for path in sorted(sql_dir.glob("*.sql"))
            if path.name < MIGRATION
        )
        db.run_migrations(database, only=predecessors)

        command_id = uuid4()
        link_id = uuid4()
        with database.connect() as conn:
            conn.execute(
                """
                INSERT INTO quant_system.hermes_commands (
                    command_id, owner_user_id, platform_session_id,
                    client_request_id, kind, canonical_request_digest,
                    payload_ref, state, version, hermes_session_id,
                    hermes_run_id
                )
                VALUES (
                    %s, %s, 'legacy-root-session', %s, 'research_chat',
                    %s, %s, 'delivered', 1, 'legacy-hermes-root',
                    'legacy-run'
                )
                """,
                (
                    command_id,
                    ROOT_USER_ID,
                    f"legacy-{command_id}",
                    "a" * 64,
                    "platform-payload://sha256/" + ("b" * 64),
                ),
            )
            conn.execute(
                """
                INSERT INTO quant_system.hermes_command_events (
                    command_id, command_version, event_type, actor,
                    to_state, canonical_request_digest, attempt_count,
                    hermes_session_id, hermes_run_id
                )
                VALUES (
                    %s, 1, 'legacy_import', 'system', 'delivered',
                    %s, 0, 'legacy-hermes-root', 'legacy-run'
                )
                """,
                (command_id, "a" * 64),
            )
            conn.execute(
                """
                INSERT INTO quant_system.hermes_run_links (
                    link_id, command_id, platform_resource_type,
                    platform_resource_id, relation, hermes_session_id,
                    hermes_run_id, link_digest, observed_at
                )
                VALUES (
                    %s, %s, 'experiment', 'legacy-experiment', 'output',
                    'legacy-hermes-root', 'legacy-run', %s, now()
                )
                """,
                (link_id, command_id, "c" * 64),
            )

        for _ in range(3):
            db.run_migrations(database, only=(MIGRATION,))

        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT hermes_session_id, resolved_hermes_session_id
                FROM quant_system.hermes_commands
                WHERE command_id = %s
                """,
                (command_id,),
            ).fetchone() == ("legacy-hermes-root", "legacy-hermes-root")
            assert conn.execute(
                """
                SELECT resolved_hermes_session_id
                FROM quant_system.hermes_command_events
                WHERE command_id = %s
                """,
                (command_id,),
            ).fetchone() == ("legacy-hermes-root",)
            assert conn.execute(
                """
                SELECT resolved_hermes_session_id
                FROM quant_system.hermes_run_links
                WHERE link_id = %s
                """,
                (link_id,),
            ).fetchone() == ("legacy-hermes-root",)
            security = conn.execute(
                """
                SELECT
                    relation.relrowsecurity,
                    relation.relforcerowsecurity
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'quant_system'
                  AND relation.relname = 'hermes_commands'
                """
            ).fetchone()
            assert security == (True, True)
            privileges = conn.execute(
                """
                SELECT
                    has_column_privilege(
                        'quant_runtime',
                        'quant_system.hermes_commands',
                        'resolved_hermes_session_id',
                        'SELECT'
                    ),
                    has_column_privilege(
                        'quant_runtime',
                        'quant_system.hermes_commands',
                        'resolved_hermes_session_id',
                        'UPDATE'
                    ),
                    has_column_privilege(
                        'quant_readonly',
                        'quant_system.hermes_commands',
                        'resolved_hermes_session_id',
                        'SELECT'
                    ),
                    has_column_privilege(
                        'quant_readonly',
                        'quant_system.hermes_commands',
                        'resolved_hermes_session_id',
                        'UPDATE'
                    ),
                    NOT EXISTS (
                        SELECT 1
                        FROM information_schema.role_column_grants
                        WHERE grantee = 'PUBLIC'
                          AND table_schema = 'quant_system'
                          AND table_name = 'hermes_commands'
                          AND column_name = 'resolved_hermes_session_id'
                    )
                """
            ).fetchone()
            assert privileges == (True, True, True, False, True)
            assert command_ledger_schema_is_ready_on_connection(conn)
