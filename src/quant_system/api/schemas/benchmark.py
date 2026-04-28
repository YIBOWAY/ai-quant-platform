from __future__ import annotations

from pydantic import BaseModel


class BenchmarkResponse(BaseModel):
    symbol: str
    equity_curve: list[dict]
    metrics: dict
