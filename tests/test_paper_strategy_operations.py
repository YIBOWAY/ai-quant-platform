from __future__ import annotations

import multiprocessing
import time
from datetime import date

import pytest

from quant_system.config.settings import reload_settings
from quant_system.execution.account import AccountPosition, PaperAccount
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
    StrategyExecutionStatus,
    StrategySignal,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.execution.price_source import PricedQuote, PriceUnavailableError
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


def test_d34_authoritative_policy_executes_on_frozen_shared_paper_account(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=100_000)
    account.kill_switch = True
    config = make_config(max_weight_per_symbol=0.99)
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "artifact-frozen-account",
            "mandate_id": "mandate-frozen-account",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    audited: list[object] = []
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 179.0}),
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": True,
            "emergency_stop": False,
            "mandate_active": True,
            "mandate_paper_execution_allowed": True,
        },
        paper_policy_decision_recorder=lambda **values: audited.append(values),
    )

    signal = runner.generate_signal_once(
        sleeve.sleeve_id,
        signal_date="2024-03-20",
        history_days=90,
    )
    plan = runner.create_execution_once(
        sleeve.sleeve_id,
        signal.signal_id,
        target_date="2024-03-21",
    )
    result = runner.process_pending_executions_once(
        sleeve_id=sleeve.sleeve_id,
        target_date="2024-03-21",
    )

    assert signal.execution_blocked_reason is None
    assert signal.proposed_orders[0]["symbol"] == "AAPL"
    assert plan.metadata["paper_execution_policy_decision"]["allowed"] is True
    assert result.filled_count == 1
    assert result.blocked_count == 0
    assert result.account is not None
    assert result.account.kill_switch is True
    assert result.account.positions["AAPL"].quantity > 0
    assert len(audited) == 1


def test_hung_observation_fills_frozen_account_without_mandate(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=100_000)
    account.kill_switch = True
    config = make_config(max_weight_per_symbol=0.99)
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "artifact-hung",
            "mandate_id": "mandate-expired",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
            # Hung observation is digest-bound since the fossil quarantine:
            # only officially hung sleeves fill while the account is frozen.
            "candidate_code_digest": "a" * 64,
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 179.0}),
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": False,
            "emergency_stop": False,
            "mandate_active": False,
            "mandate_paper_execution_allowed": False,
        },
    )

    signal = runner.generate_signal_once(
        sleeve.sleeve_id,
        signal_date="2024-03-20",
        history_days=90,
    )
    plan = runner.create_execution_once(
        sleeve.sleeve_id,
        signal.signal_id,
        target_date="2024-03-21",
    )
    result = runner.process_pending_executions_once(
        sleeve_id=sleeve.sleeve_id,
        target_date="2024-03-21",
    )

    assert signal.execution_blocked_reason is None
    assert result.filled_count == 1
    assert result.blocked_count == 0
    assert result.account is not None
    assert result.account.kill_switch is True
    assert result.account.positions["AAPL"].quantity > 0
    assert plan.metadata["paper_execution_policy_decision"]["input_document"][
        "hung_observation"
    ] is True


def test_hung_observation_stays_frozen_when_live_is_on(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("QS_LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv(
        "QS_MANUAL_LIVE_TRADING_CONFIRMATION",
        "I_UNDERSTAND_THIS_ENABLES_LIVE_TRADING",
    )
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=100_000)
    account.kill_switch = True
    config = make_config(max_weight_per_symbol=0.99)
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "artifact-live-block",
            "mandate_id": "mandate-live-block",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 179.0}),
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": False,
            "emergency_stop": False,
            "mandate_active": False,
            "mandate_paper_execution_allowed": False,
        },
    )

    signal = runner.generate_signal_once(
        sleeve.sleeve_id,
        signal_date="2024-03-20",
        history_days=90,
    )

    assert signal.execution_blocked_reason == "account_frozen"


def test_hung_observation_stays_frozen_when_authority_is_unknown(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=100_000)
    account.kill_switch = True
    config = make_config(max_weight_per_symbol=0.99)
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "artifact-authority-unknown",
            "mandate_id": "mandate-authority-unknown",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": False,
            "emergency_stop": False,
            "authority_available": False,
            "mandate_active": False,
            "mandate_paper_execution_allowed": False,
            "blockers": ["d34_authority_unavailable"],
        },
    )

    signal = runner.generate_signal_once(
        sleeve.sleeve_id,
        signal_date="2024-03-20",
        history_days=90,
    )

    assert signal.execution_blocked_reason == "account_frozen"


