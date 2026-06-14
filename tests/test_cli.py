from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.config.settings import reload_settings

runner = CliRunner()


def test_cli_help_runs() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "config" in result.output
    assert "doctor" in result.output


def test_config_show_prints_safe_defaults() -> None:
    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert '"dry_run": true' in result.output
    assert '"paper_trading": true' in result.output
    assert '"live_trading_enabled": false' in result.output
    assert '"kill_switch": true' in result.output


def test_config_show_masks_live_trading_confirmation() -> None:
    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    # The raw confirmation phrase must never appear in CLI output.
    assert "I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING" not in result.output
    assert '"manual_live_trading_confirmation": "<unset>"' in result.output


def test_doctor_reports_phase_0_status() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Phase 0 foundation is available" in result.output
    assert "live trading disabled" in result.output


def test_doctor_writes_runtime_log_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert (tmp_path / "_runtime" / "logs" / "backend.jsonl").exists()


def test_serve_writes_runtime_log_file_without_starting_server(
    tmp_path,
    monkeypatch,
) -> None:
    calls = []

    def fake_run(*args, **kwargs) -> None:
        calls.append((args, kwargs))

    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("uvicorn.run", fake_run)
    reload_settings()

    result = runner.invoke(app, ["serve", "--host", "127.0.0.1", "--port", "8765"])

    assert result.exit_code == 0
    assert calls
    assert calls[0][1]["host"] == "127.0.0.1"
    assert calls[0][1]["port"] == 8765
    assert (tmp_path / "_runtime" / "logs" / "backend.jsonl").exists()
