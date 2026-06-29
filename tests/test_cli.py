import json

from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.config.settings import reload_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SignalStatus,
    StrategySignal,
    StrategySleeveMode,
)
from quant_system.execution.price_source import PricedQuote
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


def test_paper_strategies_create_execution_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    account = PaperAccount.open_new(initial_cash=100_000.0)
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account_storage = PaperAccountStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    signal = _strategy_signal(sleeve)
    sleeve_storage.append_signal(signal)

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "create-execution",
            "--sleeve",
            sleeve.sleeve_id,
            "--signal",
            signal.signal_id,
            "--target-date",
            "2026-06-29",
        ],
    )

    assert result.exit_code == 0
    assert "status=pending" in result.output
    assert f"sleeve={sleeve.sleeve_id}" in result.output
    assert sleeve_storage.load_executions(sleeve.sleeve_id)[0].signal_id == signal.signal_id


def test_paper_strategies_execute_pending_command(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    _stub_paper_prices(monkeypatch, {"AAPL": 100.0})
    account = PaperAccount.open_new(initial_cash=100_000.0)
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account_storage = PaperAccountStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    sleeve_service = PaperStrategySleeveService(sleeve_storage)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    signal = _strategy_signal(sleeve)
    plan = sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "execute-pending",
            "--target-date",
            "2026-06-29",
        ],
    )

    assert result.exit_code == 0
    assert "filled=1" in result.output
    assert plan.execution_id in result.output
    reloaded_account = account_storage.load()
    assert reloaded_account is not None
    assert reloaded_account.cash == 75_000.0
    assert reloaded_account.positions["AAPL"].quantity == 250.0
    assert sleeve_storage.load_executions(sleeve.sleeve_id)[0].status == "filled"


def test_paper_strategies_ops_status_command_outputs_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    account = PaperAccount.open_new(initial_cash=100_000.0)
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account_storage = PaperAccountStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    sleeve_service = PaperStrategySleeveService(sleeve_storage)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    signal = _strategy_signal(sleeve)
    sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "ops-status",
            "--target-date",
            "2026-06-29",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["target_date"] == "2026-06-29"
    assert payload["sleeve_count"] == 1
    assert payload["pending_due_count"] == 1
    assert payload["pending_journal_count"] == 0


def test_paper_strategies_generate_due_signals_command_outputs_json(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    account = PaperAccount.open_new(initial_cash=100_000.0)
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account_storage = PaperAccountStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "generate-due-signals",
            "--date",
            "2024-03-20",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["signal_date"] == "2024-03-20"
    assert payload["generated_count"] == 1
    assert payload["skipped_count"] == 0
    assert len(sleeve_storage.load_signals(sleeve.sleeve_id)) == 1


def test_paper_strategies_execute_due_command_processes_due_plan(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    _stub_paper_prices(monkeypatch, {"AAPL": 100.0})
    account = PaperAccount.open_new(initial_cash=100_000.0)
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account_storage = PaperAccountStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    sleeve_service = PaperStrategySleeveService(sleeve_storage)
    sleeve = sleeve_service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    signal = _strategy_signal(sleeve)
    sleeve_service.create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "execute-due",
            "--target-date",
            "2026-06-29",
        ],
    )

    assert result.exit_code == 0
    assert "filled=1" in result.output
    reloaded_account = account_storage.load()
    assert reloaded_account is not None
    assert reloaded_account.positions["AAPL"].quantity == 250.0


def _strategy_signal(sleeve) -> StrategySignal:
    return StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-06-26",
        data_provider="futu",
        target_weights={"AAPL": 1.0},
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "notional_delta": 25_000.0,
                "target_weight": 1.0,
                "reference_price": 100.0,
                "estimated_quantity": 250.0,
            }
        ],
        status=SignalStatus.GENERATED,
    )


def _stub_paper_prices(monkeypatch, prices: dict[str, float]) -> None:
    def fake_get_price(self, symbol, **_kwargs):  # noqa: ARG001
        symbol = symbol.upper()
        return PricedQuote(
            symbol=symbol,
            price=prices[symbol],
            price_kind="futu_snapshot",
            as_of="2026-06-29T13:30:00Z",
            source="stub",
        )

    def fake_get_prices(self, symbols, **_kwargs):  # noqa: ARG001
        return {
            symbol.upper(): fake_get_price(self, symbol)
            for symbol in symbols
            if symbol.upper() in prices
        }

    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_price",
        fake_get_price,
    )
    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.get_prices",
        fake_get_prices,
    )
