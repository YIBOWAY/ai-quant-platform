from __future__ import annotations

from pydantic import BaseModel, Field


class FactorRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    start: str
    end: str
    lookback: int = Field(default=20, gt=0)
    quantiles: int = Field(default=5, ge=2)
