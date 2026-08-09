from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictBriefModel(BaseModel):
    # FastAPI supplies ISO date/time fields as strings after JSON decoding, so
    # format parsing remains enabled while unknown fields are rejected.
    model_config = ConfigDict(extra="forbid")


class BriefPriceSource(_StrictBriefModel):
    kind: str = Field(min_length=1)
    as_of: datetime | None


class BriefAccountPosition(_StrictBriefModel):
    symbol: str = Field(min_length=1)
    quantity: float
    avg_cost: float
    last_price: float
    market_value: float
    weight: float
    unrealized_pnl: float
    price_kind: str = Field(min_length=1)
    price_as_of: datetime | None
    previous_close: float | None = None
    day_change_ratio: float | None = None
    day_change_source: str | None = None
    day_change_as_of: datetime | None = None


class BriefAccountSnapshot(_StrictBriefModel):
    account_id: str = Field(min_length=1)
    base_currency: str = Field(min_length=1)
    equity: float
    cash: float
    pnl_abs: float
    pnl_pct: float
    invested_pct: float
    price_source: BriefPriceSource
    positions: list[BriefAccountPosition]


class BriefEquityPoint(_StrictBriefModel):
    timestamp: datetime
    equity: float
    cash: float
    market_value: float
    source: str = Field(min_length=1)


class BriefMarketSnapshot(_StrictBriefModel):
    symbol: str = Field(min_length=1)
    last: float | None
    change_pct: float | None
    source: str | None
    as_of: datetime | None


class BriefAiNewsItem(_StrictBriefModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    source: str = Field(min_length=1)
    published_at: datetime | None
    summary: str | None
    category: str | None
    score: float | None


class BriefHermesLogEntry(_StrictBriefModel):
    timestamp: datetime | None
    status: Literal["ok", "warn"]
    text: str = Field(min_length=1)
    href: str | None
    summary: str | None


class BriefPerformancePoint(_StrictBriefModel):
    date: date
    return_ratio: float
    equity: float | None = None
    close: float | None = None


class BriefPerformanceSeries(_StrictBriefModel):
    id: str = Field(min_length=1)
    kind: Literal["paper", "benchmark"]
    label: str = Field(min_length=1)
    symbol: str | None = None
    status: Literal["available", "partial", "unavailable"]
    source: str | None = None
    as_of: datetime | None = None
    error_code: str | None = None
    points: list[BriefPerformancePoint]


class BriefPerformanceSnapshot(_StrictBriefModel):
    selected_range: Literal["7d", "1m", "3m"]
    master_range: Literal["3m"]
    granularity: Literal["1d"]
    benchmarks: list[Literal["SPY", "QQQ"]]
    requested_start: date
    requested_end: date
    actual_start: date | None = None
    actual_end: date | None = None
    coverage_complete: bool
    series: list[BriefPerformanceSeries]
    warnings: list[str]


class BriefArchivePayload(_StrictBriefModel):
    schema_version: Literal["brief_snapshot_v1"]
    title: str = Field(min_length=1)
    issue_date: date
    locale: Literal["en", "zh"]
    generated_at: datetime
    lede: str = Field(min_length=1)
    account: BriefAccountSnapshot
    paper_equity: list[BriefEquityPoint]
    markets: list[BriefMarketSnapshot]
    market_note: str = Field(min_length=1)
    ai_news: list[BriefAiNewsItem]
    hermes_log: list[BriefHermesLogEntry]
    warnings: list[str]
    performance: BriefPerformanceSnapshot | None = None


class BriefSourceState(_StrictBriefModel):
    name: str = Field(min_length=1)
    status: Literal["available", "stale", "unavailable"]
    as_of: datetime | None
    detail: str | None
    provider: str | None = None
    served_from: str | None = None


class BriefSourceWatermark(_StrictBriefModel):
    captured_at: datetime
    sources: list[BriefSourceState]

    @model_validator(mode="after")
    def validate_unique_source_names(self) -> BriefSourceWatermark:
        names = [source.name for source in self.sources]
        if len(names) != len(set(names)):
            raise ValueError("source watermark names must be unique")
        return self


@dataclass(frozen=True)
class BriefIssue:
    issue_id: str
    public_id: str
    issue_date: date
    locale: str
    status: str


@dataclass(frozen=True)
class BriefSnapshot:
    snapshot_id: str
    version: int
    payload: dict[str, Any]
    source_watermark: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BriefIssueEnvelope:
    issue: BriefIssue
    snapshot: BriefSnapshot
    warnings: list[str] = field(default_factory=list)