def test_d34_frozen_account_override_requires_current_authoritative_context(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    api_runs_dir = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs_dir)
    sleeve_storage = PaperStrategySleeveStorage(api_runs_dir)
    account = PaperAccount.open_new(initial_cash=100_000)
    account.kill_switch = True
    config = make_config(max_weight_per_symbol=0.99)
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "artifact-no-authority",
            "mandate_id": "mandate-no-authority",
            "promotion_scope": "paper_only",
            "workspace_id": "default",
        },
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        paper_execution_context_provider=lambda _sleeve: {
            "paper_execution_enabled": False,
            "emergency_stop": True,
            "mandate_active": True,
            "mandate_paper_execution_allowed": True,
        },
    )

    signal = runner.generate_signal_once(
        sleeve.sleeve_id,
        signal_date="2024-03-20",
        history_days=90,
    )

    assert signal.execution_blocked_reason == "account_frozen"
    assert signal.proposed_orders == []
    with pytest.raises(StrategyExecutionPlanError) as blocked:
        runner.create_execution_once(
            sleeve.sleeve_id,
            signal.signal_id,
            metadata={
                "paper_execution_policy_context": {
                    "paper_execution_enabled": True,
                    "emergency_stop": False,
                    "mandate_active": True,
                    "mandate_paper_execution_allowed": True,
                }
            },
        )
    assert blocked.value.code == "account_frozen"


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
    # R3 parity: buy 250 @100 slips to 100.05 + 1bp commission on 25,012.50
    assert result.account.cash == pytest.approx(100_000.0 - 250.0 * 100.05 * (1 + 1.0 / 10_000))
    assert result.account.positions["AAPL"].quantity == pytest.approx(250.0)
    assert sleeve_storage.execution_journal_committed_path(
        sleeve.sleeve_id,
        plan.execution_id,
    ).exists()
    assert not sleeve_storage.execution_journal_pending_path(
        sleeve.sleeve_id,
        plan.execution_id,
    ).exists()


def test_empty_execution_poll_does_not_reprice_or_save_unrelated_holdings(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    account.positions["MU"] = AccountPosition(symbol="MU", quantity=100, avg_cost=872.14)
    account_storage.save(account)
    before = account_storage.account_path.read_bytes()

    class UnavailablePrices:
        def get_prices(self, symbols, **_kwargs):
            raise PriceUnavailableError(f"no price available for {symbols[0]}")

    result = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=UnavailablePrices(),
    ).process_pending_executions_once(sleeve_id=sleeve.sleeve_id, target_date="2026-09-03")

    assert result.processed_count == result.filled_count == result.blocked_count == 0
    assert result.recovered_count == 0
    assert account_storage.account_path.read_bytes() == before


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
    # R3 parity: buy 250 @100 slips to 100.05 plus 1bp commission on 25,012.50
    assert result.account.cash == pytest.approx(
        100_000.0 - 250.0 * 100.05 * (1 + 1.0 / 10_000)
    )
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


def test_ops_status_counts_blocked_executions_only_for_requested_target_date(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    plan = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=sleeve,
        signal=_strategy_signal(sleeve),
        target_date="2026-06-29",
    )
    plan.status = StrategyExecutionStatus.BLOCKED
    plan.blocked_reason = "insufficient_account_source_quantity"
    sleeve_storage.save_executions(sleeve.sleeve_id, [plan])

    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
    )

    assert runner.ops_status(target_date="2026-06-29").blocked_count == 1
    assert runner.ops_status(target_date="2026-06-30").blocked_count == 0


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


