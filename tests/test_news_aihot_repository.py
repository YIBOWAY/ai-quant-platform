from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from quant_system.config.settings import Settings
from quant_system.news import repository
from quant_system.news.models import AiHotItem, AiHotItemsPage


class _FakeConnection:
    def __init__(self, rows: list[tuple] | None = None) -> None:
        self.rows = rows or []
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()) -> _FakeConnection:
        self.statements.append((sql, params))
        return self

    def fetchall(self) -> list[tuple]:
        return self.rows


class _FakeDatabase:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    @contextmanager
    def connect(self) -> Iterator[_FakeConnection]:
        yield self.connection


def _page() -> AiHotItemsPage:
    return AiHotItemsPage(
        count=1,
        has_next=False,
        next_cursor=None,
        items=[
            AiHotItem(
                id="item-1",
                title="OpenAI 发布新模型",
                title_en="OpenAI releases a new model",
                url="https://example.com/openai",
                source="OpenAI Blog",
                published_at="2026-06-28T15:30:00.000Z",
                summary="中文摘要",
                category="ai-models",
                score=0.91,
                selected=True,
                raw={"id": "item-1"},
            )
        ],
        warnings=[],
        fetched_at="2026-06-28T15:31:00+00:00",
    )


def test_cache_aihot_items_upserts_items_and_fetch_audit(monkeypatch) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr(
        repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    query = repository.AiHotItemsCacheQuery(
        mode="selected",
        category="ai-models",
        q="OpenAI",
        since="2026-06-28T00:00:00Z",
        take=2,
    )
    repository.cache_aihot_items(_page(), settings=Settings(), query=query)

    sql_text = "\n".join(sql for sql, _params in connection.statements)
    assert "INSERT INTO quant_system.ai_news_items" in sql_text
    assert "INSERT INTO quant_system.ai_news_fetches" in sql_text
    item_params = connection.statements[0][1]
    assert item_params[0] == "aihot"
    assert item_params[1] == "item-1"
    assert item_params[2] == "OpenAI 发布新模型"


def test_load_cached_aihot_items_filters_and_returns_page(monkeypatch) -> None:
    fetched_at = datetime(2026, 6, 28, 15, 40, tzinfo=UTC)
    published_at = datetime(2026, 6, 28, 15, 30, tzinfo=UTC)
    connection = _FakeConnection(
        rows=[
            (
                "cached-1",
                "缓存里的 AI 新闻",
                None,
                "https://example.com/cached",
                "Cached Source",
                published_at,
                "上游失败时来自本地数据库缓存。",
                "industry",
                0.7,
                True,
                {"id": "cached-1"},
                fetched_at,
            )
        ]
    )
    monkeypatch.setattr(
        repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    page = repository.load_cached_aihot_items(
        settings=Settings(),
        query=repository.AiHotItemsCacheQuery(
            mode="selected",
            category="industry",
            q="OpenAI",
            since="2026-06-28T00:00:00Z",
            take=5,
        ),
    )

    assert page is not None
    assert page.count == 1
    assert page.items[0].id == "cached-1"
    assert page.items[0].published_at == "2026-06-28T15:30:00+00:00"
    assert page.fetched_at == "2026-06-28T15:40:00+00:00"
    assert "Using cached AI HOT items from the local database." in page.warnings
    sql, params = connection.statements[0]
    assert "selected IS TRUE" in sql
    assert "category = %s" in sql
    assert "ILIKE" in sql
    assert "%OpenAI%" in params


def test_load_cached_aihot_items_does_not_advertise_cursor_pagination(monkeypatch) -> None:
    fetched_at = datetime(2026, 6, 28, 15, 40, tzinfo=UTC)
    published_at = datetime(2026, 6, 28, 15, 30, tzinfo=UTC)
    rows = [
        (
            f"cached-{index}",
            f"缓存新闻 {index}",
            None,
            f"https://example.com/cached-{index}",
            "Cached Source",
            published_at,
            "缓存摘要",
            "industry",
            0.7,
            True,
            {"id": f"cached-{index}"},
            fetched_at,
        )
        for index in range(2)
    ]
    connection = _FakeConnection(rows=rows)
    monkeypatch.setattr(
        repository,
        "get_database",
        lambda _settings: _FakeDatabase(connection),
    )

    page = repository.load_cached_aihot_items(
        settings=Settings(),
        query=repository.AiHotItemsCacheQuery(mode="selected", take=1),
    )

    assert page is not None
    assert page.count == 1
    assert page.has_next is False
    assert page.next_cursor is None


def test_aihot_cache_repository_degrades_when_database_disabled(monkeypatch) -> None:
    monkeypatch.setattr(repository, "get_database", lambda _settings: None)
    query = repository.AiHotItemsCacheQuery(mode="selected", take=5)

    repository.cache_aihot_items(_page(), settings=Settings(), query=query)

    assert repository.load_cached_aihot_items(settings=Settings(), query=query) is None
