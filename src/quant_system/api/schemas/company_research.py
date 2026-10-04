"""Read-only evidence contract for company research, never an activation signal."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CompanyResearchSection(BaseModel):
    key: str
    label: str
    status: Literal["available", "empty", "unavailable"]
    provider: str
    operation: str
    fetched_at: str
    source_url: str
    raw_sha256: str | None = None
    reason: str | None = None
    data: Any = None


class CompanyResearchRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=32)


class CompanyResearchResponse(BaseModel):
    schema_version: Literal[1] = 1
    symbol: str
    status: Literal["not_loaded", "updating", "available", "partial", "failed"]
    updated_at: str | None = None
    snapshot_id: str | None = None
    stale: bool = False
    source_policy: str = "Futu 优先报价，Longbridge 备用；公司资料与财务来自 Longbridge"
    headline: str
    summary: list[str] = Field(default_factory=list)
    sections: list[CompanyResearchSection] = Field(default_factory=list)
    financials: dict[str, Any] = Field(default_factory=dict)
    research_ideas: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    research_only: Literal[True] = True
    pit_backtest_ready: Literal[False] = False


class DataSourceCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(default="SPY", min_length=1, max_length=32)


class CompanyResearchCompareResponse(BaseModel):
    items: list[CompanyResearchResponse]
    comparison_note: str = "仅并列已保存快照，各公司报告期与抓取时间可能不同；未按收益排名。"


class DataSourceProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    label: str
    status: Literal["available", "empty", "unavailable"]
    reason: str | None = None
    detail: str | None = None


class DataSourceCheckRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["not_checked", "updating", "available", "partial", "failed"]
    checked_at: str | None = None
    symbol: str | None = None
    default_provider: Literal["futu"] = "futu"
    backup_provider: Literal["longbridge"] = "longbridge"
    checks: list[DataSourceProbe] = Field(default_factory=list)
    reason: str | None = None


class DataSourceInstallation(BaseModel):
    provider: Literal["futu", "longbridge"]
    installed: bool
    version: str | None
    status: Literal["configured", "disabled", "installed", "not_installed"]
    reason: str | None


class DataSourcesResponse(DataSourceCheckRecord):
    sources: list[DataSourceInstallation]
