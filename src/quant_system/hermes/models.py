from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    RootModel,
    model_validator,
)

HermesArtifactKind = Literal["portfolio_risk", "prediction", "market_foresight"]
HermesArtifactQuality = Literal[
    "available",
    "degraded",
    "not_applicable",
    "unavailable",
]
HermesArtifactReadStatus = Literal["empty", "available", "degraded", "unavailable"]
HermesArtifactSourceStatus = Literal["available", "empty", "degraded", "unavailable"]
ShortCode = Annotated[str, Field(min_length=1, max_length=200)]
LimitationText = Annotated[str, Field(min_length=1, max_length=500)]


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class HermesRiskBeta(_StrictPayload):
    aligned_return_count: int = Field(ge=0)
    benchmark: str = Field(min_length=1, max_length=16)
    first_return_date: date | None
    last_return_date: date | None
    reason: str | None = Field(max_length=500)
    status: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=16)
    value: FiniteFloat | None


class HermesPortfolioRiskData(_StrictPayload):
    account_id: str | None = Field(max_length=128)
    currency: str | None = Field(max_length=16)
    gross_value: FiniteFloat | None = Field(ge=0)
    gross_pct_equity: FiniteFloat | None = Field(ge=0)
    largest_symbol: str | None = Field(max_length=16)
    top1_gross_pct: FiniteFloat | None = Field(ge=0, le=1)
    historical_status: str | None = Field(max_length=64)
    benchmark: str | None = Field(max_length=16)
    betas: list[HermesRiskBeta] = Field(max_length=100)
    reason_codes: list[ShortCode] = Field(max_length=100)
    limitations: list[LimitationText] = Field(max_length=100)


class HermesPredictionData(_StrictPayload):
    prediction_id: str = Field(min_length=1, max_length=128)
    state: str = Field(min_length=1, max_length=64)
    symbol: str = Field(min_length=1, max_length=16)
    direction: Literal["up", "down", "flat"]
    confidence: FiniteFloat = Field(ge=0, le=1)
    horizon_date: date
    rationale: str = Field(max_length=4000)
    outcome_return: FiniteFloat | None
    direction_brier: FiniteFloat | None = Field(ge=0, le=1)


class HermesForesightCandidate(_StrictPayload):
    id: str = Field(min_length=1, max_length=256)
    symbol: str = Field(min_length=1, max_length=16)
    direction: Literal["up", "down", "flat"]
    confidence: FiniteFloat = Field(ge=0, le=1)
    horizon_date: date
    falsifier: str = Field(min_length=1, max_length=2000)
    rationale: str = Field(max_length=4000)
    entry_session_date: date
    entry_close: FiniteFloat = Field(gt=0)
    provider: Literal["futu"]
    adjustment: Literal["qfq"]
    proposal_only: Literal[True]
    requires_human_confirmation: Literal[True]
    trading_allowed: Literal[False]


class HermesMarketForesightData(_StrictPayload):
    run_id: str = Field(min_length=1, max_length=256)
    summary: str = Field(min_length=1, max_length=1000)
    candidate_count: int = Field(ge=0, le=100)
    candidates: list[HermesForesightCandidate] = Field(max_length=100)

    @model_validator(mode="after")
    def candidate_count_matches(self) -> HermesMarketForesightData:
        if self.candidate_count != len(self.candidates):
            raise ValueError("candidate_count must match candidates")
        return self


class _HermesArtifactItemBase(_StrictPayload):
    id: str = Field(min_length=1, max_length=256)
    occurred_at: str = Field(min_length=1, max_length=64)
    quality: HermesArtifactQuality
    status: str = Field(min_length=1, max_length=64)


class HermesPortfolioRiskItem(_HermesArtifactItemBase):
    kind: Literal["portfolio_risk"]
    data: HermesPortfolioRiskData


class HermesPredictionItem(_HermesArtifactItemBase):
    kind: Literal["prediction"]
    data: HermesPredictionData


class HermesMarketForesightItem(_HermesArtifactItemBase):
    kind: Literal["market_foresight"]
    data: HermesMarketForesightData


HermesArtifactItem = Annotated[
    HermesPortfolioRiskItem | HermesPredictionItem | HermesMarketForesightItem,
    Field(discriminator="kind"),
]


class HermesArtifactItemResponse(RootModel[HermesArtifactItem]):
    pass


class HermesArtifactSourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: HermesArtifactKind
    status: HermesArtifactSourceStatus
    latest_at: str | None
    reason_code: str | None


class HermesArtifactWarningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    code: str


class HermesArtifactFeedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    read_status: HermesArtifactReadStatus
    as_of: str | None
    items: list[HermesArtifactItemResponse]
    sources: list[HermesArtifactSourceResponse]
    warnings: list[HermesArtifactWarningResponse]
