from __future__ import annotations

from pydantic import BaseModel, Field


class PaperRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY"])
    start: str
    end: str
    enable_kill_switch: bool = True
    initial_cash: float = Field(default=100_000.0, ge=0)
    max_fill_ratio_per_tick: float = Field(default=1.0, gt=0, le=1)
