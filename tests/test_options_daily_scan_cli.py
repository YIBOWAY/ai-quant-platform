from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.config.settings import OptionsRadarSettings, Settings
from quant_system.options.radar import OptionsRadarReport

runner = CliRunner()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


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


def test_options_daily_scan_sample_writes_only_unavailable_snapshot(tmp_path: Path) -> None:
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

    assert result.exit_code == 3
    assert "run_date=2026-05-03" in result.output
    assert "status=unavailable" in result.output
    assert "candidates=0" in result.output
    assert len(list(tmp_path.glob("2026-05-03.*.jsonl"))) == 1
    assert (tmp_path / "2026-05-03_meta.json").exists()


def test_options_daily_scan_sample_without_isolated_output_is_zero_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "existing.jsonl").write_bytes(b"existing\n")
    (canonical / "existing_meta.json").write_bytes(b'{"existing":true}\n')
    (canonical / "latest.json").write_bytes(b'{"run_date":"existing"}\n')
    (canonical / "iv_history").mkdir()
    (canonical / "iv_history" / "SPY.sessions.jsonl").write_bytes(b"existing\n")
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=canonical,
            curated_universe_path=canonical / "curated.csv",
        )
    )
    before = _tree_bytes(canonical)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sample canonical rejection touched a writer dependency")

    monkeypatch.setattr("quant_system.cli.reload_settings", lambda: settings)
    monkeypatch.setattr("quant_system.cli.OptionsUniverse.load", forbidden)
    monkeypatch.setattr("quant_system.cli.options_radar_scan_lock", forbidden)
    monkeypatch.setattr("quant_system.cli._build_options_radar_provider", forbidden)
    result = runner.invoke(
        app,
        [
            "options",
            "daily-scan",
            "--provider",
            "sample",
            "--date",
            "2026-05-03",
        ],
    )

    assert result.exit_code == 2
    assert "sample_options_paths_required" in result.output
    assert _tree_bytes(canonical) == before


def test_options_daily_scan_futu_top_one_cannot_write_canonical_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "existing.jsonl").write_bytes(b"existing\n")
    settings = Settings(options_radar=OptionsRadarSettings(output_dir=canonical))
    before = _tree_bytes(canonical)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("ad-hoc canonical rejection touched scan IO")

    monkeypatch.setattr("quant_system.cli.reload_settings", lambda: settings)
    monkeypatch.setattr("quant_system.cli.OptionsUniverse.load", forbidden)
    result = runner.invoke(
        app,
        ["options", "daily-scan", "--provider", "futu", "--top", "1"],
    )

    assert result.exit_code == 2
    assert "options_output_path_required" in result.output
    assert _tree_bytes(canonical) == before


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
    assert list(tmp_path.glob("2026-05-03.*.jsonl")) == []


