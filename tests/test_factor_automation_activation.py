from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from quant_system.config.settings import reload_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.factor_automation_activation import (
    AccountValuation,
    AutomaticLandAuthorizationRequest,
    AutomaticSleeveRequest,
    FactorAutomationActivationError,
    authorize_automatic_land,
    create_automatic_paper_sleeve,
    maintain_automatic_paper_sleeves,
    run_automatic_paper_cycle,
)
from quant_system.execution.factor_automation_authority import (
    FactorAutomationEventReceipt,
    FactorAutomationLineage,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from tests.test_paper_strategy_operations import FakePriceSource
from tests.test_paper_strategy_signals import (
    FakeOHLCVProvider,
    make_config,
    make_ohlcv_frame,
    patch_provider,
)


def _settings(monkeypatch, tmp_path, *, enabled: bool = True):
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "QS_FACTOR_AUTOMATION_MODE", "true" if enabled else "false"
    )
    monkeypatch.setenv(
        "QS_FACTOR_AUTOMATION_AUTO_LAND", "true" if enabled else "false"
    )
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "file")
    return reload_settings()


def _promotion_status() -> dict[str, object]:
    return {
        "promotion_id": "promo-" + ("1" * 32),
        "status": "reviewed",
        "reviewed_commit": "2" * 40,
        "reason": "reviewed",
        "manifest_sha256": "3" * 64,
        "patch_sha256": "4" * 64,
        "candidate_id": "candidate-1",
        "candidate_digest": "5" * 64,
        "final_backtest_receipt_id": "backtest-" + ("6" * 32),
        "base_commit": "7" * 40,
        "scoped_paths": [
            "src/quant_system/factors/library/promoted/auto_factor.py",
            "src/quant_system/factors/library/promoted/__init__.py",
            "tests/test_auto_factor.py",
        ],
    }


def test_authorize_land_consumes_quota_only_for_exact_reviewed_status(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(monkeypatch, tmp_path)
    written = []

    def writer(_settings, event):
        written.append(event)
        return FactorAutomationEventReceipt(1, date(2026, 8, 10), False)

    request = AutomaticLandAuthorizationRequest(
        automation_id="automation-0123456789abcdef",
        promotion_id="promo-" + ("1" * 32),
        automation_policy_digest="8" * 64,
        intake_contract_digest="9" * 64,
        gate1_digest="a" * 64,
        gate2_digest="b" * 64,
    )
    lineage, receipt = authorize_automatic_land(
        settings,
        request,
        promotion_status=_promotion_status(),
        event_writer=writer,
    )

    assert lineage.factor_id == "auto_factor"
    assert lineage.gate3_digest == "4" * 64
    assert lineage.commit_sha == "2" * 40
    assert receipt.event_seq == 1
    assert written[0].event_type == "promotion_committed"
    assert written[0].sleeve_id is None

    bad = {**_promotion_status(), "status": "awaiting_human_commit"}
    with pytest.raises(FactorAutomationActivationError, match="promotion_status_invalid"):
        authorize_automatic_land(
            settings,
            request,
            promotion_status=bad,
            event_writer=writer,
        )
    assert len(written) == 1


def test_automatic_sleeve_is_allocated_once_and_audited_idempotently(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "quant_system.execution.factor_automation_activation._verify_resident_factor",
        lambda _lineage: None,
    )
    api_runs = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs)
    sleeve_storage = PaperStrategySleeveStorage(api_runs)
    account = PaperAccount.open_new(initial_cash=1_000_000)
    account_storage.save(account)
    lineage = FactorAutomationLineage(
        automation_id="automation-0123456789abcdef",
        candidate_id="candidate-1",
        candidate_digest="5" * 64,
        factor_id="auto_factor",
        manifest_digest="3" * 64,
        automation_policy_digest="8" * 64,
        intake_contract_digest="9" * 64,
        gate1_digest="a" * 64,
        gate2_digest="b" * 64,
        gate3_digest="4" * 64,
        commit_sha="2" * 40,
    )
    request = AutomaticSleeveRequest(
        lineage=lineage,
        promotion_id="promo-" + ("1" * 32),
        universe=("SPY", "QQQ"),
        provider="futu",
    )
    written = []

    def writer(_settings, event):
        written.append(event)
        return FactorAutomationEventReceipt(
            len(written),
            date(2026, 8, 10),
            len(written) > 1,
        )

    def valuation() -> AccountValuation:
        current = account_storage.load()
        assert current is not None
        return AccountValuation(
            account_id=current.account_id,
            account_updated_at=current.updated_at,
            nav=current.cash,
            prices={},
            price_metadata={},
        )

    first, _ = create_automatic_paper_sleeve(
        settings,
        request,
        valuation=valuation(),
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        event_writer=writer,
    )
    second, _ = create_automatic_paper_sleeve(
        settings,
        request,
        valuation=valuation(),
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        event_writer=writer,
    )

    persisted = account_storage.load()
    assert persisted is not None
    assert first == second
    assert first.initial_allocated_cash == 10_000
    assert persisted.sleeve_cash[first.sleeve_id] == 10_000
    assert len(
        [entry for entry in persisted.ledger if entry.kind == "sleeve_cash_allocated"]
    ) == 1
    assert len(sleeve_storage.list_sleeves()) == 1
    assert [event.event_type for event in written] == [
        "sleeve_created",
        "sleeve_created",
    ]


