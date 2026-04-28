from __future__ import annotations

from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    CREATED = "created"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class OrderRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: pd.Timestamp
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    reason: str = ""

    def normalized_symbol(self) -> str:
        return self.symbol.upper().strip()


class ManagedOrder(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    order_id: str
    created_at: pd.Timestamp
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    status: OrderStatus = OrderStatus.CREATED
    filled_quantity: float = Field(default=0.0, ge=0)
    reason: str = ""
    rejected_reason: str = ""

    @property
    def remaining_quantity(self) -> float:
        return max(self.quantity - self.filled_quantity, 0.0)


class OrderEvent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: pd.Timestamp
    order_id: str
    symbol: str
    status: OrderStatus
    message: str = ""


class ExecutionFill(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    fill_id: str
    order_id: str
    timestamp: pd.Timestamp
    symbol: str
    side: OrderSide
    quantity: float = Field(gt=0)
    fill_price: float = Field(gt=0)
    gross_value: float = Field(ge=0)
    commission: float = Field(default=0.0, ge=0)
