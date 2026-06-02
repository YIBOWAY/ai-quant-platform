from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class BacktestRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    universe_id: str | None = None
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"] = "futu"
    strategy_id: str = "cross_sectional_top_n"
    factor_ids: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    benchmark_symbol: str = "SPY"
    lookback: int = Field(default=20, gt=0)
    top_n: int = Field(default=3, gt=0)
    initial_cash: float = Field(default=100_000.0, ge=0)
    commission_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)

    @field_validator("symbols", "factor_ids", mode="before")
    @classmethod
    def normalize_string_list(cls, value):
        if value is None:
            return []
        return value
