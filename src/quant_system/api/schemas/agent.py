from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str
    artifact_type: str
    status: str
    goal: str | None = None


class AgentCandidatesResponse(BaseModel):
    candidates: list[CandidateSummary]


class AgentCandidateDetailResponse(BaseModel):
    candidate_id: str
    metadata: dict[str, Any]
    source_preview: str
    audit: list[str]
    reviews: list[str]


class AgentTaskRequest(BaseModel):
    task_type: Literal[
        "propose-factor",
        "propose-experiment",
        "summarize",
        "audit-leakage",
    ]
    goal: str = ""
    universe: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    experiment_id: str | None = None
    factor_id: str | None = None


class AgentTaskResponse(BaseModel):
    candidate_id: str
    status: str
    path: str
    metadata: dict[str, Any]


class AgentReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str


class AgentReviewResponse(BaseModel):
    candidate_id: str
    decision: Literal["approve", "reject"]
    registration: Literal["manual_required"]


class AgentLLMConfigResponse(BaseModel):
    provider: str
    model: str
    base_url: str
    timeout: int
    has_api_key: bool
