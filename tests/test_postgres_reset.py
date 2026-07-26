"""Regression tests for migration-tolerant PostgreSQL test resets."""

from __future__ import annotations

import os

import pytest

from quant_system.storage import database as db
from tests.postgres_reset import (
    isolated_test_database_url,
    truncate_with_fk_dependents,
)

pytestmark = pytest.mark.pg

BASE_MIGRATIONS = (
    "001_runs_index.sql",
    "002_ai_news_cache.sql",
    "003_app_users_brief_ai_reports.sql",
    "004_paper_account_tables.sql",
    "005_hermes_command_ledger.sql",
    "006_hermes_workflow_binding.sql",
)
HERMES_ROOTS = (
    "quant_system.hermes_command_workflow_bindings",
    "quant_system.hermes_run_links",
    "quant_system.hermes_outbox",
    "quant_system.hermes_command_events",
    "quant_system.hermes_commands",
    "quant_system.hermes_workspace_sessions",
)


def _base_url() -> str:
    url = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    return url


def _trigger_mode(database: db.Database, trigger_name: str) -> str:
    with database.connect() as conn:
        row = conn.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgname = %s",
            (trigger_name,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_reset_tolerates_partially_applied_migration_ladder() -> None:
    with isolated_test_database_url(_base_url(), purpose="resetpart") as url:
        database = db.Database(url, connect_timeout=1)
        db.run_migrations(database, only=BASE_MIGRATIONS)

        truncate_with_fk_dependents(database, HERMES_ROOTS)

        with database.connect() as conn:
            assert conn.execute(
                "SELECT to_regclass('quant_system.agent_v02_vertical_a_claims')"
            ).fetchone() == (None,)
        assert (
            _trigger_mode(
                database,
                "trg_hermes_command_events_append_only_truncate",
            )
            == "A"
        )


def test_reset_discovers_full_ladder_fk_dependents_and_restores_triggers() -> None:
    with isolated_test_database_url(_base_url(), purpose="resetfull") as url:
        database = db.Database(url, connect_timeout=1)
        db.run_migrations(database)

        truncate_with_fk_dependents(database, HERMES_ROOTS)

        with database.connect() as conn:
            assert conn.execute(
                "SELECT to_regclass('quant_system.agent_v02_vertical_a_claims')"
            ).fetchone() != (None,)
        assert (
            _trigger_mode(
                database,
                "trg_agent_v02_vertical_a_claim_guard",
            )
            == "A"
        )