def test_activation_flags_off_prevents_all_writes(tmp_path, monkeypatch) -> None:
    settings = _settings(monkeypatch, tmp_path, enabled=False)
    with pytest.raises(FactorAutomationActivationError, match="factor_automation_disabled"):
        authorize_automatic_land(
            settings,
            AutomaticLandAuthorizationRequest(
                automation_id="automation-0123456789abcdef",
                promotion_id="promo-" + ("1" * 32),
                automation_policy_digest="8" * 64,
                intake_contract_digest="9" * 64,
                gate1_digest="a" * 64,
                gate2_digest="b" * 64,
            ),
            promotion_status=_promotion_status(),
        )


def test_maintenance_pauses_breached_sleeve_and_audits_before_state_change(
    tmp_path, monkeypatch
) -> None:
    settings = _settings(monkeypatch, tmp_path)
    api_runs = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs)
    sleeve_storage = PaperStrategySleeveStorage(api_runs)
    account = PaperAccount.open_new(initial_cash=1_000_000)
    account_storage.save(account)
    lineage = FactorAutomationLineage(
        automation_id="automation-0123456789abcdef",
        candidate_id="candidate-1",
        candidate_digest="5" * 64,
        factor_id="auto_factor",
        manifest_digest="3" * 64,
        automation_policy_digest="8" * 64,
        intake_contract_digest="9" * 64,
        gate1_digest="a" * 64,
        gate2_digest="b" * 64,
        gate3_digest="4" * 64,
        commit_sha="2" * 40,
    )
    monkeypatch.setattr(
        "quant_system.execution.factor_automation_activation._verify_resident_factor",
        lambda _lineage: None,
    )
    request = AutomaticSleeveRequest(
        lineage=lineage,
        promotion_id="promo-" + ("1" * 32),
        universe=("SPY", "QQQ"),
        provider="futu",
    )
    current = account_storage.load()
    assert current is not None
    valuation = AccountValuation(
        account_id=current.account_id,
        account_updated_at=current.updated_at,
        nav=current.cash,
        prices={},
        price_metadata={},
    )
    sleeve, _ = create_automatic_paper_sleeve(
        settings,
        request,
        valuation=valuation,
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        event_writer=lambda *_args: FactorAutomationEventReceipt(
            1, date.today(), False
        ),
    )
    sleeve.cash = 9_700
    sleeve.metadata.update(
        {
            "automation_health_day": date.today().isoformat(),
            "automation_day_start_equity": 10_000.0,
            "automation_peak_equity": 10_000.0,
        }
    )
    sleeve_storage.save_sleeve(sleeve)

    class Registry:
        @staticmethod
        def factor_ids():
            return ["auto_factor"]

    monkeypatch.setattr(
        "quant_system.execution.factor_automation_activation.build_factor_registry",
        lambda **_kwargs: Registry(),
    )
    events = []

    def writer(_settings, event):
        assert sleeve_storage.load_sleeve(sleeve.sleeve_id).status == (
            StrategySleeveStatus.RUNNING
        )
        events.append(event)
        return FactorAutomationEventReceipt(2, date.today(), False)

    persisted_account = account_storage.load()
    assert persisted_account is not None
    result = maintain_automatic_paper_sleeves(
        settings,
        valuation=AccountValuation(
            account_id=persisted_account.account_id,
            account_updated_at=persisted_account.updated_at,
            nav=persisted_account.cash,
            prices={},
            price_metadata={},
        ),
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        event_writer=writer,
    )

    assert result == {"checked": 1, "paused": 1, "quarantined": 0}
    assert events[0].event_type == "sleeve_paused"
    assert events[0].details["reasons"] == ["max_daily_loss"]
    assert sleeve_storage.load_sleeve(sleeve.sleeve_id).status == (
        StrategySleeveStatus.PAUSED
    )


