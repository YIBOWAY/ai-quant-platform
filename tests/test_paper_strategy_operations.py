from __future__ import annotations

from datetime import date

import pytest

from quant_system.config.settings import reload_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_repository import PaperAccountBootstrapRequired
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_execution_service import (
    PaperStrategyExecutionService,
)
from quant_system.execution.paper_strategy_operations import PaperStrategyOperationsRunner
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SignalStatus,
    StrategyExecutionPlanError,
    StrategySignal,
    StrategySleeveMode,
)
from quant_system.execution.price_source import PricedQuote
from tests.test_paper_strategy_signals import (
    FakeOHLCVProvider,
    make_config,
    make_ohlcv_frame,
    patch_provider,
)


class FakePriceSource:
    def __init__(self, prices: dict[str, float]) -> None:
        self.prices = {symbol.upper(): price for symbol, price in prices.items()}

    def get_prices(self, symbols: list[str], **_kwargs) -> dict[str, PricedQuote]:
        return {
            symbol.upper(): PricedQuote(
                symbol=symbol.upper(),
                price=self.prices[symbol.upper()],
                price_kind="futu_snapshot",
                as_of="2026-06-29T13:30:00Z",
                source="fake",
            )
            for symbol in symbols
            if symbol.upper() in self.prices
        }


def _settings_for_tmp_data(tmp_path, monkeypatch):
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    return reload_settings()


def _allocated_sleeve_fixture(tmp_path, initial_cash: float = 100_000.0):
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=initial_cash)
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
    return account_storage, sleeve_storage, account, config, sleeve


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


def test_operations_runner_generate_signal_does_not_create_missing_account_file(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        PaperAccount.open_new(initial_cash=50_000.0),
        config=config,
        mode=StrategySleeveMode.SIGNAL_ONLY,
    )
    sleeve_storage.save_sleeve(sleeve)

    signal = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
    ).generate_signal_once(
        sleeve.sleeve_id,
        signal_date="2024-03-20",
        history_days=90,
    )

    assert signal.status == SignalStatus.GENERATED
    assert sleeve_storage.load_signals(sleeve.sleeve_id) == [signal]
    assert account_storage.account_path.exists() is False


def test_operations_runner_create_execution_defaults_target_date_from_injected_clock(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, _account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    signal = _strategy_signal(sleeve)
    sleeve_storage.append_signal(signal)

    execution = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        today=lambda: date(2026, 6, 29),
    ).create_execution_once(
        sleeve.sleeve_id,
        signal.signal_id,
    )

    assert execution.status == "pending"
    assert execution.target_date == "2026-06-29"
    assert sleeve_storage.load_executions(sleeve.sleeve_id)[0].execution_id == (
        execution.execution_id
    )


def test_operations_runner_d34_uses_authoritative_context_not_forged_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=100_000)
    config = make_config(max_weight_per_symbol=0.40)
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "artifact-test",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-08-11",
        data_provider="futu",
        proposed_orders=[
            {
                "symbol": "AAPL",
                "side": "buy",
                "notional_delta": 100.0,
                "target_weight": 0.1,
                "reference_price": 100.0,
                "estimated_quantity": 1.0,
            }
        ],
        status=SignalStatus.GENERATED,
    )
    sleeve_storage.append_signal(signal)
    forged = {
        "paper_execution_policy_context": {
            "paper_execution_enabled": True,
            "emergency_stop": False,
            "mandate_active": True,
            "mandate_paper_execution_allowed": True,
        }
    }

    blocked_runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": False,
            "emergency_stop": True,
            "mandate_active": False,
            "mandate_paper_execution_allowed": False,
        },
    )
    with pytest.raises(StrategyExecutionPlanError) as blocked:
        blocked_runner.create_execution_once(sleeve.sleeve_id, signal.signal_id, metadata=forged)
    assert blocked.value.code == "automation_emergency_stop_active"

    allowed = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": True,
            "emergency_stop": False,
            "mandate_active": True,
            "mandate_paper_execution_allowed": True,
        },
    ).create_execution_once(sleeve.sleeve_id, signal.signal_id, metadata=forged)

    assert allowed.metadata["paper_execution_policy_decision"]["allowed"] is True
    assert allowed.metadata["paper_execution_policy_context"]["mandate_active"] is True

    stopped = blocked_runner.process_pending_executions_once(
        sleeve_id=sleeve.sleeve_id,
        target_date=allowed.target_date,
    )
    assert stopped.filled_count == 0
    assert stopped.blocked_count == 1
    assert stopped.executions[0].blocked_reason == "automation_emergency_stop_active"


