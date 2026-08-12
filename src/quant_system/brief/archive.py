from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

ArchiveKind = Literal["daily", "weekly", "monthly"]

_SNIPPET_LIMIT = 80


@dataclass(frozen=True)
class BriefArchiveRow:
    """Storage-level row: one published issue plus its latest snapshot text."""

    public_id: str
    issue_date: date
    title: str | None
    lede: str | None


@dataclass(frozen=True)
class BriefArchiveEntry:
    public_id: str
    issue_date: date
    title: str
    snippet: str
    kind: ArchiveKind
    iso_week: str | None = None
    month: str | None = None


@dataclass(frozen=True)
class BriefArchiveGroup:
    """Entries sharing one display bucket ("2026-08" for daily/weekly, "2026" for monthly)."""

    key: str
    entries: tuple[BriefArchiveEntry, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BriefArchiveView:
    daily: tuple[BriefArchiveGroup, ...]
    weekly: tuple[BriefArchiveGroup, ...]
    monthly: tuple[BriefArchiveGroup, ...]


def archive_range_start(today: date, months: int) -> date:
    """First day of the month ``months - 1`` before ``today``'s month."""
    safe_months = max(1, int(months))
    absolute_month = today.year * 12 + (today.month - 1) - (safe_months - 1)
    year, month_zero = divmod(absolute_month, 12)
    return date(year, month_zero + 1, 1)


def build_archive_view(rows: list[BriefArchiveRow]) -> BriefArchiveView:
    """Build daily/weekly/monthly archive groups over stored daily issues.

    Weekly and monthly tabs are VIEWS over daily snapshots: the weekly entry
    for an ISO week is the last daily issue published inside that week; the
    monthly entry is the last daily issue of that calendar month. No extra
    storage is involved.
    """
    ordered = sorted(rows, key=lambda row: row.issue_date, reverse=True)

    daily_entries = [_entry(row, kind="daily") for row in ordered]
    weekly_entries = [
        _entry(row, kind="weekly", iso_week=_iso_week_key(row.issue_date))
        for row in _last_per_key(ordered, lambda row: row.issue_date.isocalendar()[:2])
    ]
    monthly_entries = [
        _entry(row, kind="monthly", month=f"{row.issue_date.year}-{row.issue_date.month:02d}")
        for row in _last_per_key(
            ordered, lambda row: (row.issue_date.year, row.issue_date.month)
        )
    ]

    return BriefArchiveView(
        daily=_group_by_month(daily_entries),
        weekly=_group_by_month(weekly_entries),
        monthly=_group_by_year(monthly_entries),
    )


def _entry(
    row: BriefArchiveRow,
    *,
    kind: ArchiveKind,
    iso_week: str | None = None,
    month: str | None = None,
) -> BriefArchiveEntry:
    return BriefArchiveEntry(
        public_id=row.public_id,
        issue_date=row.issue_date,
        title=(row.title or "").strip() or row.public_id,
        snippet=_snippet(row.lede),
        kind=kind,
        iso_week=iso_week,
        month=month,
    )


def _snippet(lede: str | None) -> str:
    text = (lede or "").strip()
    if len(text) <= _SNIPPET_LIMIT:
        return text
    return text[: _SNIPPET_LIMIT - 1].rstrip() + "…"


def _iso_week_key(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _last_per_key(
    ordered_rows: list[BriefArchiveRow],
    key_fn,
) -> list[BriefArchiveRow]:
    """Keep the first row per key; input is date-desc so first == latest."""
    seen: set[object] = set()
    selected: list[BriefArchiveRow] = []
    for row in ordered_rows:
        key = key_fn(row)
        if key in seen:
            continue
        seen.add(key)
        selected.append(row)
    return selected


def _group_by_month(entries: list[BriefArchiveEntry]) -> tuple[BriefArchiveGroup, ...]:
    groups: dict[str, list[BriefArchiveEntry]] = {}
    for entry in entries:
        key = f"{entry.issue_date.year}-{entry.issue_date.month:02d}"
        groups.setdefault(key, []).append(entry)
    return tuple(
        BriefArchiveGroup(key=key, entries=tuple(groups[key]))
        for key in sorted(groups, reverse=True)
    )


def _group_by_year(entries: list[BriefArchiveEntry]) -> tuple[BriefArchiveGroup, ...]:
    groups: dict[str, list[BriefArchiveEntry]] = {}
    for entry in entries:
        key = f"{entry.issue_date.year}"
        groups.setdefault(key, []).append(entry)
    return tuple(
        BriefArchiveGroup(key=key, entries=tuple(groups[key]))
        for key in sorted(groups, reverse=True)
    )
