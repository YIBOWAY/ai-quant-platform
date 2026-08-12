from __future__ import annotations

from datetime import date

import pytest

from quant_system.brief.archive import (
    BriefArchiveRow,
    archive_range_start,
    build_archive_view,
)
from quant_system.brief.service import BriefService


def _row(day: date, title: str | None = None, lede: str | None = None) -> BriefArchiveRow:
    return BriefArchiveRow(
        public_id=f"brf_{day:%Y%m%d}_t",
        issue_date=day,
        title=title if title is not None else f"晨报 {day:%m-%d}",
        lede=lede if lede is not None else f"{day.isoformat()} 的导语。",
    )


class TestArchiveRangeStart:
    def test_same_month_when_months_is_one(self) -> None:
        assert archive_range_start(date(2026, 8, 12), 1) == date(2026, 8, 1)

    def test_spans_year_boundary(self) -> None:
        assert archive_range_start(date(2026, 2, 10), 3) == date(2025, 12, 1)

    def test_months_is_clamped_to_at_least_one(self) -> None:
        assert archive_range_start(date(2026, 8, 12), 0) == date(2026, 8, 1)


class TestBuildArchiveView:
    def test_daily_groups_by_month_desc_with_desc_entries(self) -> None:
        rows = [
            _row(date(2026, 8, 3)),
            _row(date(2026, 8, 11)),
            _row(date(2026, 7, 31)),
            _row(date(2026, 7, 1)),
        ]
        view = build_archive_view(rows)
        assert [group.key for group in view.daily] == ["2026-08", "2026-07"]
        august = view.daily[0]
        assert [entry.issue_date for entry in august.entries] == [
            date(2026, 8, 11),
            date(2026, 8, 3),
        ]
        assert all(entry.kind == "daily" for group in view.daily for entry in group.entries)

    def test_weekly_keeps_last_daily_issue_of_each_iso_week(self) -> None:
        # 2026-08-03 .. 2026-08-09 is ISO week 32; the last stored issue of
        # that week (Saturday 08-08) must win, not an earlier weekday.
        rows = [
            _row(date(2026, 8, 4)),
            _row(date(2026, 8, 8)),
            _row(date(2026, 8, 11)),  # ISO week 33
        ]
        view = build_archive_view(rows)
        weekly = [entry for group in view.weekly for entry in group.entries]
        assert [(e.issue_date, e.iso_week) for e in weekly] == [
            (date(2026, 8, 11), "2026-W33"),
            (date(2026, 8, 8), "2026-W32"),
        ]
        assert all(entry.kind == "weekly" for entry in weekly)

    def test_weekly_iso_week_labels_follow_iso_year_at_boundaries(self) -> None:
        # 2026-01-01 is ISO week 1 of 2026; 2025-12-29..31 belong to 2025-W53? No:
        # 2025-12-29 is Monday of ISO week 2026-W01. Verify the tag uses the ISO year.
        rows = [_row(date(2025, 12, 30)), _row(date(2026, 1, 2))]
        view = build_archive_view(rows)
        weekly = [entry for group in view.weekly for entry in group.entries]
        assert len(weekly) == 1
        assert weekly[0].issue_date == date(2026, 1, 2)
        assert weekly[0].iso_week == "2026-W01"

    def test_monthly_keeps_last_daily_issue_of_each_month(self) -> None:
        rows = [
            _row(date(2026, 7, 2)),
            _row(date(2026, 7, 30)),
            _row(date(2026, 8, 5)),
        ]
        view = build_archive_view(rows)
        monthly = [entry for group in view.monthly for entry in group.entries]
        assert [(e.issue_date, e.month) for e in monthly] == [
            (date(2026, 8, 5), "2026-08"),
            (date(2026, 7, 30), "2026-07"),
        ]
        assert [group.key for group in view.monthly] == ["2026"]
        assert all(entry.kind == "monthly" for entry in monthly)

    def test_empty_rows_yield_empty_groups(self) -> None:
        view = build_archive_view([])
        assert view.daily == () and view.weekly == () and view.monthly == ()

    def test_missing_title_falls_back_to_public_id_and_lede_snippet_truncates(self) -> None:
        long_lede = "导" * 200
        view = build_archive_view([_row(date(2026, 8, 11), title="  ", lede=long_lede)])
        entry = view.daily[0].entries[0]
        assert entry.title == "brf_20260811_t"
        assert entry.snippet.endswith("…")
        assert len(entry.snippet) == 80


class _RowRepository:
    def __init__(self, rows: list[BriefArchiveRow]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def list_issue_archive_rows(self, **kwargs: object) -> list[BriefArchiveRow]:
        self.calls.append(kwargs)
        return self.rows


class TestListArchiveService:
    def test_clamps_months_and_passes_range_to_repository(self) -> None:
        repository = _RowRepository([_row(date(2026, 8, 11))])
        view = BriefService(repository).list_archive(
            locale=" zh ",
            months=99,
            today=date(2026, 8, 12),
        )
        assert repository.calls == [
            {
                "locale": "zh",
                "start": date(2024, 9, 1),  # clamped to 24 months
                "end": date(2026, 8, 12),
            }
        ]
        assert view.daily[0].entries[0].public_id == "brf_20260811_t"

    def test_defaults_to_zh_locale_and_three_months(self) -> None:
        repository = _RowRepository([])
        BriefService(repository).list_archive(locale=" ", today=date(2026, 8, 12))
        assert repository.calls == [
            {"locale": "zh", "start": date(2026, 6, 1), "end": date(2026, 8, 12)}
        ]

    @pytest.mark.parametrize("locale", ["zh", "en"])
    def test_groups_reflect_repository_rows(self, locale: str) -> None:
        rows = [
            _row(date(2026, 8, 3)),
            _row(date(2026, 8, 10)),
        ]
        view = BriefService(_RowRepository(rows)).list_archive(
            locale=locale, months=3, today=date(2026, 8, 12)
        )
        assert len(view.daily[0].entries) == 2
        assert len([e for g in view.weekly for e in g.entries]) == 2  # different ISO weeks
        assert len([e for g in view.monthly for e in g.entries]) == 1  # same month
