from __future__ import annotations

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    start: str
    end: str
    lookback: int = Field(default=20, gt=0)
    top_n: int = Field(default=3, gt=0)
    initial_cash: float = Field(default=100_000.0, ge=0)
    commission_bps: float = Field(default=1.0, ge=0)
    slippage_bps: float = Field(default=5.0, ge=0)
