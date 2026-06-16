from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class BacktestSummary(BaseModel):
    id: str
    source: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class BacktestsResponse(BaseModel):
    backtests: list[BacktestSummary]


class BacktestRunTimingsResponse(BaseModel):
    data_fetch: float
    engine: float
    persist: float
    total: float


class BacktestRunResponse(BaseModel):
    run_id: str
    source: str
    trade_count: int
    order_count: int
    warnings: list[str]
    timings_ms: BacktestRunTimingsResponse
    request: dict[str, Any]
    metrics: dict[str, Any]
    attribution: list[dict[str, Any]]
    benchmark: dict[str, Any]
    paths: dict[str, Any]


BacktestRecord = dict[str, Any]


class BacktestBenchmarkSnapshot(BaseModel):
    symbol: str
    source: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    equity_curve: list[BacktestRecord]


class BacktestDetailResponse(BaseModel):
    id: str
    metadata: dict[str, Any]
    metrics: dict[str, Any]
    equity_curve: list[BacktestRecord]
    benchmark: BacktestBenchmarkSnapshot
    orders: list[BacktestRecord]
    positions: list[BacktestRecord]
    trade_blotter: list[BacktestRecord]
    attribution: list[BacktestRecord]


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
    min_order_value: float = Field(default=0.0, ge=0)
    whole_share_orders: bool = False
    rebalance_frequency: Literal["every_bar", "weekly", "monthly"] = "every_bar"
    max_weight_per_symbol: float | None = Field(default=None, gt=0, le=1)
    sector_cap: float | None = Field(default=None, gt=0, le=1)
    sector_map: dict[str, str] = Field(default_factory=dict)

    @field_validator("symbols", "factor_ids", mode="before")
    @classmethod
    def normalize_string_list(cls, value):
        if value is None:
            return []
        return value

    @model_validator(mode="after")
    def require_sector_map_for_sector_cap(self) -> BacktestRunRequest:
        if self.sector_cap is not None and not self.sector_map:
            raise ValueError("sector_cap requires sector_map")
        return self
