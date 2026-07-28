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


def _brief_generate_request(issue_date: str, locale: str) -> dict[str, object]:
    title = "每日晨报" if locale == "zh" else "Daily Morning Brief"
    lede = "平台当日事实快照。" if locale == "zh" else "Snapshot of today's platform facts."
    return {
        "issue_date": issue_date,
        "locale": locale,
        "payload": {
            "schema_version": "brief_snapshot_v1",
            "title": title,
            "issue_date": issue_date,
            "locale": locale,
            "generated_at": f"{issue_date}T08:30:00Z",
            "lede": lede,
            "account": {
                "account_id": "default",
                "base_currency": "USD",
                "equity": 100_100,
                "cash": 60_000,
                "pnl_abs": 100,
                "pnl_pct": 0.001,
                "invested_pct": 0.4,
                "price_source": {"kind": "sample", "as_of": f"{issue_date}T08:29:00Z"},
                "positions": [],
            },
            "paper_equity": [
                {
                    "timestamp": f"{issue_date}T08:29:00Z",
                    "equity": 100_100,
                    "cash": 60_000,
                    "market_value": 40_100,
                    "source": "current_quote",
                }
            ],
            "markets": [
                {
                    "symbol": "SPY",
                    "last": 620.2,
                    "change_pct": 0.004,
                    "source": "sample",
                    "as_of": f"{issue_date}T00:00:00Z",
                }
            ],
            "market_note": "SPY +0.40%",
            "ai_news": [
                {
                    "id": "news-1",
                    "title": "Archived AI item",
                    "url": "https://example.com/news-1",
                    "source": "example",
                    "published_at": f"{issue_date}T01:00:00Z",
                    "summary": "Persisted AI summary",
                    "category": "models",
                    "score": 8.5,
                }
            ],
            "hermes_log": [
                {
                    "timestamp": f"{issue_date}T02:00:00Z",
                    "status": "ok",
                    "text": "Hermes completed a read-only research run",
                    "href": "/hermes/results/run-1",
                    "summary": "run-1",
                }
            ],
            "warnings": [],
        },
        "source_watermark": {
            "captured_at": f"{issue_date}T08:30:00Z",
            "sources": [
                {
                    "name": "paper_account",
                    "status": "available",
                    "as_of": f"{issue_date}T08:29:00Z",
                    "detail": "sample",
                },
                {
                    "name": "ai_news",
                    "status": "available",
                    "as_of": f"{issue_date}T08:30:00Z",
                    "detail": "example",
                },
            ],
        },
    }


