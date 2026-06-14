from __future__ import annotations

import json
import subprocess
import sys


def test_cleanup_api_run_duckdb_reports_and_applies_only_api_run_databases(tmp_path) -> None:
    data_dir = tmp_path / "data"
    api_runs = data_dir / "api_runs"
    run_dir = api_runs / "backtests" / "backtest-1"
    run_dir.mkdir(parents=True)
    ingest_db = data_dir / "quant_system.duckdb"
    options_cache = data_dir / "futu" / "options_cache.duckdb"
    options_cache.parent.mkdir(parents=True)

    target_db = run_dir / "quant_system.duckdb"
    target_wal = run_dir / "quant_system.duckdb.wal"
    target_tmp = run_dir / "quant_system.duckdb.tmp"
    metadata = run_dir / "metadata.json"
    target_db.write_bytes(b"duckdb")
    target_wal.write_bytes(b"wal")
    target_tmp.write_bytes(b"tmp")
    metadata.write_text('{"run_id": "backtest-1"}', encoding="utf-8")
    ingest_db.write_bytes(b"ingest")
    options_cache.write_bytes(b"cache")

    dry_run = subprocess.run(
        [
            sys.executable,
            "scripts/cleanup_api_run_duckdb.py",
            "--api-runs-dir",
            str(api_runs),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert dry_run.returncode == 0, dry_run.stderr
    dry_payload = json.loads(dry_run.stdout)
    assert dry_payload["mode"] == "dry_run"
    assert dry_payload["candidate_count"] == 3
    assert dry_payload["deleted_count"] == 0
    assert dry_payload["total_bytes"] == 12
    assert dry_payload["files"] == [
        "backtests/backtest-1/quant_system.duckdb",
        "backtests/backtest-1/quant_system.duckdb.tmp",
        "backtests/backtest-1/quant_system.duckdb.wal",
    ]
    assert target_db.exists()
    assert target_wal.exists()
    assert target_tmp.exists()

    applied = subprocess.run(
        [
            sys.executable,
            "scripts/cleanup_api_run_duckdb.py",
            "--api-runs-dir",
            str(api_runs),
            "--json",
            "--apply",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert applied.returncode == 0, applied.stderr
    apply_payload = json.loads(applied.stdout)
    assert apply_payload["mode"] == "apply"
    assert apply_payload["candidate_count"] == 3
    assert apply_payload["deleted_count"] == 3
    assert apply_payload["total_bytes"] == 12
    assert not target_db.exists()
    assert not target_wal.exists()
    assert not target_tmp.exists()
    assert metadata.exists()
    assert ingest_db.exists()
    assert options_cache.exists()


def test_cleanup_api_run_duckdb_rejects_data_root_to_protect_ingest_databases(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    api_runs = data_dir / "api_runs" / "backtests" / "backtest-1"
    api_runs.mkdir(parents=True)
    run_db = api_runs / "quant_system.duckdb"
    ingest_db = data_dir / "quant_system.duckdb"
    options_cache = data_dir / "futu" / "options_cache.duckdb"
    options_cache.parent.mkdir(parents=True)
    run_db.write_bytes(b"duckdb")
    ingest_db.write_bytes(b"ingest")
    options_cache.write_bytes(b"cache")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/cleanup_api_run_duckdb.py",
            "--api-runs-dir",
            str(data_dir),
            "--apply",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "must point at an api_runs directory" in result.stderr
    assert run_db.exists()
    assert ingest_db.exists()
    assert options_cache.exists()
