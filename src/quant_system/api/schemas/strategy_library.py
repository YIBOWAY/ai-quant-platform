"""Read contracts for saved strategy evidence, including incomplete legacy records."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class StrategyLibraryEntryResponse(BaseModel):
    # Retain existing versioned evidence instead of dropping unknown saved fields.
    # A corrupt-list placeholder genuinely contains only id/title/status; optional
    # fields are omitted on the wire rather than fabricated as complete evidence.
    model_config = ConfigDict(extra="allow")

    strategy_id: str
    title: str
    status: str
    definition_digest: str | None = None
    source_sha256: str | None = None
    definition: dict[str, Any] | None = None
    origin: dict[str, Any] | None = None
    created_at: str | None = None
    validation: dict[str, Any] | None = None
    validation_sha256: str | None = None
    evaluation: dict[str, Any] | None = None
    candidate_id: str | None = None
    sleeve_id: str | None = None
    error: Any = None
    execution_ready: bool | None = None
    activation_blockers: list[str] | None = None


class StrategyLibraryResponse(BaseModel):
    items: list[StrategyLibraryEntryResponse]
    data_needs: list[dict[str, Any]] | None = None
    data_needs_error: str | None = None


class StrategyFactorOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    factor_id: str
    label: str
    expression: str | None
    lookback: int
    direction: Literal["higher_is_better", "lower_is_better"]
    origin: str
    weight: float | None = None
    research_only: bool | None = None
    status: str | None = None
    source_refs: list[dict[str, Any]] | None = None
    source_digest: str | None = None
    note: str | None = None


class StrategyFactorOptionsResponse(BaseModel):
    factors: list[StrategyFactorOption]
