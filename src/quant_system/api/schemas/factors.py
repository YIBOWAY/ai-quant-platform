from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from quant_system.factors.base import FactorMetadata


class FactorCatalogResponse(BaseModel):
    factors: list[FactorMetadata]


class FactorRunSummary(BaseModel):
    id: str
    source: str
    row_count: int
    signal_count: int
    paths: dict[str, Any]


class FactorRunsResponse(BaseModel):
    runs: list[FactorRunSummary]


class FactorRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"] = "futu"
    lookback: int = Field(default=20, gt=0)
    quantiles: int = Field(default=5, ge=2)