def _compact(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_generate_rejects_unavailable_paper_account_facts_before_database() -> None:
    request = _brief_generate_request("2026-07-14", "zh")
    request["source_watermark"]["sources"][0]["status"] = "unavailable"
    request["source_watermark"]["sources"][0]["detail"] = "503 backend down"
    client = TestClient(create_app())

    response = client.post("/api/brief/issues/generate", json=request)

    assert response.status_code == 422
    assert "paper_account must be available or stale" in response.text


def test_generate_rejects_unknown_envelope_fields_and_duplicate_sources() -> None:
    client = TestClient(create_app())
    request = _brief_generate_request("2026-07-14", "zh")
    request["pretend_success"] = True

    unknown = client.post("/api/brief/issues/generate", json=request)

    assert unknown.status_code == 422
    assert "extra_forbidden" in unknown.text

    request = _brief_generate_request("2026-07-14", "zh")
    request["source_watermark"]["sources"].append(
        dict(request["source_watermark"]["sources"][0])
    )

    duplicate = client.post("/api/brief/issues/generate", json=request)

    assert duplicate.status_code == 422
    assert "source watermark names must be unique" in duplicate.text


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
        json=_brief_generate_request("2026-07-08", "zh"),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


def test_generate_brief_issue_accepts_additive_performance_before_database(
    tmp_path,
) -> None:
    db.reset_database_cache()
    request = _brief_generate_request("2026-07-08", "zh")
    request["payload"]["account"]["positions"] = [
        {
            "symbol": "AAPL",
            "quantity": 10,
            "avg_cost": 100,
            "last_price": 102,
            "market_value": 1_020,
            "weight": 0.00102,
            "unrealized_pnl": 20,
            "price_kind": "futu_snapshot",
            "price_as_of": "2026-07-08T08:29:00Z",
            "previous_close": 101,
            "day_change_ratio": 0.0099009901,
            "day_change_source": "futu_snapshot",
            "day_change_as_of": "2026-07-08T08:29:00Z",
        }
    ]
    request["payload"]["performance"] = {
        "selected_range": "1m",
        "master_range": "3m",
        "granularity": "1d",
        "benchmarks": ["SPY", "QQQ"],
        "requested_start": "2026-04-08",
        "requested_end": "2026-07-08",
        "actual_start": "2026-04-08",
        "actual_end": "2026-07-08",
        "coverage_complete": True,
        "series": [
            {
                "id": "paper",
                "kind": "paper",
                "label": "模拟盘",
                "symbol": None,
                "status": "available",
                "source": "paper_account_ledger+futu_qfq_1d",
                "as_of": "2026-07-08T08:29:00Z",
                "error_code": None,
                "points": [
                    {
                        "date": "2026-04-08",
                        "return_ratio": 0,
                        "equity": 100_000,
                        "close": None,
                    },
                    {
                        "date": "2026-07-08",
                        "return_ratio": 0.001,
                        "equity": 100_100,
                        "close": None,
                    },
                ],
            }
        ],
        "warnings": [],
    }
    request["source_watermark"]["sources"][1].update(
        {"provider": "aihot", "served_from": "cache"}
    )
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post("/api/brief/issues/generate", json=request)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


def test_generate_brief_issue_rejects_empty_placeholder_request(tmp_path) -> None:
    db.reset_database_cache()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.post(
        "/api/brief/issues/generate",
        json={"issue_date": "2026-07-08", "locale": "zh"},
    )

    assert response.status_code == 422


def test_get_brief_issue_requires_database_when_disabled(tmp_path) -> None:
    db.reset_database_cache()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/brief/issues/brf_20260708_missing")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


def test_get_latest_brief_issue_requires_database_when_disabled(tmp_path) -> None:
    db.reset_database_cache()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/brief/issues/latest", params={"locale": "zh"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


def test_list_brief_issues_requires_database_when_disabled(tmp_path) -> None:
    db.reset_database_cache()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/brief/issues", params={"locale": "zh", "limit": 5})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


@pytest.mark.pg
def test_get_latest_brief_issue_returns_404_when_empty(tmp_path) -> None:
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
                  AND locale = %s
                """,
                (ROOT_USER_ID, "zh"),
            )

        client = TestClient(create_app(settings=settings, output_dir=tmp_path))
        response = client.get("/api/brief/issues/latest", params={"locale": "zh"})

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert detail["code"] == "brief_not_found"
        assert "public_id" not in detail
    finally:
        db.reset_database_cache()


@pytest.mark.pg
def test_get_latest_brief_issue_returns_newest_for_locale(tmp_path) -> None:
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
                  AND locale IN (%s, %s)
                  AND issue_date IN (%s, %s)
                """,
                (ROOT_USER_ID, "zh", "en", "2026-07-07", "2026-07-08"),
            )

        client = TestClient(create_app(settings=settings, output_dir=tmp_path))
        older = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-07-07", "zh"),
        )
        newer = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-07-08", "zh"),
        )
        assert older.status_code == 200
        assert newer.status_code == 200
        newer_body = newer.json()
        public_id = newer_body["issue"]["public_id"]

        latest = client.get("/api/brief/issues/latest", params={"locale": "zh"})
        assert latest.status_code == 200
        latest_body = latest.json()
        assert latest_body["issue"]["public_id"] == public_id
        assert latest_body["issue"]["issue_date"] == "2026-07-08"
        assert latest_body["issue"]["locale"] == "zh"
        assert latest_body["snapshot"]["version"] == newer_body["snapshot"]["version"]

        second = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-07-08", "zh"),
        )
        assert second.status_code == 200
        second_body = second.json()
        assert second_body["issue"]["public_id"] == public_id
        assert second_body["snapshot"]["version"] == newer_body["snapshot"]["version"] + 1

        latest_after = client.get("/api/brief/issues/latest", params={"locale": "zh"})
        assert latest_after.status_code == 200
        latest_after_body = latest_after.json()
        assert latest_after_body["issue"]["public_id"] == public_id
        assert latest_after_body["snapshot"]["version"] == second_body["snapshot"]["version"]

        en_only = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-07-08", "en"),
        )
        assert en_only.status_code == 200
        en_public_id = en_only.json()["issue"]["public_id"]
        en_latest = client.get("/api/brief/issues/latest", params={"locale": "en"})
        assert en_latest.status_code == 200
        assert en_latest.json()["issue"]["public_id"] == en_public_id
        assert en_latest.json()["issue"]["locale"] == "en"
        zh_latest = client.get("/api/brief/issues/latest", params={"locale": "zh"})
        assert zh_latest.status_code == 200
        assert zh_latest.json()["issue"]["public_id"] == public_id
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    """
                    DELETE FROM quant_system.brief_issues
                    WHERE owner_user_id = %s
                      AND locale IN (%s, %s)
                      AND issue_date IN (%s, %s)
                    """,
                    (ROOT_USER_ID, "zh", "en", "2026-07-07", "2026-07-08"),
                )
        finally:
            db.reset_database_cache()


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
            json=_brief_generate_request("2026-07-08", "zh"),
        )
        assert first.status_code == 200
        first_body = first.json()
        public_id = first_body["issue"]["public_id"]
        assert re.fullmatch(r"brf_20260708_[a-z0-9]+", public_id)
        assert first_body["issue"]["issue_date"] == "2026-07-08"
        assert first_body["issue"]["locale"] == "zh"
        assert first_body["snapshot"]["version"] == 1
        assert first_body["snapshot"]["payload"] == _brief_generate_request(
            "2026-07-08", "zh"
        )["payload"]
        assert first_body["snapshot"]["source_watermark"] == _brief_generate_request(
            "2026-07-08", "zh"
        )["source_watermark"]

        fetched = client.get(f"/api/brief/issues/{public_id}")
        assert fetched.status_code == 200
        fetched_body = fetched.json()
        assert fetched_body["issue"] == first_body["issue"]
        assert fetched_body["snapshot"] == first_body["snapshot"]

        with database.connect() as conn:
            source_rows = conn.execute(
                """
                SELECT source_type, payload
                FROM quant_system.brief_snapshot_sources
                WHERE snapshot_id = %s
                ORDER BY source_type
                """,
                (first_body["snapshot"]["snapshot_id"],),
            ).fetchall()
        assert [row[0] for row in source_rows] == ["ai_news", "paper_account"]
        assert [dict(row[1]) for row in source_rows] == [
            _brief_generate_request("2026-07-08", "zh")["source_watermark"][
                "sources"
            ][1],
            _brief_generate_request("2026-07-08", "zh")["source_watermark"][
                "sources"
            ][0],
        ]

        second = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-07-08", "zh"),
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
def test_list_brief_issues_reports_full_total_and_stable_page_order(tmp_path) -> None:
    settings = _postgres_settings(auto_migrate=False)
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    issue_dates = (
        "2026-08-01",
        "2026-08-02",
        "2026-08-03",
        "2026-08-04",
    )

    try:
        db.run_migrations(database)
        with database.connect() as conn:
            conn.execute(
                """
                DELETE FROM quant_system.brief_issues
                WHERE owner_user_id = %s
                  AND locale IN (%s, %s)
                  AND issue_date BETWEEN %s AND %s
                """,
                (ROOT_USER_ID, "zh", "en", issue_dates[0], issue_dates[-1]),
            )

        client = TestClient(create_app(settings=settings, output_dir=tmp_path))
        for issue_date in issue_dates:
            created = client.post(
                "/api/brief/issues/generate",
                json=_brief_generate_request(issue_date, "zh"),
            )
            assert created.status_code == 200
        excluded_locale = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request(issue_dates[-1], "en"),
        )
        assert excluded_locale.status_code == 200

        response = client.get(
            "/api/brief/issues",
            params={"locale": "zh", "limit": 2, "offset": 1},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 4
        assert payload["limit"] == 2
        assert payload["offset"] == 1
        assert [item["issue_date"] for item in payload["items"]] == [
            "2026-08-03",
            "2026-08-02",
        ]
        assert {item["locale"] for item in payload["items"]} == {"zh"}
    finally:
        try:
            with database.connect() as conn:
                conn.execute(
                    """
                    DELETE FROM quant_system.brief_issues
                    WHERE owner_user_id = %s
                      AND locale IN (%s, %s)
                      AND issue_date BETWEEN %s AND %s
                    """,
                    (ROOT_USER_ID, "zh", "en", issue_dates[0], issue_dates[-1]),
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
