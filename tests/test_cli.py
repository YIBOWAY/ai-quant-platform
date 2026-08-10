import json
from contextlib import contextmanager
from pathlib import Path

import pytest
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


def _file_tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    return {
        str(path.relative_to(root)): (
            ("file", path.read_bytes(), path.stat().st_mtime_ns)
            if path.is_file()
            else ("dir", path.stat().st_mtime_ns)
        )
        for path in sorted(root.rglob("*"))
    }


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


def test_paper_account_show_does_not_create_missing_account(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    result = runner.invoke(app, ["paper", "account-show"])

    assert result.exit_code == 0
    assert "account=default status=missing" in result.output
    assert not (tmp_path / "api_runs" / "paper_account").exists()


@pytest.mark.parametrize(
    "unsafe_account_id",
    ["../escape", "nested/account", "/absolute", "", ".hidden"],
)
def test_paper_account_show_rejects_unsafe_account_id(
    tmp_path,
    monkeypatch,
    unsafe_account_id,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    result = runner.invoke(
        app,
        ["paper", "account-show", "--account", unsafe_account_id],
    )

    assert result.exit_code != 0
    assert "invalid paper account id" in result.output.lower()
    assert not (tmp_path / "api_runs" / "paper_account").exists()


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


def test_paper_strategies_execute_pending_mirrors_account_in_mirror_mode(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.execution import account_repository_factory

    mirror_saves: list[str] = []

    class RecordingPostgresRepository:
        def __init__(
            self,
            *,
            settings,
            account_id: str = "default",
            source: str = "api_dual_write",
        ) -> None:
            self.settings = settings
            self.account_id = account_id
            self.source = source

        def save(self, account, **_kwargs) -> dict[str, int]:
            mirror_saves.append(account.account_id)
            return {
                "accounts": 1,
                "ledger_entries": len(account.ledger),
                "positions": len(account.positions),
                "pending_orders": len(account.pending_orders),
            }

    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "mirror")
    monkeypatch.setattr(
        account_repository_factory,
        "PostgresPaperAccountRepository",
        RecordingPostgresRepository,
    )
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
            "execute-pending",
            "--target-date",
            "2026-06-29",
        ],
    )

    assert result.exit_code == 0
    assert mirror_saves == ["default"]


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


def test_paper_strategies_observations_command_outputs_bounded_json(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve = make_sleeve(config, mode=StrategySleeveMode.ALLOCATED)
    signal = _strategy_signal(sleeve).model_copy(
        update={
            "signal_id": "signal-cli-observed",
            "generated_at": "2026-06-26T20:00:00Z",
        }
    )
    sleeve_storage.save_sleeve(sleeve)
    sleeve_storage.append_signal(signal)
    before = _file_tree_snapshot(tmp_path)

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "observations",
            "--from-date",
            "2026-06-26",
            "--to-date",
            "2026-06-26",
            "--signal-id",
            signal.signal_id,
            "--limit",
            "5",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["read_status"] == "available"
    assert payload["query"] == {
        "from_date": "2026-06-26",
        "to_date": "2026-06-26",
        "signal_id": signal.signal_id,
        "limit": 5,
    }
    assert payload["returned_count"] == 1
    assert payload["truncated"] is False
    assert payload["snapshot_at"].endswith("Z")
    assert payload["observations"][0]["signal"]["signal_id"] == signal.signal_id
    assert _file_tree_snapshot(tmp_path) == before


def test_paper_strategies_observations_configuration_failure_is_json(
    monkeypatch,
) -> None:
    def fail_settings():
        raise ValueError("secret-rich settings failure")

    monkeypatch.setattr("quant_system.cli.load_settings", fail_settings)

    result = runner.invoke(
        app,
        ["paper", "strategies", "observations", "--format", "json"],
    )

    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "error": {
            "code": "strategy_observations_unavailable",
            "message": "strategy observation configuration is unavailable",
        }
    }
    assert "secret-rich" not in result.output


