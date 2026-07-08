from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class BriefIssue:
    issue_id: str
    public_id: str
    issue_date: date
    locale: str
    status: str


@dataclass(frozen=True)
class BriefSnapshot:
    snapshot_id: str
    version: int
    payload: dict[str, Any]
    source_watermark: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BriefIssueEnvelope:
    issue: BriefIssue
    snapshot: BriefSnapshot
    warnings: list[str] = field(default_factory=list)
