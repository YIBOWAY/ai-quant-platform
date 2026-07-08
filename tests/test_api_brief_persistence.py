from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql as pg_sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.api.server import create_app
from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.storage import database as db

MIGRATION_PATH = Path("scripts/sql/003_app_users_brief_ai_reports.sql")
ROOT_USER_ID = "00000000-0000-0000-0000-000000000001"


def _compact(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def _ensure_test_database(url: str) -> None:
    params = conninfo_to_dict(url)
    dbname = params.get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail(
            "QS_TEST_DATABASE_URL must point at a throwaway test database "
            f"(got {dbname!r})"
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
            conn.execute(
                pg_sql.SQL("CREATE DATABASE {}").format(pg_sql.Identifier(dbname))
            )


def _postgres_settings(*, auto_migrate: bool = True) -> Settings:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    _ensure_test_database(url)
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=auto_migrate,
            connect_timeout_seconds=1,
        )
    )


def _primary_key_columns(conn: psycopg.Connection, table: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT a.attname
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY AS cols(attnum, ord)
              ON true
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid
             AND a.attnum = cols.attnum
            WHERE c.conrelid = to_regclass(%s)
              AND c.contype = 'p'
            ORDER BY cols.ord
            """,
            (table,),
        ).fetchall()
    ]


def _foreign_key_column_pairs(
    conn: psycopg.Connection,
    table: str,
    constraint_name: str,
) -> list[tuple[str, str]]:
    return [
        (row[0], row[1])
        for row in conn.execute(
            """
            SELECT source_attr.attname, target_attr.attname
            FROM pg_constraint c
            JOIN unnest(c.conkey) WITH ORDINALITY AS source_cols(attnum, ord)
              ON true
            JOIN unnest(c.confkey) WITH ORDINALITY AS target_cols(attnum, ord)
              ON target_cols.ord = source_cols.ord
            JOIN pg_attribute source_attr
              ON source_attr.attrelid = c.conrelid
             AND source_attr.attnum = source_cols.attnum
            JOIN pg_attribute target_attr
              ON target_attr.attrelid = c.confrelid
             AND target_attr.attnum = target_cols.attnum
            WHERE c.conrelid = to_regclass(%s)
              AND c.conname = %s
              AND c.contype = 'f'
            ORDER BY source_cols.ord
            """,
            (table, constraint_name),
        ).fetchall()
    ]


def test_brief_migration_defines_required_tables_and_root_seed() -> None:
    assert MIGRATION_PATH.exists(), f"{MIGRATION_PATH} does not exist"

    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    compact = _compact(sql)

    assert "CREATE SCHEMA IF NOT EXISTS quant_system" in compact
    for table in (
        "app_users",
        "brief_issues",
        "brief_snapshots",
        "brief_snapshot_sources",
        "ai_news_daily_reports",
    ):
        assert f"CREATE TABLE IF NOT EXISTS quant_system.{table}" in compact

    assert "INSERT INTO quant_system.app_users" in compact
    assert ROOT_USER_ID in compact
    assert "'root'" in compact
    assert "ON CONFLICT (id) DO UPDATE" in compact
    assert "username = 'root'" in compact
    assert "RAISE EXCEPTION" in compact

    expected_fragments = (
        "id UUID PRIMARY KEY",
        "username TEXT NOT NULL UNIQUE",
        "role TEXT NOT NULL DEFAULT 'root'",
        "is_active BOOLEAN NOT NULL DEFAULT TRUE",
        "issue_id UUID PRIMARY KEY",
        "public_id TEXT NOT NULL UNIQUE",
        "owner_user_id UUID NOT NULL REFERENCES quant_system.app_users(id)",
        "issue_date DATE NOT NULL",
        "market_session_date DATE",
        "locale TEXT NOT NULL DEFAULT 'zh'",
        "status TEXT NOT NULL DEFAULT 'published'",
        "latest_snapshot_id UUID",
        "share_token_hash TEXT",
        "UNIQUE (owner_user_id, issue_date, locale)",
        "snapshot_id UUID PRIMARY KEY",
        "issue_id UUID NOT NULL REFERENCES quant_system.brief_issues(issue_id) ON DELETE CASCADE",
        "version INTEGER NOT NULL",
        "payload JSONB NOT NULL",
        "rendered_text TEXT",
        "source_watermark JSONB NOT NULL DEFAULT '{}'::jsonb",
        "UNIQUE (issue_id, version)",
        "CONSTRAINT uq_brief_snapshots_issue_snapshot UNIQUE (issue_id, snapshot_id)",
        "id BIGSERIAL PRIMARY KEY",
        (
            "snapshot_id UUID NOT NULL REFERENCES "
            "quant_system.brief_snapshots(snapshot_id) ON DELETE CASCADE"
        ),
        "source_type TEXT NOT NULL",
        "source_id TEXT",
        "source_uri TEXT",
        "payload JSONB NOT NULL DEFAULT '{}'::jsonb",
        (
            f"owner_user_id UUID NOT NULL DEFAULT '{ROOT_USER_ID}'::uuid "
            "REFERENCES quant_system.app_users(id)"
        ),
        "provider TEXT NOT NULL DEFAULT 'aihot'",
        "report_date DATE NOT NULL",
        "fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()",
        "generated_at TIMESTAMPTZ",
        "lead JSONB NOT NULL DEFAULT '{}'::jsonb",
        "sections JSONB NOT NULL DEFAULT '[]'::jsonb",
        "flashes JSONB NOT NULL DEFAULT '[]'::jsonb",
        "warnings JSONB NOT NULL DEFAULT '[]'::jsonb",
        "raw JSONB NOT NULL DEFAULT '{}'::jsonb",
        "PRIMARY KEY (owner_user_id, provider, report_date)",
    )
    for fragment in expected_fragments:
        assert fragment in compact


def test_brief_migration_is_idempotent_and_run_migration_safe() -> None:
    assert MIGRATION_PATH.name.startswith("003_")
    assert MIGRATION_PATH.exists(), f"{MIGRATION_PATH} does not exist"

    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    compact = _compact(sql)

    assert "CREATE TABLE IF NOT EXISTS" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_brief_issues_owner_date" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_brief_snapshots_issue_version" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_brief_sources_snapshot_type" in compact
    assert "CREATE INDEX IF NOT EXISTS idx_ai_news_daily_reports_owner_provider_date" in compact

    assert "uq_brief_snapshots_issue_snapshot" in compact
    assert "UNIQUE (issue_id, snapshot_id)" in compact
    assert "DROP CONSTRAINT IF EXISTS fk_brief_latest_snapshot" in compact
    guard_position = compact.index("conname = 'uq_brief_snapshots_issue_snapshot'")
    alter_position = compact.index("ADD CONSTRAINT fk_brief_latest_snapshot")
    assert "DO $$" in compact
    assert guard_position < alter_position
    assert "FOREIGN KEY (issue_id, latest_snapshot_id)" in compact
    assert "REFERENCES quant_system.brief_snapshots(issue_id, snapshot_id)" in compact
    assert "DEFERRABLE INITIALLY DEFERRED" in compact


def test_generate_brief_issue_requires_database_when_disabled(tmp_path) -> None:
    db.reset_database_cache()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/brief/issues/generate",
        json={"issue_date": "2026-07-08", "locale": "zh"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


def test_get_brief_issue_requires_database_when_disabled(tmp_path) -> None:
    db.reset_database_cache()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/brief/issues/brf_20260708_missing")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


@pytest.mark.pg
def test_generate_brief_issue_persists_postgres_snapshot_versions(tmp_path) -> None:
    settings = _postgres_settings(auto_migrate=False)
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    try:
        db.run_migrations(database)
        with database.connect() as conn:
            conn.execute(
                """
                DELETE FROM quant_system.brief_issues
                WHERE owner_user_id = %s
                  AND issue_date = %s
                  AND locale = %s
                """,
                (ROOT_USER_ID, "2026-07-08", "zh"),
            )

        client = TestClient(create_app(settings=settings, output_dir=tmp_path))
        first = client.post(
            "/api/brief/issues/generate",
            json={"issue_date": "2026-07-08", "locale": "zh"},
        )
        assert first.status_code == 200
        first_body = first.json()
        public_id = first_body["issue"]["public_id"]
        assert re.fullmatch(r"brf_20260708_[a-z0-9]+", public_id)
        assert first_body["issue"]["issue_date"] == "2026-07-08"
        assert first_body["issue"]["locale"] == "zh"
        assert first_body["snapshot"]["version"] == 1
        assert first_body["snapshot"]["payload"] == {
            "title": "每日晨报",
            "issue_date": "2026-07-08",
            "sections": {
                "market": [],
                "ai_news": [],
                "paper_equity": [],
                "hermes_log": [],
            },
        }

        fetched = client.get(f"/api/brief/issues/{public_id}")
        assert fetched.status_code == 200
        fetched_body = fetched.json()
        assert fetched_body["issue"] == first_body["issue"]
        assert fetched_body["snapshot"] == first_body["snapshot"]

        second = client.post(
            "/api/brief/issues/generate",
            json={"issue_date": "2026-07-08", "locale": "zh"},
        )
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["issue"]["public_id"] == public_id
        assert second_body["snapshot"]["version"] == 2

        latest = client.get(f"/api/brief/issues/{public_id}")
        assert latest.status_code == 200
        latest_body = latest.json()
        assert latest_body["issue"] == second_body["issue"]
        assert latest_body["snapshot"] == second_body["snapshot"]
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    """
                    DELETE FROM quant_system.brief_issues
                    WHERE owner_user_id = %s
                      AND issue_date = %s
                      AND locale = %s
                    """,
                    (ROOT_USER_ID, "2026-07-08", "zh"),
                )
        finally:
            db.reset_database_cache()


@pytest.mark.pg
def test_get_missing_brief_issue_returns_404_when_database_enabled(tmp_path) -> None:
    settings = _postgres_settings(auto_migrate=False)
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    public_id = "brf_20990101_missing404"
    try:
        db.run_migrations(database)
        with database.connect() as conn:
            conn.execute(
                "DELETE FROM quant_system.brief_issues WHERE public_id = %s",
                (public_id,),
            )

        client = TestClient(create_app(settings=settings, output_dir=tmp_path))
        response = client.get(f"/api/brief/issues/{public_id}")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "brief_not_found"
    finally:
        db.reset_database_cache()


@pytest.mark.pg
def test_brief_migration_applies_idempotently_in_postgres() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    try:
        db.run_migrations(database)
        db.run_migrations(database)

        with database.connect() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                      AND table_name IN (
                          'app_users',
                          'brief_issues',
                          'brief_snapshots',
                          'brief_snapshot_sources',
                          'ai_news_daily_reports'
                      )
                    """,
                    (db.SCHEMA,),
                ).fetchall()
            }
            root_row = conn.execute(
                """
                SELECT id::text, username, role, is_active
                FROM quant_system.app_users
                WHERE id = %s
                """,
                (ROOT_USER_ID,),
            ).fetchone()
            latest_snapshot_fk_count = conn.execute(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname = 'fk_brief_latest_snapshot'
                  AND conrelid = 'quant_system.brief_issues'::regclass
                  AND contype = 'f'
                """
            ).fetchone()[0]
            latest_snapshot_fk_pairs = _foreign_key_column_pairs(
                conn,
                "quant_system.brief_issues",
                "fk_brief_latest_snapshot",
            )
            snapshot_issue_unique_count = conn.execute(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname = 'uq_brief_snapshots_issue_snapshot'
                  AND conrelid = 'quant_system.brief_snapshots'::regclass
                  AND contype = 'u'
                """
            ).fetchone()[0]
            daily_report_pk_columns = _primary_key_columns(
                conn,
                "quant_system.ai_news_daily_reports",
            )

        assert tables == {
            "app_users",
            "brief_issues",
            "brief_snapshots",
            "brief_snapshot_sources",
            "ai_news_daily_reports",
        }
        assert root_row == (ROOT_USER_ID, "root", "root", True)
        assert latest_snapshot_fk_count == 1
        assert latest_snapshot_fk_pairs == [
            ("issue_id", "issue_id"),
            ("latest_snapshot_id", "snapshot_id"),
        ]
        assert snapshot_issue_unique_count == 1
        assert daily_report_pk_columns == ["owner_user_id", "provider", "report_date"]
    finally:
        db.reset_database_cache()


