from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ExperimentSummary(BaseModel):
    id: str
    path: str


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class ExperimentRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"], min_length=2)
    start: str
    end: str
    provider: Literal["sample"] = "sample"
    lookbacks: list[PositiveInt] = Field(default_factory=lambda: [3, 5], min_length=1)
    top_ns: list[PositiveInt] = Field(default_factory=lambda: [1, 2], min_length=1)
    initial_cash: NonNegativeFloat = 100_000.0
    commission_bps: NonNegativeFloat = 1.0
    slippage_bps: NonNegativeFloat = 5.0
    rebalance_every_n_bars: PositiveInt = 1
