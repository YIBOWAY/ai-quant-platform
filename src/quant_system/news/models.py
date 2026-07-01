from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class AiHotItem:
    id: str
    title: str
    title_en: str | None
    url: str
    source: str
    published_at: str | None
    summary: str | None
    category: str | None
    score: float | None
    selected: bool | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AiHotItemsPage:
    count: int
    has_next: bool
    next_cursor: str | None
    items: list[AiHotItem]
    warnings: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class AiHotDaily:
    date: str
    generated_at: str | None
    window_start: str | None
    window_end: str | None
    lead: dict[str, Any] | None
    sections: list[dict[str, Any]]
    flashes: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True)
class AiHotDailyIndex:
    date: str
    generated_at: str | None
    lead_title: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AiHotDailiesPage:
    count: int
    items: list[AiHotDailyIndex]
    warnings: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=utc_now_iso)
