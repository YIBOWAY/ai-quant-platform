from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from quant_system.execution.d34_canary_monitor import maintain_d34_canaries
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SleeveLot,
    StrategyConfig,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.hermes.d34_registry_authority import D34Canary


class Registry:
    def __init__(self, canary: D34Canary) -> None:
        self.canary = canary
        self.observations: list[tuple[Decimal, Decimal, int]] = []
        self.transitions: list[tuple[str, str, int, str]] = []

    def list_canaries(self, *, workspace_id: str, limit: int):
        assert workspace_id == "default"
        assert limit == 100
        return [self.canary]

    def get_canary(self, canary_id: str) -> D34Canary:
        assert canary_id == self.canary.canary_id
        return self.canary

    def record_canary_observation(
        self,
        *,
        canary_id: str,
        expected_version: int,
        daily_pnl: Decimal,
        drawdown_fraction: Decimal,
        observation: dict[str, object],
    ) -> D34Canary:
        assert canary_id == self.canary.canary_id
        assert expected_version == self.canary.version
        assert observation["contract"] == "hqa.d34_canary_observation/v1"
        self.observations.append((daily_pnl, drawdown_fraction, expected_version))
        self.canary = replace(
            self.canary,
            daily_pnl=daily_pnl,
            drawdown_fraction=drawdown_fraction,
            version=expected_version + 1,
        )
        return self.canary

    def transition_canary(
        self, *, canary_id: str, action: str, expected_version: int, reason: str
    ) -> D34Canary:
        assert canary_id == self.canary.canary_id
        assert expected_version == self.canary.version
        self.transitions.append((canary_id, action, expected_version, reason))
        self.canary = replace(
            self.canary,
            status={"pause": "paused", "demote": "demoted"}[action],
            version=expected_version + 1,
        )
        return self.canary


class Prices:
    def get_prices(self, symbols: list[str]):
        assert symbols == ["SPY"]
        return {"SPY": SimpleNamespace(price=100.0, source="futu")}


class FallbackPrices:
    def get_prices(self, symbols: list[str]):
        assert symbols == ["SPY"]
        return {"SPY": SimpleNamespace(price=100.0, source="sample")}


def _setup(tmp_path: Path, *, status: str = "running"):
    storage = PaperStrategySleeveStorage(tmp_path)
    now = datetime(2026, 8, 11, tzinfo=ZoneInfo("Asia/Shanghai"))
    canary = D34Canary(
        canary_id="canary-test",
        artifact_id="artifact-test",
        mandate_id="mandate-test",
        workspace_id="default",
        sleeve_id="sleeve-d34-test",
        status=status,
        allocated_cash=Decimal("1000"),
        nav_fraction=Decimal("0.01"),
        daily_pnl=Decimal("0"),
        drawdown_fraction=Decimal("0"),
        created_at=now,
        updated_at=now,
        version=1,
    )
    config = StrategyConfig.create(
        strategy_config_id="strategy-d34-test",
        name="D-34 monitor",
        strategy_id="cross_sectional_top_n",
        symbols=["SPY"],
        factor_ids=["factor-test"],
    )
    sleeve = PaperStrategySleeveService(storage).build_sleeve(
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=1000,
        sleeve_id=canary.sleeve_id,
        metadata={
            "automation_managed": True,
            "automation_source": "d34",
            "artifact_id": canary.artifact_id,
            "factor_id": "factor-test",
            "artifact_code_path": str(tmp_path / "factor.py"),
            "candidate_code_digest": "a" * 64,
            "promotion_scope": "paper_only",
            "automation_health_day": "2026-08-11",
            "automation_day_start_equity": 1000.0,
            "automation_peak_equity": 1100.0,
        },
    )
    sleeve.cash = 870.0
    if status == "paused":
        sleeve.status = StrategySleeveStatus.PAUSED
    elif status in {"demoted", "rolled_back"}:
        sleeve.status = StrategySleeveStatus.QUARANTINED_HOLD
    storage.save_sleeve(sleeve)
    storage.save_sleeve_lots(
        sleeve.sleeve_id,
        [
            SleeveLot.create(
                sleeve_id=sleeve.sleeve_id,
                symbol="SPY",
                quantity=1,
                avg_cost=120,
                source="d34-test",
            )
        ],
    )
    return storage, Registry(canary), now


def test_monitor_records_pnl_and_drawdown_then_pauses_running_canary(
    tmp_path: Path,
) -> None:
    storage, registry, now = _setup(tmp_path)

    result = maintain_d34_canaries(
        now=now,
        workspace_id="default",
        registry=registry,
        sleeve_storage=storage,
        price_source=Prices(),
        factor_validator=lambda _sleeve: None,
    )

    assert result == {"checked": 1, "observed": 1, "paused": 1, "demoted": 0}
    daily_pnl, drawdown, version = registry.observations[0]
    assert daily_pnl == Decimal("-30.00")
    assert drawdown == Decimal("0.118181818")
    assert version == 1
    assert registry.transitions == [("canary-test", "pause", 2, "max_daily_loss,max_drawdown")]
    sleeve = storage.load_sleeve("sleeve-d34-test")
    assert sleeve.status == StrategySleeveStatus.PAUSED
    assert sleeve.metadata["automation_last_equity"] == pytest.approx(970.0)


def test_monitor_keeps_observing_paused_hold_without_retransition(tmp_path: Path) -> None:
    storage, registry, now = _setup(tmp_path, status="paused")

    result = maintain_d34_canaries(
        now=now,
        workspace_id="default",
        registry=registry,
        sleeve_storage=storage,
        price_source=Prices(),
        factor_validator=lambda _sleeve: None,
    )

    assert result == {"checked": 1, "observed": 1, "paused": 0, "demoted": 0}
    assert registry.transitions == []


def test_monitor_prices_demoted_hold_without_loading_factor_code(tmp_path: Path) -> None:
    storage, registry, now = _setup(tmp_path, status="demoted")

    result = maintain_d34_canaries(
        now=now,
        workspace_id="default",
        registry=registry,
        sleeve_storage=storage,
        price_source=Prices(),
        factor_validator=lambda _sleeve: pytest.fail("demoted hold loaded factor"),
    )

    assert result == {"checked": 1, "observed": 1, "paused": 0, "demoted": 0}
    assert registry.transitions == []


def test_monitor_rejects_non_futu_price_fallback(tmp_path: Path) -> None:
    storage, registry, now = _setup(tmp_path)

    with pytest.raises(ValueError, match="d34_canary_requires_futu_prices"):
        maintain_d34_canaries(
            now=now,
            workspace_id="default",
            registry=registry,
            sleeve_storage=storage,
            price_source=FallbackPrices(),
            factor_validator=lambda _sleeve: None,
        )

    assert registry.observations == []
    assert registry.transitions == []
