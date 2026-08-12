from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from quant_system.brief.rollup_repository import (
    BriefRollupNotFound,
    BriefRollupRepository,
)
from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.storage import database as db
from quant_system.storage.database import list_migration_files
from tests.postgres_reset import isolated_test_database_url

MIGRATION = Path("scripts/sql/033_brief_rollups.sql")


def test_033_is_ordered_after_d34_artifact_canary() -> None:
    names = list_migration_files()
    assert names.index("032_d34_artifact_canary.sql") < names.index(MIGRATION.name)


def test_033_creates_only_the_two_rollup_tables() -> None:
    compact = " ".join(MIGRATION.read_text(encoding="utf-8").split())

    assert compact.count("CREATE TABLE IF NOT EXISTS") == 2
    for forbidden in (
        "ALTER TABLE",
        "DROP TABLE",
        "INSERT INTO",
        "CREATE INDEX",
        "CREATE SCHEMA",
        "GRANT",
        "REVOKE",
        "TRIGGER",
        "BEGIN;",
        "COMMIT;",
    ):
        assert forbidden not in compact


def test_033_defines_rollup_issue_and_snapshot_columns() -> None:
    compact = " ".join(MIGRATION.read_text(encoding="utf-8").split())

    assert "CREATE TABLE IF NOT EXISTS quant_system.brief_rollup_issues" in compact
    assert "CREATE TABLE IF NOT EXISTS quant_system.brief_rollup_snapshots" in compact
    for fragment in (
        "rollup_id UUID PRIMARY KEY",
        "public_id TEXT NOT NULL UNIQUE",
        "owner_user_id UUID NOT NULL REFERENCES quant_system.app_users(id)",
        "kind TEXT NOT NULL CHECK (kind IN ('weekly','monthly'))",
        "period_key TEXT NOT NULL",
        "period_start DATE NOT NULL",
        "period_end DATE NOT NULL",
        "locale TEXT NOT NULL DEFAULT 'zh'",
        "status TEXT NOT NULL DEFAULT 'published'",
        "latest_snapshot_id UUID",
        "UNIQUE (owner_user_id, kind, period_key, locale)",
        "snapshot_id UUID PRIMARY KEY",
        (
            "rollup_id UUID NOT NULL REFERENCES "
            "quant_system.brief_rollup_issues(rollup_id) ON DELETE CASCADE"
        ),
        "version INTEGER NOT NULL",
        "payload JSONB NOT NULL",
        "source_watermark JSONB NOT NULL DEFAULT '{}'::jsonb",
        "UNIQUE (rollup_id, version)",
    ):
        assert fragment in compact


def _base_url() -> str:
    value = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get("QS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    database_name = conninfo_to_dict(value).get("dbname", "")
    if not (database_name.endswith("_tmp") or "test" in database_name):
        pytest.fail("brief rollup migration tests require a throwaway base database")
    return value


@contextmanager
def _migrated_url() -> Iterator[str]:
    with isolated_test_database_url(_base_url(), purpose="briefrl") as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database)
        db.run_migrations(database)  # the whole ladder, 033 included, must re-apply cleanly
        yield isolated_url


def _columns(
    conn: psycopg.Connection,
    table: str,
) -> dict[str, tuple[str, str, str | None]]:
    rows = conn.execute(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (db.SCHEMA, table),
    ).fetchall()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


