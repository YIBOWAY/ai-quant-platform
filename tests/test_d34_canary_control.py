from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quant_system.execution.d34_canary_control import (
    D34CanaryControlError,
    D34CanaryController,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.hermes.d34_registry_authority import D34Canary


class _Registry:
    def __init__(self, canaries: list[D34Canary]) -> None:
        self.canaries = {item.canary_id: item for item in canaries}
        self.transitions: list[tuple[str, str, int, str]] = []

    def get_canary(self, canary_id: str) -> D34Canary:
        return self.canaries[canary_id]

    def list_canaries(self, *, workspace_id: str, limit: int):
        assert limit == 100
        return [item for item in self.canaries.values() if item.workspace_id == workspace_id]

    def transition_canary(
        self, *, canary_id: str, action: str, expected_version: int, reason: str
    ) -> D34Canary:
        current = self.canaries[canary_id]
        assert current.version == expected_version
        self.transitions.append((canary_id, action, expected_version, reason))
        target = {"pause": "paused", "demote": "demoted", "rollback": "rolled_back"}[
            action
        ]
        updated = D34Canary(
            **{
                **current.__dict__,
                "status": target,
                "version": expected_version + 1,
            }
        )
        self.canaries[canary_id] = updated
        return updated


def _canary(token: str, *, version: int = 1) -> D34Canary:
    now = datetime(2026, 8, 11, tzinfo=UTC)
    return D34Canary(
        canary_id=f"canary-{token}",
        artifact_id=f"artifact-{token}",
        mandate_id=f"mandate-{token}",
        workspace_id="default",
        sleeve_id=f"sleeve-d34-{token}",
        status="running",
        allocated_cash=Decimal("1000"),
        nav_fraction=Decimal("0.01"),
        daily_pnl=Decimal("0"),
        drawdown_fraction=Decimal("0"),
        created_at=now,
        updated_at=now,
        version=version,
    )


def _save_sleeve(storage: PaperStrategySleeveStorage, canary: D34Canary) -> None:
    config = StrategyConfig.create(
        strategy_config_id=f"strategy-{canary.canary_id}",
        name="D-34 test",
        strategy_id="cross_sectional_top_n",
        universe_id="test",
        symbols=["SPY"],
        factor_ids=["test"],
    )
    sleeve = PaperStrategySleeveService(storage).build_sleeve(
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1000,
        sleeve_id=canary.sleeve_id,
        metadata={
            "automation_source": "d34",
            "artifact_id": canary.artifact_id,
            "promotion_scope": "paper_only",
        },
    )
    storage.save_sleeve(sleeve)


def test_pause_then_demote_stops_sleeve_before_registry_transition(tmp_path: Path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path)
    canary = _canary("one")
    _save_sleeve(storage, canary)
    registry = _Registry([canary])
    controller = D34CanaryController(registry=registry, sleeve_storage=storage)

    paused = controller.transition(
        canary_id=canary.canary_id,
        action="pause",
        expected_version=1,
        reason="owner pause",
    )
    demoted = controller.transition(
        canary_id=canary.canary_id,
        action="demote",
        expected_version=2,
        reason="quality degraded",
    )

    assert paused.status == "paused"
    assert demoted.status == "demoted"
    sleeve = storage.load_sleeve(canary.sleeve_id)
    assert sleeve.status == StrategySleeveStatus.QUARANTINED_HOLD
    assert sleeve.stop_reason == "quality degraded"
    assert registry.transitions == [
        (canary.canary_id, "pause", 1, "owner pause"),
        (canary.canary_id, "demote", 2, "quality degraded"),
    ]


def test_rollback_quarantines_all_active_d34_sleeves_without_flatten(tmp_path: Path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path)
    canaries = [_canary("one"), _canary("two")]
    for canary in canaries:
        _save_sleeve(storage, canary)
    registry = _Registry(canaries)
    controller = D34CanaryController(registry=registry, sleeve_storage=storage)

    result = controller.rollback_all(workspace_id="default", reason="return to D-33")

    assert result == {
        "transitioned": 2,
        "canary_ids": ["canary-one", "canary-two"],
    }
    for canary in canaries:
        assert (
            storage.load_sleeve(canary.sleeve_id).status
            == StrategySleeveStatus.QUARANTINED_HOLD
        )


def test_control_rejects_non_d34_or_wrong_artifact_sleeve(tmp_path: Path) -> None:
    storage = PaperStrategySleeveStorage(tmp_path)
    canary = _canary("one")
    _save_sleeve(storage, canary)
    sleeve = storage.load_sleeve(canary.sleeve_id)
    sleeve.metadata["artifact_id"] = "artifact-other"
    storage.save_sleeve(sleeve)
    controller = D34CanaryController(registry=_Registry([canary]), sleeve_storage=storage)

    with pytest.raises(D34CanaryControlError, match="d34_canary_lineage_invalid"):
        controller.transition(
            canary_id=canary.canary_id,
            action="pause",
            expected_version=1,
            reason="owner pause",
        )
