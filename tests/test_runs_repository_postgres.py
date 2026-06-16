from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.storage import database as db
from quant_system.storage import runs_repository as rr

pytestmark = pytest.mark.pg


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
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname))
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
            auto_migrate=True,
            connect_timeout_seconds=1,
        )
    )


def _write_run(root: Path, run_id: str, source: str) -> dict:
    metadata = {
        "run_id": run_id,
        "source": source,
        "metrics": {"sharpe": 1.0},
    }
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    return metadata


def test_postgres_run_index_backfills_lists_updates_and_prunes(tmp_path: Path) -> None:
    settings = _postgres_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)

    api_runs_dir = tmp_path / "api_runs"
    root = api_runs_dir / "backtests"
    first = _write_run(root, "backtest-20260601T010101Z-pgtesta", "sample")
    second = _write_run(root, "backtest-20260601T010102Z-pgtestb", "sample")

    try:
        indexed = rr.sync_filesystem_to_index(api_runs_dir, settings)
        assert indexed == 2

        rows = rr.list_run_metadatas("backtest", root, settings)
        assert [row["run_id"] for row in rows] == [second["run_id"], first["run_id"]]

        updated = dict(second)
        updated["source"] = "tiingo"
        rr.index_run("backtest", updated, root / second["run_id"], settings)

        rows = rr.list_run_metadatas("backtest", root, settings)
        assert rows[0]["run_id"] == second["run_id"]
        assert rows[0]["source"] == "tiingo"

        for path in (root / first["run_id"]).iterdir():
            path.unlink()
        (root / first["run_id"]).rmdir()

        pruned = rr.sync_filesystem_to_index(api_runs_dir, settings)
        assert pruned == 1

        with database.connect() as conn:
            db_run_ids = {
                row[0]
                for row in conn.execute(
                    f"SELECT run_id FROM {db.SCHEMA}.runs WHERE kind = %s",
                    ("backtest",),
                ).fetchall()
            }
        assert first["run_id"] not in db_run_ids
        assert second["run_id"] in db_run_ids
    finally:
        with database.connect() as conn:
            conn.execute(
                f"DELETE FROM {db.SCHEMA}.runs WHERE run_id LIKE %s",
                ("backtest-20260601T01010%Z-pgtest%",),
            )
        db.reset_database_cache()
