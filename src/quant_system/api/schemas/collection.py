from typing import Literal

from pydantic import BaseModel, Field


class CollectionSourceRef(BaseModel):
    label: str
    path: str
    digest: str


class CollectionIntro(BaseModel):
    status: Literal["missing", "ready", "failed", "source_changed"] = "missing"
    summary: str | None = None
    logic: list[str] = Field(default_factory=list)
    usage: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model: str | None = None
    reasoning_effort: str | None = None
    generated_at: str | None = None
    source_digest: str | None = None
    input_digest: str | None = None
    error: str | None = None


class CollectionEvidence(BaseModel):
    kind: Literal["dual_engine", "backtest", "replication", "factor_lab"]
    engine: str
    status: Literal["verified", "historical", "unavailable"]
    run_id: str | None = None
    source: str | None = None
    start: str | None = None
    end: str | None = None
    created_at: str | None = None
    metrics: dict[str, float | None] = Field(default_factory=dict)
    note: str = ""
    source_ref: str | None = None


class CollectionLink(BaseModel):
    label: str
    href: str


class CollectionComparison(BaseModel):
    status: Literal["accepted", "rejected", "unavailable"]
    daily_return_correlation: float | None = None
    terminal_nav_difference_bps: float | None = None


class CollectionItem(BaseModel):
    key: str
    kind: Literal["research", "strategy", "factor"]
    id: str
    name: str
    name_en: str
    description: str
    implementation_status: Literal["implemented", "draft", "source_unavailable"]
    source_digest: str | None = None
    source_refs: list[CollectionSourceRef] = Field(default_factory=list)
    intro: CollectionIntro = Field(default_factory=CollectionIntro)
    evidence: list[CollectionEvidence] = Field(default_factory=list)
    links: list[CollectionLink] = Field(default_factory=list)
    universe: list[str] = Field(default_factory=list)
    simulation_status: str | None = None
    comparison: CollectionComparison | None = None
    notes: list[str] = Field(default_factory=list)


class CollectionResponse(BaseModel):
    generated_at: str
    items: list[CollectionItem]
    errors: list[str] = Field(default_factory=list)
    excluded_sample_runs: int = 0
