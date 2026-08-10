from __future__ import annotations

from datetime import date

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
)
from quant_system.execution.factor_automation_authority import (
    FactorAutomationEventReceipt,
    FactorAutomationLineage,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
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
