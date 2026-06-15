from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


@contextmanager
def _held_byte_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def test_options_daily_scan_sample_writes_snapshot(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "options",
            "daily-scan",
            "--provider",
            "sample",
            "--top",
            "2",
            "--date",
            "2026-05-03",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "run_date=2026-05-03" in result.output
    assert (tmp_path / "2026-05-03.jsonl").exists()
    assert (tmp_path / "2026-05-03_meta.json").exists()


def test_options_daily_scan_fails_when_scan_lock_is_held(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.cli.run_options_radar",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("scan should not start")),
    )

    with _held_byte_lock(tmp_path / "options_radar_scan.lock"):
        result = runner.invoke(
            app,
            [
                "options",
                "daily-scan",
                "--provider",
                "sample",
                "--top",
                "2",
                "--date",
                "2026-05-03",
                "--output-dir",
                str(tmp_path),
            ],
        )

    assert result.exit_code == 1
    assert "OptionsRadarScanLocked" in result.output
    assert not (tmp_path / "2026-05-03.jsonl").exists()


def test_options_daily_task_refreshes_inputs_and_writes_status(tmp_path: Path) -> None:
    universe_path = tmp_path / "inputs" / "universe.csv"
    earnings_path = tmp_path / "inputs" / "earnings.csv"
    vix_path = tmp_path / "inputs" / "vix.csv"
    output_dir = tmp_path / "scans"

    result = runner.invoke(
        app,
        [
            "options",
            "daily-task",
            "--provider",
            "sample",
            "--top",
            "2",
            "--date",
            "2026-05-03",
            "--universe-source",
            "sample",
            "--earnings-source",
            "sample",
            "--vix-source",
            "sample",
            "--universe-path",
            str(universe_path),
            "--earnings-path",
            str(earnings_path),
            "--vix-path",
            str(vix_path),
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "step=universe status=refreshed" in result.output
    assert "step=earnings status=refreshed" in result.output
    assert "step=vix status=refreshed" in result.output
    assert "step=scan status=completed" in result.output
    assert universe_path.exists()
    assert earnings_path.exists()
    assert vix_path.exists()
    assert (output_dir / "2026-05-03.jsonl").exists()
    assert (output_dir / "2026-05-03_meta.json").exists()
    status = json.loads((output_dir / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed"
    assert status["run_date"] == "2026-05-03"
    assert status["steps"]["universe"]["status"] == "refreshed"
    assert status["steps"]["scan"]["candidate_count"] > 0


def test_options_daily_task_fails_when_scan_lock_is_held(tmp_path: Path, monkeypatch) -> None:
    universe_path = tmp_path / "inputs" / "universe.csv"
    earnings_path = tmp_path / "inputs" / "earnings.csv"
    vix_path = tmp_path / "inputs" / "vix.csv"
    output_dir = tmp_path / "scans"
    existing_status = {
        "status": "running",
        "source": "daily_task",
        "run_date": "2026-05-03",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "daily_task_status.json").write_text(
        json.dumps(existing_status),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "quant_system.cli.run_options_radar",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("scan should not start")),
    )

    with _held_byte_lock(output_dir / "options_radar_scan.lock"):
        result = runner.invoke(
            app,
            [
                "options",
                "daily-task",
                "--provider",
                "sample",
                "--top",
                "2",
                "--date",
                "2026-05-03",
                "--universe-source",
                "sample",
                "--earnings-source",
                "sample",
                "--vix-source",
                "sample",
                "--universe-path",
                str(universe_path),
                "--earnings-path",
                str(earnings_path),
                "--vix-path",
                str(vix_path),
                "--output-dir",
                str(output_dir),
            ],
        )

    assert result.exit_code == 1
    assert "OptionsRadarScanLocked" in result.output
    status = json.loads((output_dir / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status == existing_status


def test_options_daily_scan_dry_run_does_not_write(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "options",
            "daily-scan",
            "--provider",
            "sample",
            "--top",
            "2",
            "--date",
            "2026-05-03",
            "--output-dir",
            str(tmp_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "dry_run=true" in result.output
    assert not (tmp_path / "2026-05-03.jsonl").exists()


def test_options_daily_scan_futu_dry_run_reports_provider_failure(monkeypatch) -> None:
    def fake_fetch(self, underlying: str):
        raise RuntimeError("OpenD unavailable")

    monkeypatch.setattr(
        "quant_system.cli.FutuMarketDataProvider.fetch_option_expirations",
        fake_fetch,
    )

    result = runner.invoke(app, ["options", "daily-scan", "--top", "1", "--dry-run"])

    assert result.exit_code == 3
    assert "provider_check=failed" in result.output
