from __future__ import annotations

from typing import Any, Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class FactorContext(BaseModel):
    """Point-in-time inputs needed by factor implementations."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    prices: pd.DataFrame
    universe: pd.DataFrame
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyContext(BaseModel):
    """Inputs visible to strategies; intentionally contains no broker handle."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: pd.Timestamp
    prices: pd.DataFrame
    positions: pd.Series
    metadata: dict[str, Any] = Field(default_factory=dict)


class TargetPosition(BaseModel):
    """Strategy output consumed later by portfolio, risk, and execution layers."""

    asset: str
    target_weight: float | None = None
    target_quantity: float | None = None
    reason: str = ""


class RiskModel(BaseModel):
    """Placeholder risk model contract for future portfolio optimizers."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = "empty-risk-model"
    payload: dict[str, Any] = Field(default_factory=dict)


class Constraint(BaseModel):
    """Generic optimization constraint placeholder."""

    name: str
    payload: dict[str, Any] = Field(default_factory=dict)


class Factor(Protocol):
    factor_id: str
    factor_version: str
    lookback: int

    def compute(self, ctx: FactorContext) -> pd.Series:
        """Return factor values indexed by asset and timestamp."""


class Strategy(Protocol):
    strategy_id: str
    strategy_version: str

    def on_bar(self, ctx: StrategyContext) -> list[TargetPosition]:
        """Return desired target positions without creating orders."""


class PortfolioOptimizer(Protocol):
    def solve(
        self,
        expected_returns: pd.Series,
        risk_model: RiskModel,
        constraints: list[Constraint],
    ) -> pd.Series:
        """Return target weights; execution remains outside the optimizer."""

