from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CandidateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    artifact_type: str | None
    goal: str | None
    universe: list[str] | None
    status: Literal["pending", "approved", "rejected"] | None
    integrity_state: Literal["verified", "migration_required", "corrupt"]
    manifest_digest: str | None
    observed_manifest_digest: str | None
    approval_binding: Literal[
        "pending", "approved", "rejected", "legacy_unbound"
    ] | None
    approval_enabled: bool
    integrity_error_code: str | None


class AgentCandidatesResponse(BaseModel):
    candidates: list[CandidateSummary]


class AgentCandidateDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    metadata: dict[str, Any] | None
    source_preview: str | None
    audit: list[str]
    reviews: list[str]
    integrity_state: Literal["verified", "migration_required", "corrupt"]
    manifest_digest: str | None
    observed_manifest_digest: str | None
    approval_binding: Literal[
        "pending", "approved", "rejected", "legacy_unbound"
    ] | None
    approval_enabled: bool
    integrity_error_code: str | None
    status: Literal["pending", "approved", "rejected"] | None


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
    manifest_digest: str | None = None


class AgentReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2000)
    expected_manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_status: Literal["pending"]


class AgentReviewResponse(BaseModel):
    candidate_id: str
    decision: Literal["approve", "reject"]
    registration: Literal["manual_required"]
    manifest_digest: str | None = None


class AgentLLMConfigResponse(BaseModel):
    provider: str
    model: str | None
    base_url: str | None
    timeout: int
    has_api_key: bool