def _constraint_defs(
    conn: psycopg.Connection,
    table: str,
    contype: str,
) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            WHERE c.conrelid = to_regclass(%s)
              AND c.contype = %s
            ORDER BY c.conname
            """,
            (f"{db.SCHEMA}.{table}", contype),
        ).fetchall()
    ]


@pytest.mark.pg
def test_033_tables_and_columns_match_contract() -> None:
    with _migrated_url() as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        with database.connect() as conn:
            issue_columns = _columns(conn, "brief_rollup_issues")
            snapshot_columns = _columns(conn, "brief_rollup_snapshots")

    assert list(issue_columns) == [
        "rollup_id",
        "public_id",
        "owner_user_id",
        "kind",
        "period_key",
        "period_start",
        "period_end",
        "locale",
        "status",
        "latest_snapshot_id",
        "created_at",
        "updated_at",
    ]
    assert issue_columns["rollup_id"] == ("uuid", "NO", None)
    assert issue_columns["kind"][1] == "NO"
    assert issue_columns["period_key"] == ("text", "NO", None)
    assert issue_columns["period_start"] == ("date", "NO", None)
    assert issue_columns["period_end"] == ("date", "NO", None)
    assert issue_columns["locale"][2] == "'zh'::text"
    assert issue_columns["status"][2] == "'published'::text"
    assert issue_columns["latest_snapshot_id"] == ("uuid", "YES", None)
    assert issue_columns["created_at"][0] == "timestamp with time zone"
    assert issue_columns["updated_at"][0] == "timestamp with time zone"

    assert list(snapshot_columns) == [
        "snapshot_id",
        "rollup_id",
        "version",
        "payload",
        "source_watermark",
        "created_at",
    ]
    assert snapshot_columns["snapshot_id"] == ("uuid", "NO", None)
    assert snapshot_columns["rollup_id"] == ("uuid", "NO", None)
    assert snapshot_columns["version"] == ("integer", "NO", None)
    assert snapshot_columns["payload"] == ("jsonb", "NO", None)
    assert snapshot_columns["source_watermark"] == ("jsonb", "NO", "'{}'::jsonb")
    assert snapshot_columns["created_at"][0] == "timestamp with time zone"


@pytest.mark.pg
def test_033_constraints_match_contract() -> None:
    with _migrated_url() as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        with database.connect() as conn:
            issue_primary = _constraint_defs(conn, "brief_rollup_issues", "p")
            issue_uniques = _constraint_defs(conn, "brief_rollup_issues", "u")
            issue_checks = _constraint_defs(conn, "brief_rollup_issues", "c")
            issue_foreign = _constraint_defs(conn, "brief_rollup_issues", "f")
            snapshot_primary = _constraint_defs(conn, "brief_rollup_snapshots", "p")
            snapshot_uniques = _constraint_defs(conn, "brief_rollup_snapshots", "u")
            snapshot_foreign = _constraint_defs(conn, "brief_rollup_snapshots", "f")

    assert issue_primary == ["PRIMARY KEY (rollup_id)"]
    assert "UNIQUE (public_id)" in issue_uniques
    assert "UNIQUE (owner_user_id, kind, period_key, locale)" in issue_uniques
    assert len(issue_checks) == 1
    assert "kind" in issue_checks[0]
    assert "weekly" in issue_checks[0]
    assert "monthly" in issue_checks[0]
    assert len(issue_foreign) == 1
    assert issue_foreign[0].startswith("FOREIGN KEY (owner_user_id) REFERENCES")
    assert "app_users(id)" in issue_foreign[0]

    assert snapshot_primary == ["PRIMARY KEY (snapshot_id)"]
    assert snapshot_uniques == ["UNIQUE (rollup_id, version)"]
    assert len(snapshot_foreign) == 1
    assert snapshot_foreign[0].startswith("FOREIGN KEY (rollup_id) REFERENCES")
    assert "brief_rollup_issues(rollup_id)" in snapshot_foreign[0]
    assert "ON DELETE CASCADE" in snapshot_foreign[0]


@pytest.mark.pg
def test_033_repository_round_trip_on_migrated_schema() -> None:
    with _migrated_url() as isolated_url:
        settings = Settings(
            database=DatabaseSettings(
                enabled=True,
                url=isolated_url,
                auto_migrate=False,
                connect_timeout_seconds=2,
            )
        )
        db.reset_database_cache()
        try:
            repository = BriefRollupRepository(settings)
            payload = {
                "title": "第 33 周周报",
                "main_storyline": "A" * 200,
                "sections": [{"label": "市场", "items": []}],
            }
            first = repository.create_snapshot(
                kind="weekly",
                period_key="2026-W33",
                period_start=date(2026, 8, 10),
                period_end=date(2026, 8, 16),
                locale="zh",
                public_id="brf_w_2026w33_roundtrip",
                payload=payload,
                source_watermark={"captured_at": "2026-08-16T08:30:00Z", "sources": []},
            )
            assert first.issue.public_id == "brf_w_2026w33_roundtrip"
            assert first.issue.kind == "weekly"
            assert first.issue.period_key == "2026-W33"
            assert first.snapshot.version == 1
            assert first.snapshot.payload == payload

            regenerated_payload = {
                "title": "第 33 周周报 v2",
                "main_storyline": "B" * 200,
            }
            second = repository.create_snapshot(
                kind="weekly",
                period_key="2026-W33",
                period_start=date(2026, 8, 10),
                period_end=date(2026, 8, 16),
                locale="zh",
                public_id="brf_w_2026w33_regenerated",
                payload=regenerated_payload,
            )
            assert second.issue.rollup_id == first.issue.rollup_id
            assert second.issue.public_id == first.issue.public_id
            assert second.snapshot.version == 2
            assert second.snapshot.payload == regenerated_payload
            assert second.snapshot.source_watermark == {}

            fetched = repository.get_latest_by_public_id(first.issue.public_id)
            assert fetched.issue == second.issue
            assert fetched.snapshot == second.snapshot

            with pytest.raises(BriefRollupNotFound):
                repository.get_latest_by_public_id("brf_w_missing")

            monthly = repository.create_snapshot(
                kind="monthly",
                period_key="2026-08",
                period_start=date(2026, 8, 1),
                period_end=date(2026, 8, 31),
                locale="zh",
                public_id="brf_m_202608_roundtrip",
                payload={"title": "2026 年 8 月月报", "main_storyline": "C"},
            )
            weekly_items = repository.list_rollups(kind="weekly", locale="zh")
            assert [item.public_id for item in weekly_items] == [first.issue.public_id]
            assert weekly_items[0].period_start == date(2026, 8, 10)
            assert weekly_items[0].period_end == date(2026, 8, 16)
            assert weekly_items[0].title == "第 33 周周报 v2"
            assert weekly_items[0].snippet == "B" * 120

            monthly_items = repository.list_rollups(kind="monthly", locale="zh")
            assert [item.public_id for item in monthly_items] == [monthly.issue.public_id]
            assert monthly_items[0].title == "2026 年 8 月月报"

            assert repository.list_rollups(kind="weekly", locale="en") == []
        finally:
            db.reset_database_cache()
