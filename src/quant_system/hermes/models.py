from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    RootModel,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)

HermesArtifactKind = Literal[
    "portfolio_risk",
    "prediction",
    "market_foresight",
    "weekly_review",
    "opportunity_summary",
    "automation_status",
]
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
WeeklyLimitationText = Annotated[str, Field(min_length=1, max_length=200)]
BoundedCount = Annotated[StrictInt, Field(ge=0, le=1_000_000)]
UnitScore = Annotated[
    StrictFloat,
    Field(ge=0, le=1, allow_inf_nan=False),
]


def _require_timestamp_string(value: object) -> object:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be a canonical UTC string ending in Z")
    return value


StrictAwareTimestamp = Annotated[
    AwareDatetime,
    BeforeValidator(_require_timestamp_string),
]


class _StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class _ReadOnlyAggregatePayload(_StrictPayload):
    proposal_only: Literal[True]
    trading_allowed: Literal[False]

    @field_validator("proposal_only", mode="before")
    @classmethod
    def proposal_flag_is_strict_true(cls, value: object) -> object:
        if value is not True:
            raise ValueError("proposal_only must be the boolean true")
        return value

    @field_validator("trading_allowed", mode="before")
    @classmethod
    def trading_flag_is_strict_false(cls, value: object) -> object:
        if value is not False:
            raise ValueError("trading_allowed must be the boolean false")
        return value


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


class HermesWeeklyReviewData(_ReadOnlyAggregatePayload):
    week_id: str = Field(pattern=r"^\d{4}-W\d{2}$")
    period_start: StrictAwareTimestamp
    period_end: StrictAwareTimestamp
    safety_alert_count: BoundedCount
    unique_signal_count: BoundedCount
    review_draft_count: BoundedCount
    review_confirmed_count: BoundedCount
    prediction_created_count: BoundedCount
    prediction_scored_count: BoundedCount
    prediction_hit_count: BoundedCount
    mean_direction_brier: UnitScore | None
    opportunity_observed_count: BoundedCount
    opportunity_missed_count: BoundedCount
    opportunity_coverage_unknown_count: BoundedCount
    limitations: list[WeeklyLimitationText] = Field(max_length=20)

    @model_validator(mode="after")
    def counts_and_period_are_consistent(self) -> HermesWeeklyReviewData:
        if self.period_end - self.period_start != timedelta(days=7):
            raise ValueError("weekly period must be exactly seven days")
        year_text, week_text = self.week_id.split("-W", maxsplit=1)
        year = int(year_text)
        week = int(week_text)
        try:
            date.fromisocalendar(year, week, 1)
        except ValueError as exc:
            raise ValueError("week_id must name a valid ISO week") from exc
        local_year, local_week, _ = self.period_end.astimezone(
            ZoneInfo("Asia/Shanghai")
        ).isocalendar()
        if (year, week) != (local_year, local_week):
            raise ValueError("week_id must match the period end in Asia/Shanghai")
        if self.prediction_hit_count > self.prediction_scored_count:
            raise ValueError("prediction hits cannot exceed scored predictions")
        if (self.prediction_scored_count == 0) != (
            self.mean_direction_brier is None
        ):
            raise ValueError(
                "mean_direction_brier must be null exactly when no predictions were scored"
            )
        return self


class HermesOpportunityResolutionCounts(_StrictPayload):
    open: BoundedCount
    deferred: BoundedCount
    acted: BoundedCount
    action_failed: BoundedCount
    declined: BoundedCount
    missed: BoundedCount
    expired_coverage_unknown: BoundedCount
    not_actionable: BoundedCount
    unknown: BoundedCount

    def total(self) -> int:
        return sum(
            (
                self.open,
                self.deferred,
                self.acted,
                self.action_failed,
                self.declined,
                self.missed,
                self.expired_coverage_unknown,
                self.not_actionable,
                self.unknown,
            )
        )


class HermesOpportunityMissReasonCounts(_StrictPayload):
    no_decision: BoundedCount
    act_without_action: BoundedCount
    defer_expired: BoundedCount

    def total(self) -> int:
        return self.no_decision + self.act_without_action + self.defer_expired


class HermesOpportunitySummaryData(_ReadOnlyAggregatePayload):
    window_start: StrictAwareTimestamp
    window_end: StrictAwareTimestamp
    total_count: BoundedCount
    resolution_counts: HermesOpportunityResolutionCounts
    miss_reason_counts: HermesOpportunityMissReasonCounts

    @model_validator(mode="after")
    def counts_and_window_are_consistent(self) -> HermesOpportunitySummaryData:
        if self.window_end - self.window_start != timedelta(days=7):
            raise ValueError("opportunity window must be exactly seven days")
        if self.resolution_counts.total() != self.total_count:
            raise ValueError("resolution counts must sum to total_count")
        if self.miss_reason_counts.total() != self.resolution_counts.missed:
            raise ValueError("miss reason counts must sum to missed")
        return self