def test_process_pending_marks_expired_pending_plan_missed_window_without_fills(
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
    account_before = account.model_dump(mode="json")

    result = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).process_pending_executions_once(target_date="2026-06-30")

    assert result.missed_window_count == 1
    assert result.processed_count == 0
    assert result.filled_count == 0
    assert result.blocked_count == 0
    reloaded = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status == StrategyExecutionStatus.MISSED_WINDOW
    assert reloaded.fills == []
    record = reloaded.metadata["missed_window"]
    assert record["previous_status"] == "pending"
    assert record["previous_blocked_reason"] is None
    assert record["target_date"] == "2026-06-29"
    assert record["processing_date"] == "2026-06-30"
    assert account.model_dump(mode="json") == account_before
    assert not sleeve_storage.execution_journal_pending_path(
        sleeve.sleeve_id, plan.execution_id
    ).exists()
    assert not sleeve_storage.execution_journal_committed_path(
        sleeve.sleeve_id, plan.execution_id
    ).exists()


def test_price_blocked_plan_retries_then_expires_to_missed_window_across_runs(
    tmp_path,
    monkeypatch,
) -> None:
    """Sealed outage: bounded retries, block on day one, missed_window on day two."""
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    signal = _strategy_signal(sleeve)
    PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )
    account_before = account.model_dump(mode="json")
    sleeps: list[float] = []
    calls = {"count": 0}

    class SealedOutage:
        def get_prices(self, symbols, **_kwargs):
            calls["count"] += 1
            raise PriceUnavailableError("sealed outage: no real price")

    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=SealedOutage(),
        price_retry_backoff_seconds=30.0,
        sleep_func=sleeps.append,
    )

    day_one = runner.process_pending_executions_once(target_date="2026-06-29")

    assert day_one.processed_count == 1
    assert day_one.filled_count == 0
    assert day_one.blocked_count == 1
    assert day_one.missed_window_count == 0
    assert calls["count"] == 3
    assert sleeps == [30.0, 30.0]
    blocked = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert blocked.status == StrategyExecutionStatus.BLOCKED
    assert blocked.blocked_reason == "price_unavailable"
    assert len(blocked.metadata["price_unavailable_retry"]["attempts"]) == 2

    day_two = runner.process_pending_executions_once(target_date="2026-06-30")

    assert day_two.processed_count == 0
    assert day_two.missed_window_count == 1
    assert calls["count"] == 3  # no late fill was ever attempted again
    reloaded = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status == StrategyExecutionStatus.MISSED_WINDOW
    assert reloaded.blocked_reason == "price_unavailable"
    assert reloaded.fills == []
    record = reloaded.metadata["missed_window"]
    assert record["previous_status"] == "blocked"
    assert record["previous_blocked_reason"] == "price_unavailable"
    assert account.model_dump(mode="json") == account_before
    assert account.positions == {}


def test_expired_non_price_blocked_plan_stays_blocked(
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
    plan.status = StrategyExecutionStatus.BLOCKED
    plan.blocked_reason = "insufficient_sleeve_cash"
    sleeve_storage.save_executions(sleeve.sleeve_id, [plan])

    result = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).process_pending_executions_once(target_date="2026-06-30")

    assert result.missed_window_count == 0
    reloaded = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status == StrategyExecutionStatus.BLOCKED
    assert reloaded.blocked_reason == "insufficient_sleeve_cash"
    assert "missed_window" not in reloaded.metadata


def test_expired_plan_in_unscanned_sleeve_is_untouched(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    other = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=_config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000.0,
    )
    sleeve_storage.save_sleeve(other)
    other_signal = _strategy_signal(other)
    other_plan = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=other,
        signal=other_signal,
        target_date="2026-06-29",
    )

    result = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=FakePriceSource({"AAPL": 100.0}),
    ).process_pending_executions_once(
        sleeve_id=sleeve.sleeve_id,
        target_date="2026-06-30",
    )

    assert result.missed_window_count == 0
    reloaded_other = sleeve_storage.load_executions(other.sleeve_id)[0]
    assert reloaded_other.execution_id == other_plan.execution_id
    assert reloaded_other.status == StrategyExecutionStatus.PENDING


def _lock_probe_child(account_dir: str, result_queue) -> None:
    """Acquire the account mutation lock in a separate process and mutate.

    Module-level so a ``spawn`` child can pickle it; the timing is measured
    from process start so it is comparable with the parent's lock timeout.
    """
    from pathlib import Path

    from quant_system.execution.account_storage import PaperAccountStorage

    storage = PaperAccountStorage(Path(account_dir))
    started = time.monotonic()
    try:
        with storage.mutation_lock(timeout_seconds=2.0):
            account = storage.load()
            storage.save(account)
            acquired_at = time.monotonic()
        result_queue.put(("ok", acquired_at - started, time.monotonic() - started))
    except TimeoutError:
        finished = time.monotonic()
        result_queue.put(("timeout", finished - started, finished - started))


