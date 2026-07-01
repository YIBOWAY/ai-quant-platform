from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AiHotResearchSafety(BaseModel):
    research_only: bool = True
    not_investment_advice: bool = True
    does_not_trigger_trading: bool = True
    verify_original_source: bool = True


class AiHotItemResponse(BaseModel):
    id: str
    title: str
    title_en: str | None = None
    url: str
    source: str
    published_at: str | None = None
    summary: str | None = None
    category: str | None = None
    score: float | None = None
    selected: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AiHotItemsResponse(BaseModel):
    provider: str
    provider_beta: bool
    fetched_at: str
    count: int
    has_next: bool
    next_cursor: str | None = None
    items: list[AiHotItemResponse]
    warnings: list[str] = Field(default_factory=list)
    research_safety: AiHotResearchSafety = Field(default_factory=AiHotResearchSafety)


class AiHotDailyResponse(BaseModel):
    provider: str
    provider_beta: bool
    fetched_at: str
    date: str
    generated_at: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    lead: dict[str, Any] | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    flashes: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    research_safety: AiHotResearchSafety = Field(default_factory=AiHotResearchSafety)
    raw: dict[str, Any] = Field(default_factory=dict)


class AiHotDailyIndexResponse(BaseModel):
    date: str
    generated_at: str | None = None
    lead_title: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class AiHotDailiesResponse(BaseModel):
    provider: str
    provider_beta: bool
    fetched_at: str
    count: int
    items: list[AiHotDailyIndexResponse]
    warnings: list[str] = Field(default_factory=list)
    research_safety: AiHotResearchSafety = Field(default_factory=AiHotResearchSafety)


class AiHotStatusResponse(BaseModel):
    provider: str
    provider_beta: bool
    enabled: bool
    base_url: str
    timeout_seconds: int
    cache_ttl_seconds: int
    last_error: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    research_safety: AiHotResearchSafety = Field(default_factory=AiHotResearchSafety)
