from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

HermesResultKind = Literal[
    "backtest",
    "factor",
    "paper",
    "replication",
    "experiment",
    "factor_candidate",
    "portfolio_risk",
    "prediction",
    "market_foresight",
    "weekly_review",
    "opportunity_summary",
    "automation_status",
]
HermesResultSource = Literal[
    "platform_runs",
    "platform_experiments",
    "platform_candidates",
    "hqa_artifact_feed",
]
HermesResultAuthority = Literal[
    "platform_run_artifact",
    "platform_experiment_artifact",
    "platform_candidate_repository",
    "hqa_artifact_manifest",
]
HermesResultFreshness = Literal["fresh", "stale", "not_applicable", "unknown"]
HermesResultItemReadStatus = Literal[
    "available",
    "degraded",
    "missing",
    "corrupt",
    "unavailable",
]
HermesResultAggregateReadStatus = Literal["available", "degraded", "empty", "unavailable"]


class _HermesResultReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HermesResultRunLink(_HermesResultReadModel):
    command_id: str = Field(min_length=1, max_length=64)
    relation: Literal["input", "output", "context"]
    hermes_session_id: str = Field(min_length=1, max_length=256)
    resolved_hermes_session_id: str = Field(min_length=1, max_length=256)
    hermes_run_id: str = Field(min_length=1, max_length=256)
    link_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_event_id: str | None = Field(default=None, min_length=1, max_length=256)
    observed_at: str = Field(min_length=1, max_length=64)


class HermesResultItem(_HermesResultReadModel):
    kind: HermesResultKind
    resource_id: str = Field(min_length=1, max_length=256)
    # Human-readable fields are a bounded read projection only. The resource
    # identity and authoritative payload remain the source of truth.
    display_title: str = Field(min_length=1, max_length=256)
    summary: str | None = Field(default=None, min_length=1, max_length=1000)
    status: str = Field(min_length=1, max_length=128)
    occurred_at: str = Field(min_length=1, max_length=64)
    source: HermesResultSource
    authority: HermesResultAuthority
    freshness: HermesResultFreshness
    read_status: HermesResultItemReadStatus
    detail_href: str = Field(min_length=1, max_length=1000)
    original_href: str = Field(min_length=1, max_length=1000)
    run_links: list[HermesResultRunLink] | None = Field(default=None, max_length=100)


class HermesResultSourceState(_HermesResultReadModel):
    source: str = Field(min_length=1, max_length=128)
    read_status: HermesResultAggregateReadStatus
    item_count: int = Field(ge=0)


class HermesResultWarning(_HermesResultReadModel):
    source: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=128)
    kind: HermesResultKind | None = None
    resource_id: str | None = Field(default=None, min_length=1, max_length=1000)


class HermesResultsResponse(_HermesResultReadModel):
    read_status: HermesResultAggregateReadStatus
    # Null means at least one selected source could not be enumerated exactly.
    # Never present a partial count as an authoritative total.
    total: int | None = Field(default=None, ge=0)
    total_is_exact: bool
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0, le=10_000)
    has_more: bool
    items: list[HermesResultItem] = Field(max_length=100)
    sources: list[HermesResultSourceState] = Field(max_length=32)
    warnings: list[HermesResultWarning] = Field(max_length=200)


class HermesResultDetailResponse(_HermesResultReadModel):
    read_status: HermesResultItemReadStatus
    item: HermesResultItem | None
    resource: dict[str, Any] | None
    warnings: list[HermesResultWarning] = Field(max_length=20)


__all__ = [
    "HermesResultDetailResponse",
    "HermesResultKind",
    "HermesResultSource",
    "HermesResultsResponse",
]
