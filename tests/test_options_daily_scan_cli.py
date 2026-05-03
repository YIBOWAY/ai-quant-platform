from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


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
