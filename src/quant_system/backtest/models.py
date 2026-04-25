from __future__ import annotations

from enum import StrEnum
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class FillStatus(StrEnum):
    FILLED = "filled"
    PARTIAL = "partial"


class BacktestConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    initial_cash: float = Field(default=100_000.0, ge=0)
    commission_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
    execution_price: Literal["next_open"] = "next_open"
    min_order_value: float = Field(default=0.0, ge=0)
    annualization_factor: int = Field(default=252, gt=0)


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
