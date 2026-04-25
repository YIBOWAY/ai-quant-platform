from __future__ import annotations

from enum import StrEnum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FactorDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class FactorWeight(BaseModel):
    factor_id: str
    weight: float = 1.0
    direction: FactorDirection = FactorDirection.HIGHER_IS_BETTER


class FactorBlendConfig(BaseModel):
    factors: list[FactorWeight]
    rebalance_every_n_bars: int = Field(default=1, gt=0)

    @model_validator(mode="after")
    def require_at_least_one_factor(self) -> FactorBlendConfig:
        if not self.factors:
            raise ValueError("at least one factor is required")
        return self


class WalkForwardConfig(BaseModel):
    enabled: bool = False
    train_bars: int = Field(default=60, gt=0)
    validation_bars: int = Field(default=20, gt=0)
    step_bars: int = Field(default=20, gt=0)


class ExperimentConfig(BaseModel):
    experiment_name: str = "phase4-experiment"
    symbols: list[str]
    start: str
    end: str
    initial_cash: float = Field(default=100_000.0, ge=0)
    commission_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    target_gross_exposure: float = Field(default=1.0, ge=0)
    factor_blend: FactorBlendConfig
    sweep: dict[str, list[int | float | str]] = Field(default_factory=dict)
    walk_forward: WalkForwardConfig = Field(default_factory=WalkForwardConfig)


class ParameterCombination(BaseModel):
    run_id: str
    parameters: dict[str, int | float | str]


class WalkForwardSplit(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    fold_id: str
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    validation_start: pd.Timestamp
    validation_end: pd.Timestamp


class ExperimentRunSummary(BaseModel):
    run_id: str
    created_at: str
    parameters: dict[str, int | float | str]
    total_return: float
    annualized_return: float
    volatility: float
    sharpe: float
    max_drawdown: float
    turnover: float
    fold_count: int = 0

    def flat_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "volatility": self.volatility,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
            "turnover": self.turnover,
            "fold_count": self.fold_count,
        }
        record.update(self.parameters)
        return record
