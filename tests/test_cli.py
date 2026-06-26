from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.config.settings import reload_settings
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import StrategySleeveMode
from tests.test_paper_strategy_signals import (
    FakeOHLCVProvider,
    make_config,
    make_ohlcv_frame,
    make_sleeve,
    patch_provider,
)

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


def test_doctor_reports_platform_health_summary() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Quant System local health" in result.output
    assert "safety.live_trading_enabled=false" in result.output
    assert "data.default_provider=" in result.output
    assert "database.enabled=" in result.output
    assert "runtime.log=" in result.output
    assert "Phase 0 foundation is available" not in result.output


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


def test_paper_strategies_generate_signal_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve = make_sleeve(config, mode=StrategySleeveMode.SIGNAL_ONLY)
    storage.save_strategy_config(config)
    storage.save_sleeve(sleeve)

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "generate-signal",
            "--sleeve",
            sleeve.sleeve_id,
            "--signal-date",
            "2024-03-20",
        ],
    )

    assert result.exit_code == 0
    assert "status=generated" in result.output
    assert f"sleeve={sleeve.sleeve_id}" in result.output
    assert storage.load_signals(sleeve.sleeve_id)
    assert PaperAccountStorage(tmp_path / "api_runs").account_path.exists() is False
