from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from quant_system.config.settings import HorizonSettings, Settings
from quant_system.news import daily_report_repository, horizon_repository, repository
from quant_system.news.horizon_inbox import HorizonInboxRun
from quant_system.news.models import AiHotDaily, AiHotItem


class _FakeConnection:
    def __init__(
        self,
        *,
        rows: list[tuple] | None = None,
        row: tuple | None = None,
    ) -> None:
        self.rows = rows or []
        self.row = row
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> _FakeConnection:
        self.statements.append((sql, params))
        return self

    def fetchall(self) -> list[tuple]:
        return self.rows

    def fetchone(self) -> tuple | None:
        return self.row


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    @contextmanager
    def connect(self) -> Iterator[_FakeConnection]:
        yield self.connection


def _settings(*, max_age_seconds: int = 129_600) -> Settings:
    settings = Settings()
    settings.horizon = HorizonSettings(
        enabled=True,
        max_age_seconds=max_age_seconds,
        inbox_dir=str(Path("data/horizon_inbox")),
    )
    return settings


def _run_row(
    *,
    run_id: str = "20260723T120000Z-ab12",
    generated_at: datetime | str,
    item_count: int = 3,
    status: str = "ingested",
) -> tuple:
    return (
        run_id,
        generated_at,
        None,
        None,
        item_count,
        "2026-07-23",
        "/tmp/inbox/runs/20260723T120000Z-ab12",
        "digest-abc",
        datetime(2026, 7, 23, 12, 5, tzinfo=UTC),
        status,
        None,
        {"run_id": run_id},
    )


