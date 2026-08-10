from __future__ import annotations

import hashlib

import pytest

from quant_system.execution.account import PaperAccount
from quant_system.execution.factor_automation_demote import (
    FactorAutomationDemoteService,
)
from quant_system.execution.factor_automation_safety import (
    FactorAutomationLimitError,
    FactorAutomationLimits,
    admit_auto_sleeve,
    automation_risk_limits,
    evaluate_auto_sleeve_health,
    validate_auto_execution_orders,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SleeveLot,
    StrategyConfig,
    StrategyExecutionPlanError,
    StrategySignal,
    StrategySleeveMode,
    StrategySleeveStatus,
)

POLICY_DIGEST = hashlib.sha256(b"policy").hexdigest()
MANIFEST_DIGEST = hashlib.sha256(b"manifest").hexdigest()


def _config() -> StrategyConfig:
    return StrategyConfig.create(
        name="auto factor",
        strategy_id="auto-factor",
        symbols=["SPY", "QQQ"],
        factor_ids=["factor-auto-1"],
    )


def _metadata(*, manifest_digest: str = MANIFEST_DIGEST) -> dict[str, object]:
    return {
        "automation_managed": True,
        "factor_id": "factor-auto-1",
        "manifest_digest": manifest_digest,
        "automation_policy_digest": POLICY_DIGEST,
        "promotion_scope": "paper_only",
        "reviewer": "auto",
    }


def test_auto_sleeve_admission_enforces_conservative_cash_and_duplicate_limits(
    tmp_path,
) -> None:
    account = PaperAccount.open_new(initial_cash=1_000_000)
    storage = PaperStrategySleeveStorage(tmp_path)
    service = PaperStrategySleeveService(storage)

    admission = admit_auto_sleeve(
        nav=1_000_000,
        existing_sleeves=[],
        factor_id="factor-auto-1",
        manifest_digest=MANIFEST_DIGEST,
        automation_policy_digest=POLICY_DIGEST,
    )
    assert admission.allocated_cash == 10_000
    assert admission.metadata == _metadata()
    sleeve = service.create_sleeve(
        account,
        config=_config(),
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=admission.allocated_cash,
        metadata=admission.metadata,
    )

    with pytest.raises(FactorAutomationLimitError) as duplicate_factor:
        admit_auto_sleeve(
            nav=1_000_000,
            existing_sleeves=[sleeve],
            factor_id="factor-auto-1",
            manifest_digest=hashlib.sha256(b"other").hexdigest(),
            automation_policy_digest=POLICY_DIGEST,
        )
    assert duplicate_factor.value.code == "duplicate_factor"

    with pytest.raises(FactorAutomationLimitError) as duplicate_manifest:
        admit_auto_sleeve(
            nav=1_000_000,
            existing_sleeves=[sleeve],
            factor_id="factor-auto-2",
            manifest_digest=MANIFEST_DIGEST,
            automation_policy_digest=POLICY_DIGEST,
        )
    assert duplicate_manifest.value.code == "duplicate_manifest"


def test_auto_sleeve_admission_blocks_single_and_aggregate_cash_overage(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path)
    service = PaperStrategySleeveService(storage)
    existing = []
    for index in range(10):
        existing.append(
            service.build_sleeve(
                config=_config().new_version(strategy_id=f"auto-{index}"),
                mode=StrategySleeveMode.ALLOCATED,
                allocated_cash=1_000,
                metadata={
                    **_metadata(
                        manifest_digest=hashlib.sha256(f"manifest-{index}".encode()).hexdigest()
                    ),
                    "factor_id": f"factor-{index}",
                },
            )
        )

    with pytest.raises(FactorAutomationLimitError) as aggregate:
        admit_auto_sleeve(
            nav=100_000,
            existing_sleeves=existing,
            factor_id="factor-new",
            manifest_digest=hashlib.sha256(b"manifest-new").hexdigest(),
            automation_policy_digest=POLICY_DIGEST,
        )
    assert aggregate.value.code == "aggregate_auto_cash_limit"

    with pytest.raises(FactorAutomationLimitError) as single:
        admit_auto_sleeve(
            nav=100_000,
            existing_sleeves=[],
            factor_id="factor-new",
            manifest_digest=hashlib.sha256(b"manifest-new").hexdigest(),
            automation_policy_digest=POLICY_DIGEST,
            requested_cash=1_001,
        )
    assert single.value.code == "single_sleeve_cash_limit"


def test_auto_sleeve_risk_limits_do_not_trip_inner_kill_switch() -> None:
    limits = automation_risk_limits(["SPY", "QQQ"])

    assert limits.kill_switch is False
    assert limits.max_position_size == 0.40
    assert limits.max_daily_loss == 0.02
    assert limits.max_drawdown == 0.10
    assert limits.max_order_value == 10_000