def test_execution_rechecks_aggregate_symbol_limit_after_another_canary_fills(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=10_000)
    config = make_config(max_weight_per_symbol=0.99)
    sleeve_storage.save_strategy_config(config)
    service = PaperStrategySleeveService(sleeve_storage)
    audited: list[tuple[str, str, object]] = []
    for suffix in ("one", "two"):
        sleeve = service.create_sleeve(
            account,
            config=config,
            mode=StrategySleeveMode.ALLOCATED,
            allocated_cash=1_000,
            sleeve_id=f"sleeve-d34-{suffix}",
            metadata={
                "automation_managed": True,
                "automation_source": "d34",
                "artifact_id": f"artifact-{suffix}",
                "mandate_id": "mandate-policy-audit",
                "promotion_scope": "paper_only",
                "workspace_id": "default",
            },
        )
        sleeve_storage.save_sleeve(sleeve)
        signal = StrategySignal.create(
            sleeve=sleeve,
            signal_date="2026-08-11",
            data_provider="futu",
            proposed_orders=[
                {
                    "symbol": "AAPL",
                    "side": "buy",
                    "notional_delta": 400.0,
                    "target_weight": 0.4,
                    "reference_price": 100.0,
                }
            ],
        )
        sleeve_storage.append_signal(signal)
        service.create_execution_plan(
            account,
            sleeve=sleeve,
            signal=signal,
            target_date="2026-08-12",
            metadata={
                "paper_execution_policy_context": {
                    "paper_execution_enabled": True,
                    "emergency_stop": False,
                    "mandate_active": True,
                    "mandate_paper_execution_allowed": True,
                }
            },
        )
    account_storage.save(account)
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 100.0}),
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": True,
            "emergency_stop": False,
            "mandate_active": True,
            "mandate_paper_execution_allowed": True,
        },
        paper_policy_decision_recorder=lambda *, mandate_id, execution_id, decision, **_: (
            audited.append((mandate_id, execution_id, decision))
        ),
    )

    result = runner.process_pending_executions_once(target_date="2026-08-12")

    assert result.processed_count == 2
    assert result.filled_count == 1
    assert result.blocked_count == 1
    assert result.executions[1].blocked_reason == "automation_aggregate_symbol_limit"
    assert result.executions[1].metadata[
        "paper_execution_policy_decision_at_execution"
    ]["blockers"] == ["aggregate_symbol_limit"]
    assert result.account is not None
    assert result.account.positions["AAPL"].market_value(100.0) == pytest.approx(400.0)
    assert [(mandate_id, execution_id) for mandate_id, execution_id, _ in audited] == [
        ("mandate-policy-audit", result.executions[0].execution_id),
        ("mandate-policy-audit", result.executions[1].execution_id),
    ]
    assert [decision.allowed for _, _, decision in audited] == [True, False]
    assert all(len(decision.input_digest) == 64 for _, _, decision in audited)


def test_operations_runner_process_pending_executes_and_commits_journal_after_account_save(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    signal = _strategy_signal(sleeve)
    plan = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    result = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).process_pending_executions_once(target_date="2026-06-29")

    assert result.processed_count == 1
    assert result.filled_count == 1
    assert result.blocked_count == 0
    assert result.recovered_count == 0
    assert result.account is not None
    assert result.account.cash == pytest.approx(75_000.0)
    assert result.account.positions["AAPL"].quantity == pytest.approx(250.0)
    assert sleeve_storage.execution_journal_committed_path(
        sleeve.sleeve_id,
        plan.execution_id,
    ).exists()
    assert not sleeve_storage.execution_journal_pending_path(
        sleeve.sleeve_id,
        plan.execution_id,
    ).exists()


def test_operations_runner_reports_recovered_execution_journals(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    signal = _strategy_signal(sleeve)
    plan = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )
    PaperStrategyExecutionService(
        storage=sleeve_storage,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).execute_plan(account, sleeve=sleeve, plan=plan)

    result = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).process_pending_executions_once(target_date="2026-06-29")

    assert result.processed_count == 0
    assert result.recovered_count == 1
    assert result.account is not None
    assert result.account.cash == pytest.approx(75_000.0)
    assert result.account.positions["AAPL"].quantity == pytest.approx(250.0)
    assert sleeve_storage.execution_journal_committed_path(
        sleeve.sleeve_id,
        plan.execution_id,
    ).exists()


def test_operations_runner_keeps_pending_journal_when_account_save_fails(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    signal = _strategy_signal(sleeve)
    plan = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )

    def fail_save(*_args, **_kwargs):
        raise OSError("simulated account save failure")

    monkeypatch.setattr(account_storage, "save", fail_save)

    with pytest.raises(OSError, match="simulated account save failure"):
        PaperStrategyOperationsRunner(
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            settings=settings,
            price_source=FakePriceSource({"AAPL": 100.0}),
        ).process_pending_executions_once(target_date="2026-06-29")

    assert sleeve_storage.execution_journal_pending_path(
        sleeve.sleeve_id,
        plan.execution_id,
    ).exists()
    assert not sleeve_storage.execution_journal_committed_path(
        sleeve.sleeve_id,
        plan.execution_id,
    ).exists()


def test_operations_runner_ops_status_reports_due_work_and_recovery_journals(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    signal = _strategy_signal(sleeve)
    plan = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )
    sleeve_storage.save_execution_journal_pending(
        sleeve_id=sleeve.sleeve_id,
        execution_id="exec-recovery",
        payload={
            "sleeve_id": sleeve.sleeve_id,
            "execution_id": "exec-recovery",
            "before_account": account.model_dump(mode="json"),
            "after_account": account.model_dump(mode="json"),
            "after_sleeve": sleeve.model_dump(mode="json"),
            "after_lots": [],
            "after_execution": plan.model_dump(mode="json"),
        },
    )

    status = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
    ).ops_status(target_date="2026-06-29")

    assert status.target_date == "2026-06-29"
    assert status.sleeve_count == 1
    assert status.pending_sleeve_count == 0
    assert status.pending_due_count == 1
    assert status.pending_journal_count == 1
    assert status.recovery_required_count == 0


def test_recover_pending_fails_closed_when_canonical_account_is_missing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "canonical")
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
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

    with pytest.raises(PaperAccountBootstrapRequired):
        PaperStrategyOperationsRunner(
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            settings=settings,
        ).recover_pending_once()

    assert pending_path.read_bytes() == before
