from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReversalMomentumReplicationDetailResponse(BaseModel):
    run_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class ReversalMomentumReplicationRunResponse(BaseModel):
    paper: dict[str, Any]
    methodology: dict[str, Any]
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    monthly_returns: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    legs: list[dict[str, Any]]
    warnings: list[str]
    run_id: str
    kind: str = "replication"
    status: str = "completed"
    created_at: str | None = None
    result_type: str
    source: str
    request: dict[str, Any]
    paths: dict[str, Any]
    artifact_path: str