@pytest.mark.parametrize("db_mode", ["file", "mirror", "canonical"])
def test_paper_strategies_observations_is_pure_in_every_account_mode(
    tmp_path,
    monkeypatch,
    db_mode,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", db_mode)
    reload_settings()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("observation CLI crossed a mutation or provider seam")

    monkeypatch.setattr(
        "quant_system.execution.account_repository_factory.PostgresPaperAccountRepository",
        fail_if_called,
    )
    monkeypatch.setattr(
        PaperStrategySleeveStorage,
        "mutation_lock",
        fail_if_called,
    )
    monkeypatch.setattr(
        "quant_system.execution.price_source.PaperPriceSource.__init__",
        fail_if_called,
    )
    before = _file_tree_snapshot(tmp_path)

    result = runner.invoke(
        app,
        ["paper", "strategies", "observations", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["read_status"] == "empty"
    assert _file_tree_snapshot(tmp_path) == before


def test_paper_strategies_observations_returns_degraded_json_without_repair(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = make_sleeve(make_config(), mode=StrategySleeveMode.ALLOCATED)
    storage.save_sleeve(sleeve)
    signals_path = storage.sleeve_signals_path(sleeve.sleeve_id)
    signals_path.write_bytes(b"{not-json\n")
    before = _file_tree_snapshot(tmp_path)

    result = runner.invoke(
        app,
        ["paper", "strategies", "observations", "--format", "json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["read_status"] == "degraded"
    assert payload["errors"][0]["code"] == "strategy_observation_data_unreadable"
    assert _file_tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("output_format", ["text", "json"])
@pytest.mark.parametrize("db_mode", ["file", "mirror", "canonical"])
def test_paper_strategies_ops_status_is_observational(
    tmp_path,
    monkeypatch,
    output_format,
    db_mode,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", db_mode)
    reload_settings()

    def fail_postgres_repository(*_args, **_kwargs):
        raise AssertionError("ops-status CLI opened the account repository")

    monkeypatch.setattr(
        "quant_system.execution.account_repository_factory.PostgresPaperAccountRepository",
        fail_postgres_repository,
    )
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    pending_sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        PaperAccount.open_new(initial_cash=100_000.0),
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    pending_path = sleeve_storage.save_pending_sleeve(pending_sleeve)
    corrupt_journal = sleeve_storage.execution_journal_pending_path(
        pending_sleeve.sleeve_id,
        "exec-corrupt",
    )
    corrupt_journal.parent.mkdir(parents=True, exist_ok=True)
    corrupt_journal.write_bytes(b"{not-json")
    before = _file_tree_snapshot(tmp_path)

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "ops-status",
            "--target-date",
            "2026-06-29",
            "--format",
            output_format,
        ],
    )

    assert result.exit_code == 0
    if output_format == "json":
        payload = json.loads(result.output)
        assert payload["pending_sleeve_count"] == 1
        assert payload["pending_journal_count"] == 1
    else:
        assert "pending_sleeves=1" in result.output
        assert "pending_journals=1" in result.output
    assert pending_path.exists()
    assert corrupt_journal.read_bytes() == b"{not-json"
    assert _file_tree_snapshot(tmp_path) == before
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "file")
    reload_settings()


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_paper_strategies_ops_status_does_not_materialize_missing_storage(
    tmp_path,
    monkeypatch,
    output_format,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    result = runner.invoke(
        app,
        ["paper", "strategies", "ops-status", "--format", output_format],
    )

    assert result.exit_code == 0
    assert not (tmp_path / "api_runs" / "paper_account").exists()
    assert not (tmp_path / "api_runs" / "paper_strategy_sleeves").exists()


def test_paper_strategies_ops_status_rejects_unknown_execution_window(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    result = runner.invoke(
        app,
        [
            "paper",
            "strategies",
            "ops-status",
            "--window",
            "typo",
            "--format",
            "json",
        ],
    )

    assert result.exit_code != 0
    assert "next_open" in result.output


def test_paper_strategies_recover_pending_is_an_explicit_recovery_only_command(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()
    account_storage = PaperAccountStorage(tmp_path / "api_runs")
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    account = PaperAccount.open_new(initial_cash=100_000.0)
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    pending_sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    account_storage.save(account)
    pending_path = sleeve_storage.save_pending_sleeve(pending_sleeve)
    signal = _strategy_signal(pending_sleeve)
    sleeve_storage.append_signal(signal)
    pending_execution = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=pending_sleeve,
        signal=signal,
        target_date="2026-06-29",
    )
    corrupt_journal = sleeve_storage.execution_journal_pending_path(
        pending_sleeve.sleeve_id,
        "exec-corrupt",
    )
    corrupt_journal.parent.mkdir(parents=True, exist_ok=True)
    corrupt_journal.write_bytes(b"{not-json")
    monkeypatch.setattr(
        "quant_system.execution.paper_strategy_sleeve_storage.log.warning",
        lambda *_args, **_kwargs: None,
    )

    result = runner.invoke(
        app,
        ["paper", "strategies", "recover-pending", "--format", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "corrupt_journal_count": 1,
        "discarded_sleeve_count": 0,
        "reconciled_sleeve_count": 1,
        "recovered_execution_count": 0,
        "remaining_pending_journal_count": 0,
        "remaining_pending_sleeve_count": 0,
    }
    assert not pending_path.exists()
    assert sleeve_storage.sleeve_path(pending_sleeve.sleeve_id).exists()
    executions = sleeve_storage.load_executions(pending_sleeve.sleeve_id)
    assert executions[0].execution_id == pending_execution.execution_id
    assert executions[0].status == "pending"
    preserved_corrupt = list(corrupt_journal.parent.glob("exec-corrupt.corrupt-*.json"))
    assert len(preserved_corrupt) == 1
    assert preserved_corrupt[0].read_bytes() == b"{not-json"

    status = runner.invoke(
        app,
        ["paper", "strategies", "ops-status", "--format", "json"],
    )
    assert status.exit_code == 0
    assert json.loads(status.output)["corrupt_journal_count"] == 1


def test_paper_strategies_recover_pending_fails_closed_for_missing_canonical_account(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "canonical")
    reload_settings()

    class MissingCanonicalRepository:
        def __init__(self, *, account_id, **_kwargs) -> None:
            self.account_id = account_id

        @contextmanager
        def mutation_lock(self, **_kwargs):
            yield

        def load(self):
            return None

    monkeypatch.setattr(
        "quant_system.execution.account_repository_factory.PostgresPaperAccountRepository",
        MissingCanonicalRepository,
    )
    sleeve_storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    pending_sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        PaperAccount.open_new(initial_cash=100_000.0),
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=25_000.0,
    )
    pending_path = sleeve_storage.save_pending_sleeve(pending_sleeve)
    before = pending_path.read_bytes()

    result = runner.invoke(
        app,
        ["paper", "strategies", "recover-pending", "--format", "json"],
    )

    assert result.exit_code != 0
    assert "paper_account_bootstrap_required" in result.output
    assert pending_path.read_bytes() == before
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "file")
    reload_settings()


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
    monkeypatch.setattr(
        "quant_system.execution.account_snapshot._resolve_futu_account_quotes",
        lambda account, *, settings: {
            symbol: fake_get_price(None, symbol)
            for symbol in account.positions
            if symbol in prices
        },
    )
