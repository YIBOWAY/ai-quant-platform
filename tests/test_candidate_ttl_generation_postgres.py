from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from psycopg.conninfo import conninfo_to_dict

from quant_system.config.settings import (
    CandidateAdmissionSettings,
    DatabaseSettings,
    Settings,
)
from quant_system.hermes.candidate_admission_authority import (
    candidate_admission_schema_is_ready_on_connection,
    candidate_admission_schema_ready,
)
from quant_system.storage import database as db
from tests.postgres_reset import isolated_test_database_url
from tests.test_agent_v02_migrations_025_026_postgres import THROUGH_026

pytestmark = pytest.mark.pg

MIGRATION_027 = "027_agent_v02_candidate_ttl_window.sql"
MIGRATION_028 = "028_agent_v02_candidate_paper_epoch_fence.sql"


def _base_url() -> str:
    value = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get("QS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    database_name = conninfo_to_dict(value).get("dbname", "")
    if not (database_name.endswith("_tmp") or "test" in database_name):
        pytest.fail("PostgreSQL migration tests require a throwaway base database")
    return value


@contextmanager
def _database(*, purpose: str) -> Iterator[db.Database]:
    with isolated_test_database_url(_base_url(), purpose=purpose) as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database, only=THROUGH_026)
        yield database


def _replace_ttl_constraint(
    database: db.Database,
    *,
    interval: str,
    not_valid: bool = False,
) -> None:
    validation = " NOT VALID" if not_valid else ""
    with database.connect() as conn:
        conn.execute(
            """
            ALTER TABLE quant_system.agent_v02_candidate_admissions
                DROP CONSTRAINT ck_agent_v02_candidate_ttl
            """
        )
        conn.execute(
            f"""
            ALTER TABLE quant_system.agent_v02_candidate_admissions
                ADD CONSTRAINT ck_agent_v02_candidate_ttl
                CHECK (
                    expires_at > opened_at
                    AND expires_at <= opened_at + interval '{interval}'
                ){validation}
            """
        )


def _settings(database: db.Database, *, ttl_seconds: int) -> Settings:
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=database._url,  # noqa: SLF001 - exact isolated test database
            auto_migrate=False,
            connect_timeout_seconds=2,
        ),
        candidate_admission=CandidateAdmissionSettings(
            enabled=True,
            ttl_seconds=ttl_seconds,
        ),
    )


def test_readiness_recognizes_exact_legacy_and_current_ttl_generations() -> None:
    with _database(purpose="ttl-generation") as database:
        with database.connect() as conn:
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is False
            )
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=1800,
                )
                is False
            )
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=1801,
                )
                is False
            )
            marker = conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'quant_system'
                  AND table_name = 'agent_v02_candidate_admission_meta'
                  AND column_name = 'ttl_ceiling_seconds'
                """
            ).fetchone()
            assert marker is None

        db.reset_database_cache()
        assert candidate_admission_schema_ready(_settings(database, ttl_seconds=1800)) is False
        db.reset_database_cache()
        assert candidate_admission_schema_ready(_settings(database, ttl_seconds=1801)) is False

        db.run_migrations(database, only=(MIGRATION_027,))
        db.run_migrations(database, only=(MIGRATION_027,))
        db.run_migrations(database, only=(MIGRATION_028,))

        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT ttl_ceiling_seconds
                FROM quant_system.agent_v02_candidate_admission_meta
                WHERE singleton IS TRUE
                """
            ).fetchone() == (7200,)
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=7200,
                )
                is True
            )
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=7201,
                )
                is False
            )
        db.reset_database_cache()
        assert candidate_admission_schema_ready(_settings(database, ttl_seconds=7200)) is True
        db.reset_database_cache()


def test_readiness_recognizes_original_027_and_rejects_mixed_generations() -> None:
    with _database(purpose="ttl-mixed") as database:
        db.run_migrations(database, only=(MIGRATION_027,))
        db.run_migrations(database, only=(MIGRATION_028,))
        _replace_ttl_constraint(database, interval="2 hours")
        with database.connect() as conn:
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=7200,
                )
                is True
            )
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=7201,
                )
                is False
            )

        db.reset_database_cache()
        assert candidate_admission_schema_ready(_settings(database, ttl_seconds=7200)) is True
        db.reset_database_cache()

        _replace_ttl_constraint(
            database,
            interval="2 hours",
            not_valid=True,
        )
        with database.connect() as conn:
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is False
            )

        _replace_ttl_constraint(database, interval="1 hour")
        with database.connect() as conn:
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is False
            )

        db.run_migrations(database, only=(MIGRATION_027,))
        _replace_ttl_constraint(database, interval="30 minutes")
        with database.connect() as conn:
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is False
            )


def test_027_replay_repairs_marker_and_constraint_together() -> None:
    with _database(purpose="ttl-repair") as database:
        db.run_migrations(database, only=(MIGRATION_027,))
        db.run_migrations(database, only=(MIGRATION_028,))
        with database.connect() as conn:
            conn.execute(
                """
                ALTER TABLE quant_system.agent_v02_candidate_admission_meta
                    DROP CONSTRAINT ck_agent_v02_candidate_ttl_ceiling
                """
            )
            conn.execute(
                """
                ALTER TABLE quant_system.agent_v02_candidate_admission_meta
                    ADD CONSTRAINT ck_agent_v02_candidate_ttl_ceiling
                    CHECK (ttl_ceiling_seconds = 7200 OR TRUE)
                """
            )
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is False
            )

        db.run_migrations(database, only=(MIGRATION_027,))
        _replace_ttl_constraint(database, interval="30 minutes")
        with database.connect() as conn:
            conn.execute(
                """
                ALTER TABLE quant_system.agent_v02_candidate_admission_meta
                    DROP CONSTRAINT ck_agent_v02_candidate_ttl_ceiling
                """
            )
            conn.execute(
                """
                UPDATE quant_system.agent_v02_candidate_admission_meta
                SET ttl_ceiling_seconds = 3600
                WHERE singleton IS TRUE
                """
            )
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=120,
                )
                is False
            )

        db.run_migrations(database, only=(MIGRATION_027,))
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT ttl_ceiling_seconds
                FROM quant_system.agent_v02_candidate_admission_meta
                WHERE singleton IS TRUE
                """
            ).fetchone() == (7200,)
            assert (
                candidate_admission_schema_is_ready_on_connection(
                    conn,
                    required_ttl_seconds=7200,
                )
                is True
            )
