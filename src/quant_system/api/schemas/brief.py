from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_system.brief.models import BriefArchivePayload, BriefSourceWatermark


class BriefGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_date: date | None = None
    locale: str = "zh"
    payload: BriefArchivePayload
    source_watermark: BriefSourceWatermark

    @model_validator(mode="after")
    def validate_snapshot_identity(self) -> BriefGenerateRequest:
        active_date = self.issue_date or self.payload.issue_date
        active_locale = self.locale.strip() or "zh"
        if active_date != self.payload.issue_date:
            raise ValueError("issue_date must match payload.issue_date")
        if active_locale != self.payload.locale:
            raise ValueError("locale must match payload.locale")
        paper_account = next(
            (
                source
                for source in self.source_watermark.sources
                if source.name == "paper_account"
            ),
            None,
        )
        if paper_account is None or paper_account.status == "unavailable":
            raise ValueError(
                "paper_account must be available or stale before a brief can be archived"
            )
        return self


class BriefIssueResponse(BaseModel):
    issue_id: str
    public_id: str
    issue_date: date
    locale: str
    status: str = "published"


class BriefSnapshotResponse(BaseModel):
    snapshot_id: str
    version: int
    payload: dict[str, Any] = Field(default_factory=dict)
    source_watermark: dict[str, Any] = Field(default_factory=dict)


class BriefIssueEnvelopeResponse(BaseModel):
    issue: BriefIssueResponse
    snapshot: BriefSnapshotResponse
    warnings: list[str] = Field(default_factory=list)


class BriefIssueListResponse(BaseModel):
    items: list[BriefIssueResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 30
    offset: int = 0


class BriefArchiveEntryResponse(BaseModel):
    public_id: str
    issue_date: date
    title: str
    snippet: str = ""
    kind: Literal["daily", "weekly", "monthly"]
    iso_week: str | None = None
    month: str | None = None


class BriefArchiveGroupResponse(BaseModel):
    key: str
    entries: list[BriefArchiveEntryResponse] = Field(default_factory=list)


class BriefArchiveViewResponse(BaseModel):
    locale: str
    months: int
    daily: list[BriefArchiveGroupResponse] = Field(default_factory=list)
    weekly: list[BriefArchiveGroupResponse] = Field(default_factory=list)
    monthly: list[BriefArchiveGroupResponse] = Field(default_factory=list)


class BriefRollupListItemResponse(BaseModel):
    public_id: str
    kind: str
    period_key: str
    period_start: date
    period_end: date
    locale: str
    status: str
    title: str
    snippet: str = ""


class BriefRollupListResponse(BaseModel):
    items: list[BriefRollupListItemResponse] = Field(default_factory=list)
    total: int = 0
    kind: str
    locale: str


class BriefRollupIssueResponse(BaseModel):
    rollup_id: str
    public_id: str
    kind: str
    period_key: str
    period_start: date
    period_end: date
    locale: str
    status: str = "published"


class BriefRollupSnapshotResponse(BaseModel):
    snapshot_id: str
    version: int
    payload: dict[str, Any] = Field(default_factory=dict)
    source_watermark: dict[str, Any] = Field(default_factory=dict)


class BriefRollupEnvelopeResponse(BaseModel):
    issue: BriefRollupIssueResponse
    snapshot: BriefRollupSnapshotResponse
    warnings: list[str] = Field(default_factory=list)
