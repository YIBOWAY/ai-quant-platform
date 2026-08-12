from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AiHotResearchSafety(BaseModel):
    research_only: bool = True
    not_investment_advice: bool = True
    does_not_trigger_trading: bool = True
    verify_original_source: bool = True


NewsPreference = Literal["auto", "aihot", "horizon"]
NewsServedFrom = Literal["primary", "failover", "cache", "forced"]


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
    preference: NewsPreference = "auto"
    served_from: NewsServedFrom = "primary"


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
    preference: NewsPreference = "auto"
    served_from: NewsServedFrom = "primary"


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
    preference: NewsPreference = "auto"
    served_from: NewsServedFrom = "primary"


class MarketTopicsResponse(BaseModel):
    """Morning-brief market-topics lane (Polygon primary, Finnhub failover)."""

    provider: str
    provider_beta: bool
    fetched_at: str
    count: int
    has_next: bool = False
    next_cursor: str | None = None
    items: list[AiHotItemResponse]
    warnings: list[str] = Field(default_factory=list)
    research_safety: AiHotResearchSafety = Field(default_factory=AiHotResearchSafety)
    served_from: NewsServedFrom = "primary"
    keywords: list[str] = Field(default_factory=list)


class NewsFailoverStatus(BaseModel):
    auto_enabled: bool = True
    order: list[str] = Field(
        default_factory=lambda: ["aihot_live", "horizon_pg", "aihot_cache"]
    )


class NewsStatusResponse(BaseModel):
    """Aggregated dual-source status (spec §6.5) plus aihot-compat fields."""

    preference_default: NewsPreference = "auto"
    research_only: bool = True
    providers: dict[str, Any] = Field(default_factory=dict)
    failover: NewsFailoverStatus = Field(default_factory=NewsFailoverStatus)
    warnings: list[str] = Field(default_factory=list)
    research_safety: AiHotResearchSafety = Field(default_factory=AiHotResearchSafety)
    # Backward-compatible aihot status fields.
    provider: str = "aihot"
    provider_beta: bool = True
    enabled: bool = True
    base_url: str = ""
    timeout_seconds: int = 0
    cache_ttl_seconds: int = 0
    last_error: dict[str, Any] | None = None


# Keep old name as alias for any external imports.
AiHotStatusResponse = NewsStatusResponse
