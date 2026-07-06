from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from quant_system.factors.base import FactorMetadata
from quant_system.universe.registry import UniverseDefinition


class FactorCatalogItem(FactorMetadata):
    """Factor metadata plus catalog provenance.

    ``origin`` is additive and always present: ``builtin`` for example factors,
    ``promoted`` for code-reviewed promoted-library factors, ``candidate`` for
    human-approved agent candidates surfaced only when
    ``GET /factors?include_candidates=true``.
    """

    origin: Literal["builtin", "promoted", "candidate"]


class FactorCatalogResponse(BaseModel):
    factors: list[FactorCatalogItem]


class FactorRunSummary(BaseModel):
    id: str
    source: str
    row_count: int
    signal_count: int
    paths: dict[str, Any]


class FactorRunsResponse(BaseModel):
    runs: list[FactorRunSummary]


class FactorRunRequestEchoResponse(BaseModel):
    symbols: list[str]
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"]
    lookback: int
    quantiles: int


class FactorRunPathsResponse(BaseModel):
    factor_results: str
    signals: str
    ic: str
    quantiles: str
    report: str


class FactorRunResponse(BaseModel):
    run_id: str
    kind: str = "factor"
    status: str = "completed"
    created_at: str | None = None
    source: str
    row_count: int
    signal_count: int
    warnings: list[str]
    request: FactorRunRequestEchoResponse
    paths: FactorRunPathsResponse


FactorLabRecord = dict[str, Any]


class FactorLabCrossSectional(BaseModel):
    engine: str
    rows: list[FactorLabRecord]


class FactorLabTiming(BaseModel):
    engine: str
    symbol: str
    rows: list[FactorLabRecord]


class FactorLabWalkForwardResponse(BaseModel):
    enabled: bool
    train_bars: int
    validation_bars: int
    step_bars: int
    fold_count: int


class FactorLabLeakageAuditResponse(BaseModel):
    status: Literal["basic_passed", "failed", "empty"]
    checked: bool
    rule: str | None = None


class FactorLabGuardrailsResponse(BaseModel):
    exploratory_only: bool
    warning: str
    walk_forward: FactorLabWalkForwardResponse
    leakage_audit: FactorLabLeakageAuditResponse


class FactorLabCacheKeyResponse(BaseModel):
    provider: str
    universe_id: str
    symbol: str
    benchmark_symbol: str
    start: str
    end: str
    lookback: int


class FactorLabCacheResponse(BaseModel):
    status: Literal["cached", "recomputed"]
    path: str
    key: FactorLabCacheKeyResponse


class FactorLabResponse(BaseModel):
    generated_at: str | None = None
    source: str
    benchmark_symbol: str
    universe: UniverseDefinition
    factors: list[FactorMetadata]
    guardrails: FactorLabGuardrailsResponse
    cache: FactorLabCacheResponse
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
