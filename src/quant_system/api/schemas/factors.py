from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from quant_system.factors.base import FactorMetadata
from quant_system.universe.registry import UniverseDefinition


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


FactorLabRecord = dict[str, Any]


class FactorLabCrossSectional(BaseModel):
    engine: str
    rows: list[FactorLabRecord]


class FactorLabTiming(BaseModel):
    engine: str
    symbol: str
    rows: list[FactorLabRecord]


class FactorLabResponse(BaseModel):
    generated_at: str | None = None
    source: str
    benchmark_symbol: str
    universe: UniverseDefinition
    factors: list[FactorMetadata]
    guardrails: dict[str, Any]
    cache: dict[str, Any]
    cross_sectional: FactorLabCrossSectional
    timing: FactorLabTiming


FactorRunRecord = dict[str, Any]


class FactorRunDetailResponse(BaseModel):
    run_id: str
    metadata: dict[str, Any]
    factor_results: list[FactorRunRecord]
    signals: list[FactorRunRecord]
    information_coefficients: list[FactorRunRecord]
    quantile_returns: list[FactorRunRecord]


class FactorRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"] = "futu"
    lookback: int = Field(default=20, gt=0)
    quantiles: int = Field(default=5, ge=2)
