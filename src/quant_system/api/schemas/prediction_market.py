from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PredictionMarketScanRequest(BaseModel):
    provider: Literal["sample", "polymarket"] = "sample"
    cache_mode: Literal["prefer_cache", "refresh", "network_only"] = "prefer_cache"
    min_edge_bps: float = Field(default=200.0, ge=0)
    max_capital_per_leg: float = Field(default=1_000.0, ge=0)
    capital_limit: float = Field(default=1_000.0, ge=0)
    max_legs: int = Field(default=3, ge=1)
    max_markets: int = Field(default=50, ge=1)
    fee_bps: float = Field(default=0.0, ge=0)
    history_interval: Literal["1h", "6h", "1d", "max"] = "1d"
    history_fidelity: int = Field(default=60, ge=1)
    polymarket_api_key: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PredictionMarketDryArbitrageRequest(PredictionMarketScanRequest):
    optimizer: Literal["greedy"] = "greedy"


class PredictionMarketCollectRequest(BaseModel):
    provider: Literal["sample", "polymarket"] = "sample"
    cache_mode: Literal["prefer_cache", "refresh", "network_only"] = "prefer_cache"
    duration_seconds: float = Field(default=0.0, ge=0)
    interval_seconds: float | None = Field(default=None, gt=0)
    limit: int = Field(default=10, ge=1)
    market_ids: list[str] = Field(default_factory=list)
    polymarket_api_key: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class PredictionMarketTimeseriesBacktestRequest(BaseModel):
    provider: Literal["sample", "polymarket"] = "sample"
    start_time: str | None = None
    end_time: str | None = None
    scanners: list[Literal["yes_no_arbitrage", "outcome_set_consistency"]] = Field(
        default_factory=lambda: ["yes_no_arbitrage", "outcome_set_consistency"]
    )
    min_edge_bps: float = Field(default=200.0, ge=0)
    capital_limit: float = Field(default=1_000.0, gt=0)
    max_legs: int = Field(default=3, ge=1)
    max_markets: int = Field(default=50, ge=1)
    fee_bps: float | None = Field(default=None, ge=0)
    display_size_multiplier: float = Field(default=1.0, gt=0)
    market_ids: list[str] = Field(default_factory=list)
    polymarket_api_key: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