def test_options_daily_task_refreshes_inputs_and_writes_status(tmp_path: Path) -> None:
    universe_path = tmp_path / "inputs" / "universe.csv"
    earnings_path = tmp_path / "inputs" / "earnings.csv"
    vix_path = tmp_path / "inputs" / "vix.csv"
    dividends_path = tmp_path / "inputs" / "dividends.csv"
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
            "--dividend-source",
            "sample",
            "--universe-path",
            str(universe_path),
            "--earnings-path",
            str(earnings_path),
            "--vix-path",
            str(vix_path),
            "--dividends-path",
            str(dividends_path),
            "--output-dir",
            str(output_dir),
            "--iv-history-dir",
            str(tmp_path / "iv-history"),
        ],
    )

    assert result.exit_code == 3, result.output
    assert "step=universe status=refreshed" in result.output
    assert "step=earnings status=refreshed" in result.output
    assert "step=dividends status=refreshed" in result.output
    assert "step=vix status=refreshed" in result.output
    assert "step=scan status=data_unavailable" in result.output
    assert universe_path.exists()
    assert earnings_path.exists()
    assert vix_path.exists()
    assert dividends_path.exists()
    assert len(list(output_dir.glob("2026-05-03.*.jsonl"))) == 1
    assert (output_dir / "2026-05-03_meta.json").exists()
    status = json.loads((output_dir / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "data_unavailable"
    assert status["run_date"] == "2026-05-03"
    assert status["steps"]["universe"]["status"] == "refreshed"
    assert status["steps"]["dividends"]["status"] == "refreshed"
    assert status["steps"]["dividends"]["source"] == "sample"
    assert status["steps"]["scan"]["candidate_count"] == 0


def test_options_daily_task_uses_existing_static_universe_without_overwrite(
    tmp_path: Path,
) -> None:
    universe_path = tmp_path / "inputs" / "curated_wheel.csv"
    universe_path.parent.mkdir(parents=True)
    original = "\n".join(
        [
            "ticker,name,sector,exchange,source",
            "SPY,SPDR S&P 500 ETF,ETF,US,core_etf",
            "QQQ,Invesco QQQ Trust,ETF,US,core_etf",
        ]
    ) + "\n"
    universe_path.write_text(original, encoding="utf-8")
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
            "existing",
            "--earnings-source",
            "sample",
            "--vix-source",
            "sample",
            "--universe-path",
            str(universe_path),
            "--earnings-path",
            str(tmp_path / "inputs" / "earnings.csv"),
            "--vix-path",
            str(tmp_path / "inputs" / "vix.csv"),
            "--dividend-source",
            "sample",
            "--dividends-path",
            str(tmp_path / "inputs" / "dividends.csv"),
            "--output-dir",
            str(output_dir),
            "--iv-history-dir",
            str(tmp_path / "iv-history"),
        ],
    )

    assert result.exit_code == 3, result.output
    assert universe_path.read_text(encoding="utf-8") == original
    status = json.loads((output_dir / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status["steps"]["universe"]["status"] == "loaded_existing"
    assert status["steps"]["universe"]["row_count"] == 2


def test_options_daily_task_marks_zero_successful_tickers_data_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output_dir = tmp_path / "scans"

    def fake_run_options_radar(**_kwargs):
        return OptionsRadarReport(
            run_date="2026-05-03",
            started_at="2026-05-03T00:00:00+00:00",
            finished_at="2026-05-03T00:01:00+00:00",
            universe_size=2,
            expected_universe_size=2,
            scanned_tickers=0,
            failed_tickers=[
                ("SPY", "FutuProviderError:connection_failed"),
                ("QQQ", "FutuProviderError:connection_failed"),
            ],
            candidates=[],
            provider="sample",
            status="unavailable",
        )

    monkeypatch.setattr("quant_system.cli.run_options_radar", fake_run_options_radar)
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
            str(tmp_path / "inputs" / "universe.csv"),
            "--earnings-path",
            str(tmp_path / "inputs" / "earnings.csv"),
            "--vix-path",
            str(tmp_path / "inputs" / "vix.csv"),
            "--dividend-source",
            "sample",
            "--dividends-path",
            str(tmp_path / "inputs" / "dividends.csv"),
            "--output-dir",
            str(output_dir),
            "--iv-history-dir",
            str(tmp_path / "iv-history"),
        ],
    )

    assert result.exit_code == 3, result.output
    status = json.loads((output_dir / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "data_unavailable"
    assert status["steps"]["scan"]["status"] == "data_unavailable"
    assert status["steps"]["scan"]["scanned_tickers"] == 0


def test_options_daily_task_rejects_sample_inputs_for_futu_before_writes(
    tmp_path: Path,
) -> None:
    universe_path = tmp_path / "universe.csv"
    earnings_path = tmp_path / "earnings.csv"
    vix_path = tmp_path / "vix.csv"
    output_dir = tmp_path / "scans"

    result = runner.invoke(
        app,
        [
            "options",
            "daily-task",
            "--provider",
            "futu",
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
            "--iv-history-dir",
            str(tmp_path / "iv-history"),
        ],
    )

    assert result.exit_code == 2
    assert "sample_options_input_withdrawn" in result.output
    assert not universe_path.exists()
    assert not earnings_path.exists()
    assert not vix_path.exists()
    assert not output_dir.exists()


def test_options_daily_task_sample_mode_requires_isolated_paths() -> None:
    result = runner.invoke(
        app,
        [
            "options",
            "daily-task",
            "--provider",
            "sample",
            "--universe-source",
            "sample",
            "--earnings-source",
            "sample",
            "--vix-source",
            "sample",
        ],
    )

    assert result.exit_code == 2
    assert "sample_options_paths_required" in result.output


def test_options_daily_task_sample_default_sources_are_zero_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    universe = canonical / "universe.csv"
    curated = canonical / "curated.csv"
    earnings = canonical / "earnings.csv"
    vix = canonical / "vix.csv"
    output = canonical / "scans"
    output.mkdir()
    for path in (universe, curated, earnings, vix):
        path.write_bytes(f"existing:{path.name}\n".encode())
    (output / "existing.jsonl").write_bytes(b"existing\n")
    (output / "existing_meta.json").write_bytes(b'{"existing":true}\n')
    (output / "latest.json").write_bytes(b'{"run_date":"existing"}\n')
    (output / "iv_history").mkdir()
    (output / "iv_history" / "SPY.sessions.jsonl").write_bytes(b"existing\n")
    settings = Settings(
        options_radar=OptionsRadarSettings(
            universe_path=universe,
            curated_universe_path=curated,
            earnings_calendar_path=earnings,
            vix_history_path=vix,
            output_dir=output,
        )
    )
    before = _tree_bytes(canonical)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sample canonical rejection touched a writer dependency")

    monkeypatch.setattr("quant_system.cli.reload_settings", lambda: settings)
    monkeypatch.setattr("quant_system.cli.options_radar_scan_lock", forbidden)
    monkeypatch.setattr("quant_system.cli.refresh_options_universe", forbidden)
    monkeypatch.setattr("quant_system.cli.refresh_earnings_calendar", forbidden)
    monkeypatch.setattr("quant_system.cli.refresh_vix_history", forbidden)
    monkeypatch.setattr("quant_system.cli.refresh_dividend_events", forbidden)
    result = runner.invoke(
        app,
        ["options", "daily-task", "--provider", "sample", "--date", "2099-01-03"],
    )

    assert result.exit_code == 2
    assert "sample_options_paths_required" in result.output
    assert _tree_bytes(canonical) == before


def test_options_daily_task_canonical_output_requires_34_requested_symbols(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "existing.jsonl").write_bytes(b"existing\n")
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=canonical,
            curated_universe_path=tmp_path / "curated.csv",
            earnings_calendar_path=tmp_path / "earnings.csv",
            vix_history_path=tmp_path / "vix.csv",
        )
    )
    before = _tree_bytes(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("canonical top rejection touched writer IO")

    monkeypatch.setattr("quant_system.cli.reload_settings", lambda: settings)
    monkeypatch.setattr("quant_system.cli.options_radar_scan_lock", forbidden)
    result = runner.invoke(
        app,
        [
            "options",
            "daily-task",
            "--provider",
            "futu",
            "--top",
            "1",
            "--universe-source",
            "existing",
        ],
    )

    assert result.exit_code == 2
    assert "canonical_options_universe_size_required" in result.output
    assert _tree_bytes(tmp_path) == before


@pytest.mark.parametrize(
    ("universe_source", "override_path"),
    [
        ("public", None),
        ("existing", "other.csv"),
    ],
)
def test_options_daily_task_canonical_output_requires_tracked_curated_universe(
    tmp_path: Path,
    monkeypatch,
    universe_source: str,
    override_path: str | None,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "existing.jsonl").write_bytes(b"existing\n")
    curated = tmp_path / "curated_wheel.csv"
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=canonical,
            universe_path=tmp_path / "wide.csv",
            curated_universe_path=curated,
            earnings_calendar_path=tmp_path / "earnings.csv",
            vix_history_path=tmp_path / "vix.csv",
        )
    )
    before = _tree_bytes(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("canonical universe rejection touched writer IO")

    monkeypatch.setattr("quant_system.cli.reload_settings", lambda: settings)
    monkeypatch.setattr("quant_system.cli.options_radar_scan_lock", forbidden)
    arguments = [
        "options",
        "daily-task",
        "--provider",
        "futu",
        "--top",
        "34",
        "--universe-source",
        universe_source,
    ]
    if override_path is not None:
        arguments.extend(["--universe-path", str(tmp_path / override_path)])

    result = runner.invoke(app, arguments)

    assert result.exit_code == 2
    assert "canonical_options_curated_universe_required" in result.output
    assert _tree_bytes(tmp_path) == before


def test_options_daily_task_rejects_arbitrary_34_ticker_canonical_universe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    curated = tmp_path / "curated_wheel.csv"
    curated.write_text(
        "ticker,name,sector,exchange,source\n"
        + "".join(
            f"FAKE{index},Fake {index},Technology,US,m7\n"
            for index in range(34)
        ),
        encoding="utf-8",
    )
    settings = Settings(
        options_radar=OptionsRadarSettings(
            output_dir=canonical,
            curated_universe_path=curated,
            earnings_calendar_path=tmp_path / "earnings.csv",
            vix_history_path=tmp_path / "vix.csv",
        )
    )
    before = _tree_bytes(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("curated identity rejection touched writer IO")

    monkeypatch.setattr("quant_system.cli.reload_settings", lambda: settings)
    monkeypatch.setattr("quant_system.cli.options_radar_scan_lock", forbidden)
    result = runner.invoke(
        app,
        [
            "options",
            "daily-task",
            "--provider",
            "futu",
            "--top",
            "34",
            "--universe-source",
            "existing",
        ],
    )

    assert result.exit_code == 2
    assert "canonical_options_curated_universe_mismatch" in result.output
    assert _tree_bytes(tmp_path) == before


def test_options_daily_task_sample_rejects_canonical_iv_history_before_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    canonical_output = tmp_path / "canonical-scans"
    canonical_output.mkdir()
    (canonical_output / "existing.jsonl").write_bytes(b"existing\n")
    settings = Settings(
        options_radar=OptionsRadarSettings(output_dir=canonical_output)
    )
    before = _tree_bytes(canonical_output)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sample IV isolation rejection acquired the lock")

    monkeypatch.setattr("quant_system.cli.reload_settings", lambda: settings)
    monkeypatch.setattr("quant_system.cli.options_radar_scan_lock", forbidden)
    result = runner.invoke(
        app,
        [
            "options",
            "daily-task",
            "--provider",
            "sample",
            "--universe-source",
            "sample",
            "--earnings-source",
            "sample",
            "--vix-source",
            "sample",
            "--universe-path",
            str(tmp_path / "dev" / "universe.csv"),
            "--earnings-path",
            str(tmp_path / "dev" / "earnings.csv"),
            "--vix-path",
            str(tmp_path / "dev" / "vix.csv"),
            "--dividend-source",
            "sample",
            "--dividends-path",
            str(tmp_path / "dev" / "dividends.csv"),
            "--output-dir",
            str(tmp_path / "dev" / "scans"),
            "--iv-history-dir",
            str(canonical_output / "iv_history"),
        ],
    )

    assert result.exit_code == 2
    assert "sample_options_paths_required" in result.output
    assert _tree_bytes(canonical_output) == before
    assert not (canonical_output / "options_radar_scan.lock").exists()


def test_options_daily_task_passes_explicit_shared_iv_history_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    shared_history = tmp_path / "shared-iv-history"
    captured: dict[str, Path] = {}

    def fake_run_options_radar(**kwargs):
        captured["iv_history_dir"] = Path(kwargs["iv_history_dir"])
        return OptionsRadarReport(
            run_date="2026-05-03",
            started_at="2026-05-03T00:00:00Z",
            finished_at="2026-05-03T00:01:00Z",
            universe_size=2,
            expected_universe_size=2,
            scanned_tickers=2,
            failed_tickers=[],
            candidates=[],
            provider="sample",
            status="unavailable",
            risk_free_rate=0.0387,
            shortfall_count=20,
            shortfall_reasons={"sample_provider": 1},
        )

    monkeypatch.setattr("quant_system.cli.run_options_radar", fake_run_options_radar)
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
            str(tmp_path / "universe.csv"),
            "--earnings-path",
            str(tmp_path / "earnings.csv"),
            "--vix-path",
            str(tmp_path / "vix.csv"),
            "--dividend-source",
            "sample",
            "--dividends-path",
            str(tmp_path / "dividends.csv"),
            "--iv-history-dir",
            str(shared_history),
            "--output-dir",
            str(tmp_path / "scans"),
        ],
    )

    assert result.exit_code == 3, result.output
    assert captured["iv_history_dir"] == shared_history