def _pending_plan_fixture(tmp_path, monkeypatch):
    settings = _settings_for_tmp_data(tmp_path, monkeypatch)
    account_storage, sleeve_storage, account, _config, sleeve = _allocated_sleeve_fixture(tmp_path)
    signal = _strategy_signal(sleeve)
    PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account,
        sleeve=sleeve,
        signal=signal,
        target_date="2026-06-29",
    )
    return settings, account_storage, sleeve_storage, account, sleeve


class _SealedOutage:
    """Price source that always fails, counting calls."""

    def __init__(self) -> None:
        self.calls = 0

    def get_prices(self, symbols, **_kwargs):
        self.calls += 1
        raise PriceUnavailableError("sealed outage: no real price")


def test_backoff_sleep_does_not_hold_mutation_lock(tmp_path, monkeypatch) -> None:
    """The bounded backoff must run without either mutation lock held."""
    settings, account_storage, sleeve_storage, _account, sleeve = _pending_plan_fixture(
        tmp_path, monkeypatch
    )
    source = _SealedOutage()
    probes: list[float] = []

    def _probe(seconds: float) -> None:
        # A short timeout proves the lock is free: if the runner still held it,
        # this would raise TimeoutError instead of returning.
        with account_storage.mutation_lock(timeout_seconds=1.0):
            pass
        with sleeve_storage.mutation_lock(timeout_seconds=1.0):
            pass
        probes.append(seconds)

    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=source,
        price_retry_backoff_seconds=30.0,
        sleep_func=_probe,
    )

    result = runner.process_pending_executions_once(target_date="2026-06-29")

    assert probes == [30.0, 30.0]
    assert source.calls == 3
    assert result.blocked_count == 1
    assert result.filled_count == 0
    blocked = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert blocked.status == StrategyExecutionStatus.BLOCKED
    assert blocked.blocked_reason == "price_unavailable"


def test_structural_block_precedes_price_fetch_and_survives_outage(
    tmp_path, monkeypatch
) -> None:
    """A statically ineligible plan blocks with its own code, not the price code.

    Regression for the prepare/commit split (D1): the account-free structural
    guards must run before any price fetch, so a sealed outage cannot mask
    ``sleeve_paused`` with ``price_unavailable`` -- which would burn 3 price
    calls + 2x30s backoff and, being a retryable price code, silently roll the
    plan forward to MISSED_WINDOW the next day instead of staying BLOCKED.
    """
    settings, account_storage, sleeve_storage, _account, sleeve = _pending_plan_fixture(
        tmp_path, monkeypatch
    )
    paused = sleeve_storage.load_sleeve(sleeve.sleeve_id)
    paused.status = StrategySleeveStatus.PAUSED
    sleeve_storage.save_sleeve(paused)
    source = _SealedOutage()
    sleeps: list[float] = []

    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=source,
        price_retry_backoff_seconds=30.0,
        sleep_func=sleeps.append,
    )

    result = runner.process_pending_executions_once(target_date="2026-06-29")

    assert source.calls == 0
    assert sleeps == []
    assert result.blocked_count == 1
    assert result.filled_count == 0
    blocked = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert blocked.status == StrategyExecutionStatus.BLOCKED
    assert blocked.blocked_reason == "sleeve_paused"
    assert "price_unavailable_retry" not in blocked.metadata

    # Next day the structural block must remain BLOCKED: a price block would
    # have been rolled forward to MISSED_WINDOW by the expiry scan.
    follow_up = runner.process_pending_executions_once(target_date="2026-06-30")
    assert follow_up.missed_window_count == 0
    persisted = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert persisted.status == StrategyExecutionStatus.BLOCKED
    assert persisted.blocked_reason == "sleeve_paused"


