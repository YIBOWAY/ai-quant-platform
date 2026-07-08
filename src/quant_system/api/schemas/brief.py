from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class BriefGenerateRequest(BaseModel):
    issue_date: date | None = None
    locale: str = "zh"


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
