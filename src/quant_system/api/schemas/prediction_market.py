from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PredictionMarketScanRequest(BaseModel):
    provider: Literal["sample", "polymarket"] = "sample"
    min_edge_bps: float = Field(default=200.0, ge=0)
    max_capital_per_leg: float = Field(default=1_000.0, ge=0)
    capital_limit: float = Field(default=1_000.0, ge=0)
    max_legs: int = Field(default=3, ge=1)
    max_markets: int = Field(default=50, ge=1)
    fee_bps: float = Field(default=0.0, ge=0)
    polymarket_api_key: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PredictionMarketDryArbitrageRequest(PredictionMarketScanRequest):
    optimizer: Literal["greedy"] = "greedy"
