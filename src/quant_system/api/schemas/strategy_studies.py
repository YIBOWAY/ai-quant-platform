"""Purpose-specific research API, separate from candidates and paper execution."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class StrategyStudiesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_discovery: StrictBool = False


class StrategyStudiesResponse(BaseModel):
    status: Literal["not_started", "updating", "ready", "partial", "failed", "stale"]
    run_id: str | None = None
    updated_at: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    protocol_digest: str | None = None
    calculation_digest: str | None = None
    profiles: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)
    discovery: dict[str, Any] | None = None
    progress: str = ""
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    stages: dict[str, Any] = Field(default_factory=dict)
    recovery: dict[str, Any] | None = None


class StrategyStudyProfileResponse(BaseModel):
    run_id: str
    profile_id: str
    profile: dict[str, Any]
    status: str
    signal_dates: list[str] = Field(default_factory=list)
    selected_signal_date: str | None = None
    signals: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    reconciliation: dict[str, Any] = Field(default_factory=dict)
    source: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