def test_options_daily_task_records_partial_scan_as_warning(tmp_path: Path, monkeypatch) -> None:
    universe_path = tmp_path / "inputs" / "universe.csv"
    earnings_path = tmp_path / "inputs" / "earnings.csv"
    vix_path = tmp_path / "inputs" / "vix.csv"
    output_dir = tmp_path / "scans"

    def fake_run_options_radar(**_kwargs):
        return OptionsRadarReport(
            run_date="2026-05-03",
            started_at="2026-05-03T00:00:00+00:00",
            finished_at="2026-05-03T00:01:00+00:00",
            universe_size=2,
            expected_universe_size=2,
            scanned_tickers=1,
            failed_tickers=[("FAIL", "FutuProviderError:rate_limited")],
            candidates=[],
            provider="futu",
            as_of="2026-05-01T20:00:00Z",
            status="empty",
            risk_free_rate=0.0387,
        )

    monkeypatch.setattr("quant_system.cli.run_options_radar", fake_run_options_radar)

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
            "--dividend-source",
            "sample",
            "--dividends-path",
            str(tmp_path / "inputs" / "dividends.csv"),
            "--output-dir",
            str(output_dir),
            "--iv-history-dir",
            str(tmp_path / "iv-history"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "warning=partial_scan failed_tickers=1" in result.output
    status = json.loads((output_dir / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "completed_with_warnings"
    assert status["steps"]["scan"]["failed_tickers"] == 1


def test_options_radar_provider_uses_steady_futu_pacing(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, float] = {}

    class FakeBucket:
        def __init__(self, *, max_tokens, refill_seconds):
            captured["max_tokens"] = max_tokens
            captured["refill_seconds"] = refill_seconds

    monkeypatch.setattr("quant_system.options.daily_task.TokenBucket", FakeBucket)

    from quant_system.cli import _build_options_radar_provider

    settings = SimpleNamespace(
        futu=SimpleNamespace(
            host="127.0.0.1",
            port=11111,
            request_timeout_seconds=15,
            cache_dir=tmp_path,
            use_cache=False,
        ),
        options_radar=SimpleNamespace(
            snapshot_batch_size=200,
            futu_request_pause_seconds=3.1,
        ),
    )

    _build_options_radar_provider(settings, "futu")

    assert captured == {"max_tokens": 1, "refill_seconds": 3.1}


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
                "--dividend-source",
                "sample",
                "--dividends-path",
                str(tmp_path / "inputs" / "dividends.csv"),
                "--output-dir",
                str(output_dir),
                "--iv-history-dir",
                str(output_dir / "iv_history"),
            ],
        )

    assert result.exit_code == 1
    assert "OptionsRadarScanLocked" in result.output
    status = json.loads((output_dir / "daily_task_status.json").read_text(encoding="utf-8"))
    assert status == existing_status


def test_options_daily_task_wide_scan_uses_shared_iv_authority_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    main_output = tmp_path / "main-scans"
    wide_output = tmp_path / "wide-scans"
    shared_history = main_output / "iv_history"
    monkeypatch.setattr(
        "quant_system.cli.run_options_radar",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("scan should not start")),
    )

    with _held_byte_lock(main_output / "options_radar_scan.lock"):
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
                str(tmp_path / "universe.csv"),
                "--earnings-path",
                str(tmp_path / "earnings.csv"),
                "--vix-path",
                str(tmp_path / "vix.csv"),
                "--dividend-source",
                "sample",
                "--dividends-path",
                str(tmp_path / "dividends.csv"),
                "--iv-history-dir",
                str(shared_history),
                "--output-dir",
                str(wide_output),
            ],
        )

    assert result.exit_code == 1
    assert "OptionsRadarScanLocked" in result.output
    assert not wide_output.exists()


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
    assert list(tmp_path.glob("2026-05-03.*.jsonl")) == []


def test_options_daily_scan_futu_dry_run_reports_provider_failure(monkeypatch) -> None:
    def fake_fetch(self, underlying: str):
        raise RuntimeError("OpenD unavailable")

    monkeypatch.setattr(
        "quant_system.options.daily_task.FutuMarketDataProvider.fetch_option_expirations",
        fake_fetch,
    )

    result = runner.invoke(app, ["options", "daily-scan", "--top", "1", "--dry-run"])

    assert result.exit_code == 3
    assert "provider_check=failed" in result.output