@pytest.mark.pg
def test_ai_news_daily_reports_old_shape_upgrades_without_losing_rows() -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    try:
        with database.connect() as conn:
            conn.execute("CREATE SCHEMA IF NOT EXISTS quant_system")
            conn.execute("DROP TABLE IF EXISTS quant_system.ai_news_daily_reports")
            conn.execute(
                """
                CREATE TABLE quant_system.ai_news_daily_reports (
                    provider      TEXT NOT NULL DEFAULT 'aihot',
                    report_date   DATE NOT NULL,
                    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                    generated_at  TIMESTAMPTZ,
                    lead          JSONB NOT NULL DEFAULT '{}'::jsonb,
                    sections      JSONB NOT NULL DEFAULT '[]'::jsonb,
                    flashes       JSONB NOT NULL DEFAULT '[]'::jsonb,
                    warnings      JSONB NOT NULL DEFAULT '[]'::jsonb,
                    raw           JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (provider, report_date)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO quant_system.ai_news_daily_reports
                    (provider, report_date, lead, raw)
                VALUES
                    (
                        'aihot',
                        '2026-07-08',
                        '{"headline": "old"}'::jsonb,
                        '{"source": "legacy"}'::jsonb
                    )
                """
            )

        db.run_migrations(database)
        db.run_migrations(database)

        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT owner_user_id::text,
                       provider,
                       report_date::text,
                       lead ->> 'headline',
                       raw ->> 'source'
                FROM quant_system.ai_news_daily_reports
                WHERE provider = 'aihot'
                  AND report_date = '2026-07-08'
                """
            ).fetchone()
            daily_report_pk_columns = _primary_key_columns(
                conn,
                "quant_system.ai_news_daily_reports",
            )

        assert row == (ROOT_USER_ID, "aihot", "2026-07-08", "old", "legacy")
        assert daily_report_pk_columns == ["owner_user_id", "provider", "report_date"]
    finally:
        try:
            with database.connect() as conn:
                conn.execute("DROP TABLE IF EXISTS quant_system.ai_news_daily_reports")
        finally:
            db.reset_database_cache()