class HermesAutomationJobStatus(_StrictPayload):
    job_id: Literal[
        "daily_close",
        "freshness",
        "weekly",
        "notification_drain",
    ]
    expected_schedule: str = Field(min_length=1, max_length=128)
    timezone: Literal["Asia/Shanghai"]
    freshness_budget_seconds: Annotated[
        StrictInt,
        Field(ge=1, le=10_000_000),
    ]
    last_attempt_at: StrictAwareTimestamp | None
    last_success_at: StrictAwareTimestamp | None
    fresh_until: StrictAwareTimestamp | None
    status: Literal["fresh", "stale", "failed", "never_run"]
    reason_code: str | None = Field(max_length=200)
    last_run_id: str | None = Field(max_length=256)
    notification_status: Literal[
        "delivered",
        "queued",
        "fallback_persisted",
        "not_required",
        "delivery_unknown",
    ]

    @model_validator(mode="after")
    def status_fields_are_consistent(self) -> HermesAutomationJobStatus:
        if self.status == "never_run":
            if any(
                value is not None
                for value in (
                    self.last_attempt_at,
                    self.last_success_at,
                    self.fresh_until,
                    self.last_run_id,
                )
            ):
                raise ValueError("never_run jobs cannot claim a prior run")
            if not self.reason_code:
                raise ValueError("never_run jobs require a reason_code")
            return self
        if self.last_attempt_at is None or self.last_run_id is None:
            raise ValueError("attempted jobs require last_attempt_at and last_run_id")
        if self.status in {"fresh", "stale"} and (
            self.last_success_at is None or self.fresh_until is None
        ):
            raise ValueError("fresh or stale jobs require success freshness timestamps")
        if (self.last_success_at is None) != (self.fresh_until is None):
            raise ValueError("last_success_at and fresh_until must be present together")
        if (
            self.last_success_at is not None
            and self.fresh_until is not None
            and self.fresh_until <= self.last_success_at
        ):
            raise ValueError("fresh_until must be after last_success_at")
        if self.status == "fresh" and self.reason_code is not None:
            raise ValueError("fresh jobs cannot have a reason_code")
        if self.status in {"stale", "failed"} and not self.reason_code:
            raise ValueError("degraded jobs require a reason_code")
        return self


class HermesAutomationStatusData(_ReadOnlyAggregatePayload):
    checked_at: StrictAwareTimestamp
    overall_status: Literal["fresh", "degraded"]
    jobs: list[HermesAutomationJobStatus] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def job_set_and_status_are_consistent(self) -> HermesAutomationStatusData:
        job_ids = [job.job_id for job in self.jobs]
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("automation job ids must be unique")
        if set(job_ids) != {
            "daily_close",
            "freshness",
            "weekly",
            "notification_drain",
        }:
            raise ValueError("automation status must report every full-9H job")
        expected_status = (
            "fresh" if all(job.status == "fresh" for job in self.jobs) else "degraded"
        )
        if self.overall_status != expected_status:
            raise ValueError("overall_status must match job freshness")
        for job in self.jobs:
            if job.last_attempt_at is not None and job.last_attempt_at > self.checked_at:
                raise ValueError("job attempt cannot be later than checked_at")
            if (
                job.last_success_at is not None
                and job.last_attempt_at is not None
                and job.last_success_at > job.last_attempt_at
            ):
                raise ValueError("job success cannot be later than its latest attempt")
            if (
                job.status == "fresh"
                and job.fresh_until is not None
                and self.checked_at > job.fresh_until
            ):
                raise ValueError("fresh job must remain inside its freshness window")
            if (
                job.status == "stale"
                and job.fresh_until is not None
                and self.checked_at <= job.fresh_until
            ):
                raise ValueError("stale job must be outside its freshness window")
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


class HermesWeeklyReviewItem(_HermesArtifactItemBase):
    kind: Literal["weekly_review"]
    data: HermesWeeklyReviewData


class HermesOpportunitySummaryItem(_HermesArtifactItemBase):
    kind: Literal["opportunity_summary"]
    data: HermesOpportunitySummaryData


class HermesAutomationStatusItem(_HermesArtifactItemBase):
    kind: Literal["automation_status"]
    data: HermesAutomationStatusData


HermesArtifactItem = Annotated[
    HermesPortfolioRiskItem
    | HermesPredictionItem
    | HermesMarketForesightItem
    | HermesWeeklyReviewItem
    | HermesOpportunitySummaryItem
    | HermesAutomationStatusItem,
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

    schema_version: Literal["1.0", "1.1"]
    read_status: HermesArtifactReadStatus
    as_of: str | None
    items: list[HermesArtifactItemResponse]
    sources: list[HermesArtifactSourceResponse]
    warnings: list[HermesArtifactWarningResponse]
