from __future__ import annotations

import json
from typing import Any

from quant_system.config.settings import Settings
from quant_system.news import daily_report_repository as repository
from quant_system.news.daily_report_repository import (
    daily_report_cache_warning,
)
from quant_system.news.models import AiHotDaily

ROOT_USER_ID = "00000000-0000-0000-0000-000000000001"


class FakeConnection:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self._row = row

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> FakeConnection:
        self.executions.append((sql, params))
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class FakeDatabase:
    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.connection = FakeConnection(row=row)

    def connect(self) -> FakeConnection:
        return self.connection


class BrokenDatabase:
    def connect(self) -> FakeConnection:
        raise RuntimeError("database is down")


def _daily() -> AiHotDaily:
    return AiHotDaily(
        date="2026-07-08",
        generated_at="2026-07-08T00:01:00+00:00",
        window_start="2026-07-07T00:00:00+00:00",
        window_end="2026-07-08T00:00:00+00:00",
        lead={"title": "Daily lead"},
        sections=[{"label": "Models", "items": [{"title": "Model update"}]}],
        flashes=[{"title": "Flash"}],
        warnings=["live warning"],
        raw={"date": "2026-07-08", "window_start": "2026-07-07T00:00:00+00:00"},
        fetched_at="2026-07-08T08:00:00+00:00",
    )


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def test_daily_report_cache_warning_text_is_stable() -> None:
    assert (
        daily_report_cache_warning("2026-07-08")
        == "Using cached AI HOT daily report for 2026-07-08 from the local database."
    )


def test_cache_aihot_daily_report_upserts_owner_scoped_report(monkeypatch) -> None:
    fake = FakeDatabase()
    monkeypatch.setattr(repository, "get_database", lambda _settings: fake)

    repository.cache_aihot_daily_report(_daily(), settings=Settings())

    assert len(fake.connection.executions) == 1
    sql, params = fake.connection.executions[0]
    compact = _compact(sql)
    assert "INSERT INTO quant_system.ai_news_daily_reports" in compact
    assert "owner_user_id" in compact
    assert "ON CONFLICT (owner_user_id, provider, report_date)" in compact
    assert "ON CONFLICT (provider, report_date)" not in compact

    assert str(params[0]) == ROOT_USER_ID
    assert params[1] == "aihot"
    assert params[2] == "2026-07-08"
    assert params[3] == "2026-07-08T08:00:00+00:00"
    assert params[4] == "2026-07-08T00:01:00+00:00"
    assert json.loads(params[5]) == {"title": "Daily lead"}
    assert json.loads(params[6]) == [
        {"label": "Models", "items": [{"title": "Model update"}]}
    ]
    assert json.loads(params[7]) == [{"title": "Flash"}]
    assert json.loads(params[8]) == ["live warning"]
    assert json.loads(params[9])["date"] == "2026-07-08"
    assert json.loads(params[9])["window_start"] == "2026-07-07T00:00:00+00:00"
    assert json.loads(params[9])["window_end"] == "2026-07-08T00:00:00+00:00"


def test_load_cached_aihot_daily_report_returns_daily_with_cache_warning(
    monkeypatch,
) -> None:
    row = (
        "2026-07-08",
        "2026-07-08T08:00:00+00:00",
        "2026-07-08T00:01:00+00:00",
        '{"title": "Cached lead"}',
        '[{"label": "Models"}]',
        '[{"title": "Flash"}]',
        '["stored warning"]',
        (
            '{"date": "2026-07-08", '
            '"window_start": "2026-07-07T00:00:00+00:00", '
            '"window_end": "2026-07-08T00:00:00+00:00"}'
        ),
    )
    fake = FakeDatabase(row=row)
    monkeypatch.setattr(repository, "get_database", lambda _settings: fake)

    daily = repository.load_cached_aihot_daily_report("2026-07-08", settings=Settings())

    assert isinstance(daily, AiHotDaily)
    assert daily.date == "2026-07-08"
    assert daily.fetched_at == "2026-07-08T08:00:00+00:00"
    assert daily.generated_at == "2026-07-08T00:01:00+00:00"
    assert daily.window_start == "2026-07-07T00:00:00+00:00"
    assert daily.window_end == "2026-07-08T00:00:00+00:00"
    assert daily.lead == {"title": "Cached lead"}
    assert daily.sections == [{"label": "Models"}]
    assert daily.flashes == [{"title": "Flash"}]
    assert "stored warning" in daily.warnings
    assert daily_report_cache_warning("2026-07-08") in daily.warnings

    sql, params = fake.connection.executions[0]
    compact = _compact(sql)
    assert "FROM quant_system.ai_news_daily_reports" in compact
    assert "owner_user_id = %s" in compact
    assert "provider = %s" in compact
    assert "report_date = %s::date" in compact
    assert str(params[0]) == ROOT_USER_ID
    assert params[1] == "aihot"
    assert params[2] == "2026-07-08"


def test_daily_report_cache_is_noop_when_database_disabled(monkeypatch) -> None:
    monkeypatch.setattr(repository, "get_database", lambda _settings: None)

    repository.cache_aihot_daily_report(_daily(), settings=Settings())

    assert (
        repository.load_cached_aihot_daily_report("2026-07-08", settings=Settings())
        is None
    )


def test_daily_report_cache_errors_do_not_escape(monkeypatch) -> None:
    monkeypatch.setattr(repository, "get_database", lambda _settings: BrokenDatabase())

    repository.cache_aihot_daily_report(_daily(), settings=Settings())

    assert (
        repository.load_cached_aihot_daily_report("2026-07-08", settings=Settings())
        is None
    )
