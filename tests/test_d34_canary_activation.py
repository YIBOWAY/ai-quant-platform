from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quant_system.execution.account import PaperAccount
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.d34_canary_activation import (
    D34CanaryActivationRequest,
    activate_d34_paper_canary,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategySignal,
    StrategySleeveStatus,
)
from quant_system.hermes.d34_registry_authority import D34Artifact


class _Registry:
    def __init__(self, *, failures: int = 0) -> None:
        self.commands = []
        self.failures = failures

    def provision_canary(self, command):
        self.commands.append(command)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("registry temporarily unavailable")
        return {
            "contract": "hqa.d34_canary/v1",
            "artifact_id": command.artifact_id,
            "sleeve_id": command.sleeve_id,
            "status": "running",
        }


def _factor(tmp_path: Path) -> tuple[Path, str]:
    source = b'''import pandas as pd
from quant_system.factors.base import BaseFactor
class GeneratedFactor(BaseFactor):
    factor_id = "d34_generated"
    factor_name = "D34 Generated"
    default_lookback = 2
    direction = "higher_is_better"
    description = "test"
    def _compute_values(self, frame: pd.DataFrame) -> pd.Series:
        return frame.groupby("symbol", sort=False)["close"].pct_change(2)
D34_FACTOR = GeneratedFactor
'''
    path = tmp_path / "generated.py"
    path.write_bytes(source)
    return path, hashlib.sha256(source).hexdigest()


def test_artifact_activates_one_real_digest_bound_paper_sleeve_idempotently(
    tmp_path: Path,
) -> None:
    code_path, code_digest = _factor(tmp_path)
    account_storage = PaperAccountStorage(tmp_path)
    sleeve_storage = PaperStrategySleeveStorage(tmp_path)
    account = PaperAccount.open_new(initial_cash=100_000)
    account_storage.save(account)
    registry = _Registry(failures=1)
    artifact = D34Artifact(
        artifact_id="artifact-" + "a" * 32,
        mandate_id="mandate-00000000-0000-0000-0000-000000000034",
        workspace_id="default",
        status="qualified",
        qualification_scope="paper_only",
        policy_digest="1" * 64,
        snapshot_digest="2" * 64,
        candidate_code_digest=code_digest,
        qlib_config_digest="3" * 64,
        rdagent_commit="4" * 40,
        qlib_commit="5" * 40,
        docker_image_digest="sha256:" + "6" * 64,
        qlib_receipt_digest="7" * 64,
        platform_receipt_digest="8" * 64,
        comparison_digest="9" * 64,
        policy_decision_id="decision-test",
        created_at=datetime(2026, 8, 11, tzinfo=UTC),
        updated_at=datetime(2026, 8, 11, tzinfo=UTC),
        version=1,
    )
    request = D34CanaryActivationRequest(
        artifact=artifact,
        factor_id="d34_generated",
        artifact_code_path=code_path,
        universe=("SPY", "QQQ", "IWM", "DIA"),
        provider="futu",
        nav=Decimal("100000"),
        account_updated_at=account.updated_at,
        prices={},
        price_metadata={},
    )

    with pytest.raises(RuntimeError, match="registry temporarily unavailable"):
        activate_d34_paper_canary(
            request,
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            registry=registry,
        )
    awaiting = sleeve_storage.list_sleeves()[0]
    assert awaiting.status == StrategySleeveStatus.PAUSED
    assert awaiting.metadata["d34_activation_state"] == "awaiting_registry"

    first, first_canary = activate_d34_paper_canary(
        request,
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        registry=registry,
    )
    replay, replay_canary = activate_d34_paper_canary(
        request,
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        registry=registry,
    )

    assert replay == first
    assert first_canary == replay_canary
    assert first.initial_allocated_cash == 1000
    assert first.status == StrategySleeveStatus.RUNNING
    assert first.metadata["automation_source"] == "d34"
    assert first.metadata["artifact_id"] == artifact.artifact_id
    assert first.metadata["d34_activation_state"] == "active"
    assert first.metadata["workspace_id"] == artifact.workspace_id
    assert first.metadata["promotion_scope"] == "paper_only"
    config = sleeve_storage.load_strategy_config(first.strategy_config_id)
    assert config.factor_ids == ["d34_generated"]
    assert config.lookback == 2
    assert config.top_n == 1
    assert config.max_weight_per_symbol == 0.99
    assert config.metadata["workspace_id"] == artifact.workspace_id
    assert config.metadata["artifact_code_path"] == str(code_path.resolve())
    signal = StrategySignal.create(
        sleeve=first,
        signal_date="2026-08-11",
        data_provider="futu",
        target_weights={"SPY": 0.99},
        proposed_orders=[
            {
                "symbol": "SPY",
                "side": "buy",
                "notional_delta": 990.0,
                "target_weight": 0.99,
                "reference_price": 495.0,
            }
        ],
    )
    plan = PaperStrategySleeveService(sleeve_storage).create_execution_plan(
        account_storage.load(),  # type: ignore[arg-type]
        sleeve=first,
        signal=signal,
        metadata={
            "paper_execution_policy_context": {
                "paper_execution_enabled": True,
                "emergency_stop": False,
                "mandate_active": True,
                "mandate_paper_execution_allowed": True,
            }
        },
    )
    assert plan.metadata["paper_execution_policy_decision"]["allowed"] is True
    assert len(sleeve_storage.list_sleeves()) == 1
    assert account_storage.load().sleeve_cash[first.sleeve_id] == 1000  # type: ignore[union-attr]
    assert registry.commands[0].allocated_cash == Decimal("1000.0")