def test_backoff_sleep_releases_mutation_lock_across_processes(tmp_path, monkeypatch) -> None:
    """A concurrent process must be able to mutate during the backoff sleep."""
    settings, account_storage, sleeve_storage, _account, sleeve = _pending_plan_fixture(
        tmp_path, monkeypatch
    )
    source = _SealedOutage()
    sleeps: list[float] = []
    child: dict[str, object] = {}

    def _probe(seconds: float) -> None:
        sleeps.append(seconds)
        if child:
            return
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        process = context.Process(
            target=_lock_probe_child,
            # Rebuild the storage from its base dir in the child process.
            args=(str(account_storage.account_dir.parents[1]), queue),
            daemon=True,
        )
        process.start()
        status, acquire_elapsed, _total_elapsed = queue.get(timeout=20)
        process.join(timeout=20)
        child.update(
            status=status,
            acquire_elapsed=acquire_elapsed,
            exitcode=process.exitcode,
        )

    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=source,
        price_retry_backoff_seconds=30.0,
        sleep_func=_probe,
    )

    result = runner.process_pending_executions_once(target_date="2026-06-29")

    assert child["status"] == "ok", child
    assert child["acquire_elapsed"] < 1.0, child
    assert child["exitcode"] == 0
    assert sleeps == [30.0, 30.0]
    assert source.calls == 3
    assert result.blocked_count == 1
    assert result.filled_count == 0
    blocked = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert blocked.status == StrategyExecutionStatus.BLOCKED
    assert blocked.blocked_reason == "price_unavailable"


class _FlakyOutage:
    """First call fails, subsequent calls return the sealed close."""

    def __init__(self, price: float = 100.0) -> None:
        self.price = price
        self.calls = 0

    def get_prices(self, symbols, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            raise PriceUnavailableError("transient outage")
        return {
            symbol.upper(): PricedQuote(
                symbol=symbol.upper(),
                price=self.price,
                price_kind="futu_snapshot",
                as_of="2026-06-29T13:30:00Z",
                source="fake",
            )
            for symbol in symbols
        }


@pytest.mark.parametrize("mutation", ["plan_blocked", "sleeve_stopped", "account_frozen"])
def test_external_mutation_during_backoff_fails_closed(tmp_path, monkeypatch, mutation) -> None:
    """A concurrent decision inside the window must never be overwritten."""
    settings, account_storage, sleeve_storage, _account, sleeve = _pending_plan_fixture(
        tmp_path, monkeypatch
    )
    source = _FlakyOutage()

    def _mutate(_seconds: float) -> None:
        if mutation == "plan_blocked":
            executions = sleeve_storage.load_executions(sleeve.sleeve_id)
            executions[0].status = StrategyExecutionStatus.BLOCKED
            executions[0].blocked_reason = "insufficient_sleeve_cash"
            sleeve_storage.save_executions(sleeve.sleeve_id, executions)
        elif mutation == "sleeve_stopped":
            stopped = sleeve_storage.load_sleeve(sleeve.sleeve_id)
            stopped.status = StrategySleeveStatus.STOPPED
            sleeve_storage.save_sleeve(stopped)
        else:
            frozen = account_storage.load()
            frozen.kill_switch = True
            account_storage.save(frozen)

    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
        price_source=source,
        price_retry_backoff_seconds=30.0,
        sleep_func=_mutate,
    )

    result = runner.process_pending_executions_once(target_date="2026-06-29")

    assert result.filled_count == 0
    persisted = sleeve_storage.load_executions(sleeve.sleeve_id)[0]
    assert persisted.fills == []
    reloaded_account = account_storage.load()
    assert reloaded_account.cash == pytest.approx(100_000.0)
    assert reloaded_account.positions == {}
    assert all(entry.kind != "sleeve_execution_fill" for entry in reloaded_account.ledger)
    assert sleeve_storage.load_pending_execution_journals() == []
    assert sleeve_storage.load_sleeve_lots(sleeve.sleeve_id) == []

    if mutation == "plan_blocked":
        assert result.processed_count == 0
        assert persisted.status == StrategyExecutionStatus.BLOCKED
        assert persisted.blocked_reason == "insufficient_sleeve_cash"
    elif mutation == "sleeve_stopped":
        assert result.blocked_count == 1
        assert persisted.status == StrategyExecutionStatus.BLOCKED
        assert persisted.blocked_reason == "sleeve_stopped"
    else:
        assert result.blocked_count == 1
        assert persisted.status == StrategyExecutionStatus.BLOCKED
        assert persisted.blocked_reason == "account_frozen"
        assert account_storage.load().kill_switch is True
