from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class AgentTaskType(StrEnum):
    FACTOR_PROPOSAL = "factor_proposal"
    EXPERIMENT_DESIGN = "experiment_design"
    RESULT_SUMMARY = "result_summary"
    LEAKAGE_AUDIT = "leakage_audit"
    REVIEW = "review"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AgentTask(BaseModel):
    task_id: str
    task_type: AgentTaskType
    goal: str
    universe: list[str] = Field(default_factory=list)
    experiment_id: str | None = None
    factor_id: str | None = None
    created_at: str = Field(default_factory=utc_now_iso)


class AgentMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    created_at: str = Field(default_factory=utc_now_iso)


class AgentDecision(BaseModel):
    allowed: bool
    reason: str
    candidate_id: str | None = None
    safety: dict[str, Any] = Field(default_factory=dict)


class CandidateArtifact(BaseModel):
    candidate_id: str
    task_id: str
    artifact_type: str
    path: Path
    metadata_path: Path
    status: CandidateStatus = CandidateStatus.PENDING
    created_at: str = Field(default_factory=utc_now_iso)


class ReviewRecord(BaseModel):
    candidate_id: str
    decision: Literal["approve", "reject"]
    note: str
    reviewer: str = "manual"
    created_at: str = Field(default_factory=utc_now_iso)