def test_daily_loss_and_drawdown_require_pause() -> None:
    limits = FactorAutomationLimits()

    assert evaluate_auto_sleeve_health(
        equity=9_700,
        peak_equity=10_000,
        daily_pnl=-201,
        limits=limits,
    ) == ("max_daily_loss",)
    assert evaluate_auto_sleeve_health(
        equity=8_999,
        peak_equity=10_000,
        daily_pnl=0,
        limits=limits,
    ) == ("max_drawdown",)


def test_quarantine_blocks_signals_resume_and_execution_but_keeps_lots_visible(
    tmp_path,
) -> None:
    account = PaperAccount.open_new(initial_cash=100_000)
    storage = PaperStrategySleeveStorage(tmp_path)
    service = PaperStrategySleeveService(storage)
    sleeve = service.create_sleeve(
        account,
        config=_config(),
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata=_metadata(),
    )
    storage.save_sleeve(sleeve)
    storage.save_sleeve_lots(
        sleeve.sleeve_id,
        [
            SleeveLot.create(
                sleeve_id=sleeve.sleeve_id,
                symbol="SPY",
                quantity=2,
                avg_cost=500,
                source=f"strategy:{sleeve.sleeve_id}",
            )
        ],
    )
    demoter = FactorAutomationDemoteService(storage)
    sleeve = demoter.demote(
        sleeve,
        request_id="demote-factor-missing-1",
        reason="factor_missing",
    )
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-08-10",
        data_provider="futu",
        proposed_orders=[{"symbol": "SPY", "side": "buy", "notional_delta": 100}],
    )

    assert sleeve.status == StrategySleeveStatus.QUARANTINED_HOLD
    assert signal.execution_blocked_reason == "sleeve_quarantined_hold"
    assert storage.list_sleeves()[0].status == StrategySleeveStatus.QUARANTINED_HOLD
    assert storage.load_sleeve_lots(sleeve.sleeve_id)[0].quantity == 2
    assert storage.load_demoted_state(sleeve.sleeve_id)["status"] == "quarantined_hold"
    with pytest.raises(ValueError, match="only paused sleeves"):
        service.resume_sleeve(sleeve)
    with pytest.raises(StrategyExecutionPlanError) as blocked:
        service.create_execution_plan(account, sleeve=sleeve, signal=signal)
    assert blocked.value.code == "sleeve_quarantined_hold"

    replay = demoter.demote(
        sleeve,
        request_id="demote-factor-missing-1",
        reason="factor_missing",
    )
    assert replay.status == StrategySleeveStatus.QUARANTINED_HOLD


def test_factor_missing_sweep_quarantines_only_automation_sleeves(tmp_path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path)
    service = PaperStrategySleeveService(storage)
    auto = service.build_sleeve(
        config=_config(),
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata=_metadata(),
    )
    manual = service.build_sleeve(
        config=_config().new_version(strategy_id="manual"),
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1_000,
        metadata={},
    )
    storage.save_sleeve(auto)
    storage.save_sleeve(manual)

    changed = FactorAutomationDemoteService(storage).quarantine_missing_factors(
        registered_factor_ids=set()
    )

    assert [sleeve.sleeve_id for sleeve in changed] == [auto.sleeve_id]
    assert storage.load_sleeve(auto.sleeve_id).status == StrategySleeveStatus.QUARANTINED_HOLD
    assert storage.load_sleeve(manual.sleeve_id).status == StrategySleeveStatus.RUNNING


def test_execution_order_limits_cover_sleeve_and_cross_sleeve_symbol_exposure() -> None:
    limits = FactorAutomationLimits()
    validate_auto_execution_orders(
        orders=[{"symbol": "SPY", "notional_delta": 2_000}],
        sleeve_equity=10_000,
        nav=1_000_000,
        aggregate_symbol_values={"SPY": 45_000},
        limits=limits,
    )

    with pytest.raises(FactorAutomationLimitError) as sleeve_symbol:
        validate_auto_execution_orders(
            orders=[{"symbol": "SPY", "notional_delta": 4_001}],
            sleeve_equity=10_000,
            nav=1_000_000,
            aggregate_symbol_values={},
            limits=limits,
        )
    assert sleeve_symbol.value.code == "sleeve_symbol_limit"

    with pytest.raises(FactorAutomationLimitError) as aggregate_symbol:
        validate_auto_execution_orders(
            orders=[{"symbol": "SPY", "notional_delta": 5_001}],
            sleeve_equity=20_000,
            nav=1_000_000,
            aggregate_symbol_values={"SPY": 45_000},
            limits=limits,
        )
    assert aggregate_symbol.value.code == "aggregate_symbol_limit"