def test_d33_maintenance_ignores_d34_managed_sleeves(tmp_path, monkeypatch) -> None:
    settings = _settings(monkeypatch, tmp_path)
    api_runs = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs)
    sleeve_storage = PaperStrategySleeveStorage(api_runs)
    account = PaperAccount.open_new(initial_cash=1_000_000)
    config = make_config()
    sleeve_storage.save_strategy_config(config)
    sleeve = PaperStrategySleeveService(sleeve_storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": "artifact-d34-test",
        },
        sleeve_id="sleeve-d34-test",
    )
    sleeve_storage.save_sleeve(sleeve)
    account_storage.save(account)

    class Registry:
        @staticmethod
        def factor_ids():
            return []

    monkeypatch.setattr(
        "quant_system.execution.factor_automation_activation.build_factor_registry",
        lambda **_kwargs: Registry(),
    )
    current = account_storage.load()
    assert current is not None

    result = maintain_automatic_paper_sleeves(
        settings,
        valuation=AccountValuation(
            account_id=current.account_id,
            account_updated_at=current.updated_at,
            nav=current.cash,
            prices={},
            price_metadata={},
        ),
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        event_writer=lambda *_args: pytest.fail("D-33 must not audit a D-34 sleeve"),
    )

    assert result == {"checked": 0, "paused": 0, "quarantined": 0}
    assert sleeve_storage.load_sleeve(sleeve.sleeve_id).status == (
        StrategySleeveStatus.RUNNING
    )


def test_automatic_paper_cycle_materializes_one_next_open_plan_idempotently(
    tmp_path,
    monkeypatch,
) -> None:
    settings = _settings(monkeypatch, tmp_path)
    patch_provider(monkeypatch, FakeOHLCVProvider(make_ohlcv_frame()))
    api_runs = tmp_path / "api_runs"
    account_storage = PaperAccountStorage(api_runs)
    sleeve_storage = PaperStrategySleeveStorage(api_runs)
    account = PaperAccount.open_new(initial_cash=1_000_000)
    config = make_config(max_weight_per_symbol=0.40)
    sleeve_storage.save_strategy_config(config)
    service = PaperStrategySleeveService(sleeve_storage)
    automated = service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000,
        metadata={"automation_managed": True, "automation_source": "d33"},
        sleeve_id="sleeve-auto-0123456789abcdef",
    )
    d34 = service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000,
        metadata={"automation_managed": True, "automation_source": "d34"},
        sleeve_id="sleeve-d34-0123456789abcdef",
    )
    manual = service.create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10_000,
    )
    sleeve_storage.save_sleeve(automated)
    sleeve_storage.save_sleeve(d34)
    sleeve_storage.save_sleeve(manual)
    account_storage.save(account)
    local_tz = ZoneInfo("Asia/Shanghai")
    saturday = datetime(2026, 6, 27, 6, 15, tzinfo=local_tz)

    first = run_automatic_paper_cycle(
        settings,
        now=saturday,
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
    )
    second = run_automatic_paper_cycle(
        settings,
        now=saturday,
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
    )

    signals = sleeve_storage.load_signals(automated.sleeve_id)
    executions = sleeve_storage.load_executions(automated.sleeve_id)
    assert first["signals_generated"] == 1
    assert first["executions_created"] == 1
    assert second["signals_generated"] == 0
    assert second["executions_created"] == 0
    assert len(signals) == len(executions) == 1
    assert executions[0].signal_id == signals[0].signal_id
    assert executions[0].target_date == "2026-06-29"
    assert sleeve_storage.load_signals(d34.sleeve_id) == []
    assert sleeve_storage.load_signals(manual.sleeve_id) == []

    executed = run_automatic_paper_cycle(
        settings,
        now=datetime(2026, 6, 29, 21, 40, tzinfo=local_tz),
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        price_source=FakePriceSource({"AAPL": 179.0, "MSFT": 180.25}),
    )
    assert executed["executions_processed"] == 1
    assert executed["executions_filled"] == 1
