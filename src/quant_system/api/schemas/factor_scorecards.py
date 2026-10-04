from typing import Any, Literal

from pydantic import BaseModel, Field


class FactorScorecardRefreshRequest(BaseModel):
    """Owner-triggered refresh inputs; defaults mirror ``scorecard_service``."""

    provider: str = "futu"
    universe_id: str = "etf"
    start: str = "2024-01-02"
    end: str = "2024-12-31"
    benchmark_symbol: str = "SPY"
    horizons: list[int] = Field(default_factory=lambda: [1, 5, 21])
    quantiles: int = 5
    lookback: int = 20


class FactorScorecardsResponse(BaseModel):
    """Stored factor scorecard payload (``latest.json``) plus live run overlays.

    The heavy per-factor blocks stay opaque dictionaries so the read path can pass
    the stored scorecard through unchanged; the named fields mirror the scorecard
    top level exactly, keeping the named-contract guarantee of the sibling routes.
    """

    schema_version: str | None = None
    status: Literal["ready", "partial", "unavailable", "updating"]
    generated_at: str | None = None
    stale: bool = False
    reason: str | None = None
    methodology: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    factors: list[dict[str, Any]] = Field(default_factory=list)
    run: dict[str, Any] | None = None
    progress: str = ""
    data_acceptance: dict[str, Any] | None = None
    wide_run: dict[str, Any] | None = None
    factor_catalog: list[dict[str, Any]] = Field(default_factory=list)
    factor_coverage: list[dict[str, Any]] = Field(default_factory=list)
    operation: dict[str, Any] | None = None
    error: str | None = None
