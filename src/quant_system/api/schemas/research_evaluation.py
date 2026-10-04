from typing import Any, Literal

from pydantic import BaseModel, Field

RESEARCH_KEY_PATTERN = r"^research:(?:artifact-[a-zA-Z0-9_-]+|strategy-[0-9a-f]{24})$"


class ResearchEvaluationRequest(BaseModel):
    key: str | None = Field(default=None, pattern=RESEARCH_KEY_PATTERN)


class ResearchEvaluationResponse(BaseModel):
    status: Literal["not_started", "updating", "ready", "partial", "failed", "stale"]
    key: str | None = None
    run_id: str | None = None
    updated_at: str | None = None
    input_digest: str | None = None
    source_digest: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    reference: dict[str, Any] | None = None
    rolling: dict[str, Any] | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    progress: str = ""


class PaperEvaluationResponse(BaseModel):
    status: str
    as_of: str | None = None
    updated_at: str | None = None
    input_digest: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] | None = None
    error: str | None = None
    facts_status: str | None = None
    interpretation_status: str | None = None
    fact_archive_status: str | None = None
    fact_archive: dict[str, Any] | None = None
