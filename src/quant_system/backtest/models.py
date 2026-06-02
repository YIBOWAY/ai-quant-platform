from __future__ import annotations

from enum import StrEnum
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class FillStatus(StrEnum):
    FILLED = "filled"
    PARTIAL = "partial"


class RebalanceFrequency(StrEnum):
    """How often the engine acts on the strategy's target weights.

    ``EVERY_BAR`` reproduces the original behavior (rebalance on every bar that
    has a signal). ``WEEKLY`` / ``MONTHLY`` only rebalance on the first signalled
    bar of a new ISO week / calendar month and hold the prior positions in
    between (mark-to-market only).
    """

    EVERY_BAR = "every_bar"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class BacktestConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    initial_cash: float = Field(default=100_000.0, ge=0)
    commission_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    execution_price: Literal["next_open"] = "next_open"
    min_order_value: float = Field(default=0.0, ge=0)
    annualization_factor: int = Field(default=252, gt=0)
    # Engine-depth controls. All default to the original behavior so existing
    # runs and stored artifacts are byte-stable.
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.EVERY_BAR
    max_weight_per_symbol: float | None = Field(default=None)
    sector_cap: float | None = Field(default=None)
    sector_map: dict[str, str] = Field(default_factory=dict)

    @field_validator("max_weight_per_symbol", "sector_cap")
    @classmethod
    def _validate_cap(cls, value: float | None) -> float | None:
        if value is not None and not (0.0 < value <= 1.0):
            raise ValueError("weight caps must be in the interval (0, 1]")
        return value


class TargetWeight(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: pd.Timestamp
    symbol: str
    target_weight: float
    reason: str = ""


class Order(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    order_id: str
    timestamp: pd.Timestamp
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    reason: str = ""


class Fill(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    fill_id: str
    order_id: str
    timestamp: pd.Timestamp
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    requested_price: float = Field(gt=0)
    fill_price: float = Field(gt=0)
    gross_value: float = Field(ge=0)
    commission: float = Field(ge=0)
    slippage_bps: float = Field(ge=0)
    status: FillStatus = FillStatus.FILLED
