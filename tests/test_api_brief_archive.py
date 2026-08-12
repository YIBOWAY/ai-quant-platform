from __future__ import annotations

import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql as pg_sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.api.server import create_app
from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.storage import database as db

ROOT_USER_ID = "00000000-0000-0000-0000-000000000001"

# Fixed historical dates with known ISO-week / month relations:
#   2026-07-30 -> ISO 2026-W31, month 2026-07
#   2026-08-04 -> ISO 2026-W32, month 2026-08
#   2026-08-06 -> ISO 2026-W32, month 2026-08
#   2026-08-11 -> ISO 2026-W33, month 2026-08
ISSUE_DATES = ("2026-07-30", "2026-08-04", "2026-08-06", "2026-08-11")


def _brief_generate_request(issue_date: str, locale: str) -> dict[str, object]:
    title = "每日晨报" if locale == "zh" else "Daily Morning Brief"
    lede = (
        f"{issue_date} 平台当日事实快照。"
        if locale == "zh"
        else f"Snapshot of {issue_date} facts."
    )
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
            "ai_news": [],
            "hermes_log": [],
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
                }
            ],
        },
    }


def test_brief_archive_requires_database_when_disabled(tmp_path) -> None:
    db.reset_database_cache()
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/brief/archive", params={"locale": "zh", "months": 3})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "brief_database_unavailable"


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


def _cleanup(database) -> None:
    with database.connect() as conn:
        conn.execute(
            """
            DELETE FROM quant_system.brief_issues
            WHERE owner_user_id = %s
              AND locale IN ('zh', 'en')
              AND issue_date BETWEEN %s AND %s
            """,
            (ROOT_USER_ID, ISSUE_DATES[0], ISSUE_DATES[-1]),
        )


@pytest.mark.pg
def test_brief_archive_groups_daily_weekly_monthly_views(tmp_path) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    try:
        db.run_migrations(database)
        _cleanup(database)
        client = TestClient(create_app(settings=settings, output_dir=tmp_path))
        for issue_date in ISSUE_DATES:
            created = client.post(
                "/api/brief/issues/generate",
                json=_brief_generate_request(issue_date, "zh"),
            )
            assert created.status_code == 200
        en_created = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-08-10", "en"),
        )
        assert en_created.status_code == 200

        response = client.get(
            "/api/brief/archive",
            params={"locale": "zh", "months": 24},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["locale"] == "zh"
        assert payload["months"] == 24

        daily = {group["key"]: group["entries"] for group in payload["daily"]}
        assert [entry["issue_date"] for entry in daily["2026-08"]] == [
            "2026-08-11",
            "2026-08-06",
            "2026-08-04",
        ]
        assert [entry["issue_date"] for entry in daily["2026-07"]] == ["2026-07-30"]
        august_entry = daily["2026-08"][0]
        assert august_entry["kind"] == "daily"
        assert august_entry["title"] == "每日晨报"
        assert august_entry["snippet"].startswith("2026-08-11")
        assert august_entry["public_id"].startswith("brf_20260811_")

        weekly = [entry for group in payload["weekly"] for entry in group["entries"]]
        assert [(entry["issue_date"], entry["iso_week"]) for entry in weekly] == [
            ("2026-08-11", "2026-W33"),
            ("2026-08-06", "2026-W32"),  # last daily issue of ISO week 32 wins
            ("2026-07-30", "2026-W31"),
        ]
        assert all(entry["kind"] == "weekly" for entry in weekly)

        monthly = [entry for group in payload["monthly"] for entry in group["entries"]]
        assert [(entry["issue_date"], entry["month"]) for entry in monthly] == [
            ("2026-08-11", "2026-08"),
            ("2026-07-30", "2026-07"),
        ]
        assert all(entry["kind"] == "monthly" for entry in monthly)
        assert [group["key"] for group in payload["monthly"]] == ["2026"]

        # zh view never leaks the en-only issue
        all_zh_ids = {
            entry["public_id"]
            for group_list in (payload["daily"], payload["weekly"], payload["monthly"])
            for group in group_list
            for entry in group["entries"]
        }
        assert en_created.json()["issue"]["public_id"] not in all_zh_ids

        en_response = client.get(
            "/api/brief/archive",
            params={"locale": "en", "months": 24},
        )
        assert en_response.status_code == 200
        en_daily = [
            entry for group in en_response.json()["daily"] for entry in group["entries"]
        ]
        assert [entry["issue_date"] for entry in en_daily] == ["2026-08-10"]
    finally:
        try:
            _cleanup(database)
        finally:
            db.reset_database_cache()


@pytest.mark.pg
def test_brief_archive_double_archive_run_stays_one_issue_with_bumped_version(
    tmp_path,
) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None

    try:
        db.run_migrations(database)
        _cleanup(database)
        client = TestClient(create_app(settings=settings, output_dir=tmp_path))

        first = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-08-11", "zh"),
        )
        second = client.post(
            "/api/brief/issues/generate",
            json=_brief_generate_request("2026-08-11", "zh"),
        )
        assert first.status_code == 200 and second.status_code == 200
        assert (
            second.json()["issue"]["public_id"] == first.json()["issue"]["public_id"]
        )
        assert second.json()["snapshot"]["version"] == 2

        listing = client.get("/api/brief/issues", params={"locale": "zh", "limit": 100})
        matching = [
            item
            for item in listing.json()["items"]
            if item["issue_date"] == "2026-08-11" and item["locale"] == "zh"
        ]
        assert len(matching) == 1

        archive = client.get(
            "/api/brief/archive",
            params={"locale": "zh", "months": 24},
        )
        august_daily = next(
            group
            for group in archive.json()["daily"]
            if group["key"] == "2026-08"
        )
        same_day = [
            entry
            for entry in august_daily["entries"]
            if entry["issue_date"] == "2026-08-11"
        ]
        assert len(same_day) == 1
        assert same_day[0]["public_id"] == first.json()["issue"]["public_id"]
    finally:
        try:
            _cleanup(database)
        finally:
            db.reset_database_cache()