def test_load_latest_horizon_run_returns_fresh_run(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
    generated = now - timedelta(hours=1)
    connection = _FakeConnection(row=_run_row(generated_at=generated, item_count=5))
    monkeypatch.setattr(
        horizon_repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    result = horizon_repository.load_latest_horizon_run(settings=_settings(), now=now)

    assert result is not None
    assert result["run_id"] == "20260723T120000Z-ab12"
    assert result["item_count"] == 5
    assert result["status"] == "ingested"
    assert result["content_digest"] == "digest-abc"
    sql, params = connection.statements[0]
    assert "ai_news_provider_runs" in sql
    assert "status = %s" in sql
    assert "item_count > 0" in sql
    assert params[0] == "horizon"
    assert params[1] == "ingested"


def test_load_latest_horizon_run_stale_generated_at_returns_none(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
    generated = now - timedelta(hours=40)  # > default 36h
    connection = _FakeConnection(row=_run_row(generated_at=generated, item_count=5))
    monkeypatch.setattr(
        horizon_repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    result = horizon_repository.load_latest_horizon_run(
        settings=_settings(max_age_seconds=129_600),
        now=now,
    )

    assert result is None


def test_load_latest_horizon_run_item_count_zero_not_fresh(monkeypatch) -> None:
    now = datetime(2026, 7, 23, 14, 0, tzinfo=UTC)
    # SQL filters item_count > 0, so fetchone returns None when no qualifying row.
    connection = _FakeConnection(row=None)
    monkeypatch.setattr(
        horizon_repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    result = horizon_repository.load_latest_horizon_run(settings=_settings(), now=now)

    assert result is None
    sql, _params = connection.statements[0]
    assert "item_count > 0" in sql


def test_load_horizon_items_page_filters_provider_horizon(monkeypatch) -> None:
    fetched_at = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    published_at = datetime(2026, 7, 23, 11, 0, tzinfo=UTC)
    connection = _FakeConnection(
        rows=[
            (
                "hz-1",
                "Horizon 新闻",
                None,
                "https://example.com/hz",
                "Horizon Source",
                published_at,
                "摘要",
                "industry",
                0.8,
                True,
                {"id": "hz-1"},
                fetched_at,
            )
        ]
    )
    monkeypatch.setattr(
        repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    page = horizon_repository.load_horizon_items_page(
        settings=_settings(),
        take=10,
        category="industry",
        q="Horizon",
    )

    assert page is not None
    assert page.count == 1
    assert page.items[0].id == "hz-1"
    sql, params = connection.statements[0]
    assert "FROM quant_system.ai_news_items" in sql
    assert "provider = %s" in sql
    assert params[0] == "horizon"
    assert "selected IS TRUE" not in sql  # horizon loads mode=all
    assert "category = %s" in sql
    assert "%Horizon%" in params


def test_is_run_ingested_true_when_digest_matches(monkeypatch) -> None:
    connection = _FakeConnection(row=(1,))
    monkeypatch.setattr(
        horizon_repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    assert (
        horizon_repository.is_run_ingested(
            "horizon",
            "run-1",
            "digest-1",
            _settings(),
        )
        is True
    )
    sql, params = connection.statements[0]
    assert "content_digest = %s" in sql
    assert params == ("horizon", "run-1", "digest-1", "ingested")


def test_is_run_ingested_false_when_missing(monkeypatch) -> None:
    connection = _FakeConnection(row=None)
    monkeypatch.setattr(
        horizon_repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    assert (
        horizon_repository.is_run_ingested(
            "horizon",
            "run-1",
            "digest-1",
            _settings(),
        )
        is False
    )


def test_record_provider_run_upserts(monkeypatch) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr(
        horizon_repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    horizon_repository.record_provider_run(
        settings=_settings(),
        provider="horizon",
        run_id="run-1",
        generated_at="2026-07-23T12:00:00+00:00",
        inbox_path="/tmp/run-1",
        content_digest="abc",
        status="ingested",
        item_count=2,
        daily_date="2026-07-23",
        raw_meta={"k": "v"},
    )

    assert len(connection.statements) == 1
    sql, params = connection.statements[0]
    assert "INSERT INTO quant_system.ai_news_provider_runs" in sql
    assert "ON CONFLICT (provider, run_id)" in sql
    assert params[0] == "horizon"
    assert params[1] == "run-1"
    assert params[5] == 2
    assert params[8] == "abc"
    assert params[9] == "ingested"


def test_persist_horizon_run_writes_items_daily_and_run(monkeypatch) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr(
        horizon_repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    item = AiHotItem(
        id="i1",
        title="T",
        title_en=None,
        url="https://example.com/t",
        source="s",
        published_at="2026-07-23T11:00:00+00:00",
        summary="sum",
        category="ai",
        score=0.9,
        selected=True,
        raw={"id": "i1"},
    )
    daily = AiHotDaily(
        date="2026-07-23",
        generated_at="2026-07-23T12:00:00+00:00",
        window_start=None,
        window_end=None,
        lead={"title": "Lead"},
        sections=[],
        flashes=[],
        warnings=[],
        raw={},
        fetched_at="2026-07-23T12:01:00+00:00",
    )
    run = HorizonInboxRun(
        run_id="run-xyz",
        path=Path("/tmp/runs/run-xyz"),
        meta={
            "run_id": "run-xyz",
            "generated_at": "2026-07-23T12:00:00+00:00",
            "daily_date": "2026-07-23",
        },
        items=[item],
        daily=daily,
        content_digest="digest-xyz",
    )

    horizon_repository.persist_horizon_run(run, settings=_settings())

    sql_blob = "\n".join(sql for sql, _ in connection.statements)
    assert "INSERT INTO quant_system.ai_news_items" in sql_blob
    assert "INSERT INTO quant_system.ai_news_daily_reports" in sql_blob
    assert "INSERT INTO quant_system.ai_news_provider_runs" in sql_blob
    item_params = connection.statements[0][1]
    assert item_params[0] == "horizon"
    assert item_params[1] == "i1"
    run_params = connection.statements[-1][1]
    assert run_params[0] == "horizon"
    assert run_params[1] == "run-xyz"
    assert run_params[5] == 1
    assert run_params[8] == "digest-xyz"


def test_cache_news_daily_report_accepts_horizon_provider(monkeypatch) -> None:
    class FakeConnection:
        def __init__(self) -> None:
            self.executions: list[tuple[str, tuple]] = []

        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def execute(self, sql: str, params: tuple = ()) -> FakeConnection:
            self.executions.append((sql, params))
            return self

        def fetchone(self) -> None:
            return None

    class FakeDatabase:
        def __init__(self) -> None:
            self.connection = FakeConnection()

        def connect(self) -> FakeConnection:
            return self.connection

    fake = FakeDatabase()
    monkeypatch.setattr(daily_report_repository, "get_database", lambda _s: fake)

    daily = AiHotDaily(
        date="2026-07-23",
        generated_at="2026-07-23T12:00:00+00:00",
        window_start=None,
        window_end=None,
        lead={"title": "H"},
        sections=[],
        flashes=[],
        warnings=[],
        raw={},
        fetched_at="2026-07-23T12:01:00+00:00",
    )
    daily_report_repository.cache_news_daily_report(
        daily,
        settings=Settings(),
        provider="horizon",
    )
    _sql, params = fake.connection.executions[0]
    assert params[1] == "horizon"


def test_load_horizon_daily_and_dailies(monkeypatch) -> None:
    daily_row = (
        "2026-07-23",
        "2026-07-23T12:01:00+00:00",
        "2026-07-23T12:00:00+00:00",
        '{"title": "Lead"}',
        "[]",
        "[]",
        "[]",
        "{}",
    )
    index_rows = [
        ("2026-07-23", "2026-07-23T12:00:00+00:00", '{"title": "Lead"}', "{}"),
        ("2026-07-22", "2026-07-22T12:00:00+00:00", '{"title": "Older"}', "{}"),
    ]

    class FakeConnection:
        def __init__(self) -> None:
            self.executions: list[tuple[str, tuple]] = []
            self._mode = "one"

        def __enter__(self) -> FakeConnection:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def execute(self, sql: str, params: tuple = ()) -> FakeConnection:
            self.executions.append((sql, params))
            self._mode = (
                "all"
                if "ORDER BY report_date DESC" in sql and "LIMIT %s" in sql
                else "one"
            )
            if "LIMIT 1" in sql and "report_date = %s::date" not in sql:
                self._mode = "latest"
            return self

        def fetchone(self) -> tuple | None:
            return daily_row

        def fetchall(self) -> list[tuple]:
            return index_rows

    class FakeDatabase:
        def __init__(self) -> None:
            self.connection = FakeConnection()

        def connect(self) -> FakeConnection:
            return self.connection

    fake = FakeDatabase()
    monkeypatch.setattr(daily_report_repository, "get_database", lambda _s: fake)

    daily = horizon_repository.load_horizon_daily(settings=_settings(), date="2026-07-23")
    assert daily is not None
    assert daily.date == "2026-07-23"
    assert fake.connection.executions[0][1][1] == "horizon"

    page = horizon_repository.load_horizon_dailies(settings=_settings(), take=5)
    assert page is not None
    assert page.count == 2
    assert page.items[0].date == "2026-07-23"
    assert fake.connection.executions[-1][1][1] == "horizon"


def test_horizon_repo_degrades_without_database(monkeypatch) -> None:
    monkeypatch.setattr(horizon_repository, "get_database", lambda _s: None)
    monkeypatch.setattr(repository, "get_database", lambda _s: None)
    monkeypatch.setattr(daily_report_repository, "get_database", lambda _s: None)

    assert horizon_repository.load_latest_horizon_run(settings=_settings()) is None
    assert horizon_repository.load_horizon_items_page(settings=_settings(), take=5) is None
    assert horizon_repository.load_horizon_daily(settings=_settings(), date=None) is None
    assert horizon_repository.load_horizon_dailies(settings=_settings(), take=5) is None
    assert (
        horizon_repository.is_run_ingested("horizon", "r", "d", _settings()) is False
    )
