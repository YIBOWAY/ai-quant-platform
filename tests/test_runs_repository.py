from __future__ import annotations

import json
from pathlib import Path

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.storage import runs_repository as rr


def _disabled_db_settings() -> Settings:
    # Explicit init kwargs override any QS_DATABASE_* values from the local .env.
    return Settings(database=DatabaseSettings(enabled=False, url=None))


def _write_run(root: Path, run_id: str, source: str) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps({"run_id": run_id, "source": source, "metrics": {"sharpe": 1.0}}),
        encoding="utf-8",
    )


def test_index_run_is_noop_when_database_disabled(tmp_path: Path) -> None:
    settings = _disabled_db_settings()
    assert settings.database.enabled is False
    # Must not raise and must not require a database connection.
    rr.index_run("backtest", {"run_id": "backtest-x", "source": "sample"}, tmp_path, settings)


def test_list_run_metadatas_reads_filesystem_when_disabled(tmp_path: Path) -> None:
    settings = _disabled_db_settings()
    root = tmp_path / "backtests"
    _write_run(root, "backtest-20240101T000001Z-aaaaaaaa", "sample")
    _write_run(root, "backtest-20240101T000002Z-bbbbbbbb", "futu")

    rows = rr.list_run_metadatas("backtest", root, settings)

    assert {row["run_id"] for row in rows} == {
        "backtest-20240101T000001Z-aaaaaaaa",
        "backtest-20240101T000002Z-bbbbbbbb",
    }
    assert {row["source"] for row in rows} == {"sample", "futu"}


def test_created_at_parsed_from_run_id() -> None:
    iso = rr._created_at_from_run_id("paper-20260603T010203Z-deadbeef")
    assert iso is not None and iso.startswith("2026-06-03T01:02:03")
    assert rr._created_at_from_run_id("no-timestamp-here") is None


def test_db_backed_list_keeps_filesystem_as_source_of_truth(tmp_path: Path, monkeypatch) -> None:
    settings = _disabled_db_settings()
    root = tmp_path / "backtests"
    _write_run(root, "backtest-file-only", "sample")

    monkeypatch.setattr(
        rr,
        "_db_metadatas",
        lambda kind, current_settings: [
            {"run_id": "backtest-stale-db-only", "source": "futu"},
        ],
    )

    rows = rr.list_run_metadatas("backtest", root, settings)

    assert [row["run_id"] for row in rows] == ["backtest-file-only"]
