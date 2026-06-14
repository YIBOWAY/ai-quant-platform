from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


def test_backup_api_runs_zips_runs_and_manifest_without_secrets(tmp_path) -> None:
    data_dir = tmp_path / "data"
    api_runs = data_dir / "api_runs"
    run_dir = api_runs / "backtests" / "backtest-1"
    account_dir = api_runs / "paper_account" / "default"
    run_dir.mkdir(parents=True)
    account_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text('{"run_id": "backtest-1"}', encoding="utf-8")
    (account_dir / "account.json").write_text('{"account_id": "default"}', encoding="utf-8")
    (account_dir / "positions_snapshot.parquet").write_bytes(b"parquet")
    (data_dir / ".env").write_text("SECRET=do-not-copy", encoding="utf-8")
    (data_dir / "quant_system.duckdb").write_bytes(b"db")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/backup_api_runs.py",
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(data_dir / "backups"),
            "--label",
            "unit",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    archive_path = Path(payload["archive_path"])
    assert archive_path.exists()
    assert archive_path.name.startswith("api_runs-backup-unit-")

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "api_runs/backtests/backtest-1/metadata.json" in names
        assert "api_runs/paper_account/default/account.json" in names
        assert "api_runs/paper_account/default/positions_snapshot.parquet" in names
        assert ".env" not in names
        assert "quant_system.duckdb" not in names
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))

    assert manifest["data_dir"] == str(data_dir.resolve())
    assert manifest["included_root"] == "api_runs"
    assert manifest["file_count"] == 3
    assert manifest["excluded_patterns"] == [
        "*.duckdb",
        "*.duckdb.wal",
        "*.duckdb.tmp",
        "*.lock",
        ".env",
        ".env.*",
    ]
