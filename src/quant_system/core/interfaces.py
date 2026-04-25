from __future__ import annotations

from typing import Any, Protocol

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class FactorContext(BaseModel):
    """Point-in-time inputs needed by factor implementations.

    Phase 2 ``BaseFactor`` accepts a long OHLCV DataFrame directly, but newer
    callers may prefer to pass an explicit context that pairs prices with a
    universe definition and free-form metadata.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ohlcv: pd.DataFrame
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
    """Canonical factor contract.

    Implementations such as Phase 2 ``BaseFactor`` consume a long-format OHLCV
    DataFrame and return a long-format factor result frame with columns
    ``symbol, signal_ts, tradeable_ts, factor_id, factor_version, factor_name,
    lookback, value``.
    """

    factor_id: str
    factor_version: str
    lookback: int

    def compute(self, ohlcv: pd.DataFrame) -> pd.DataFrame:
        """Return factor values for every actionable bar."""


class Strategy(Protocol):
    """Canonical strategy contract.

    A strategy converts a per-timestamp view of the market into target
    weights or quantities. It must not place orders; the backtest or paper
    trading engine owns order generation and execution.
    """

    def target_weights(
        self, timestamp: pd.Timestamp
    ) -> list[TargetPosition] | None:
        """Return target positions for the timestamp, or ``None`` to skip."""


class PortfolioOptimizer(Protocol):
    def solve(
        self,
        expected_returns: pd.Series,
        risk_model: RiskModel,
        constraints: list[Constraint],
    ) -> pd.Series:
        """Return target weights; execution remains outside the optimizer."""

