"""Optional PostgreSQL cache for read-only AI HOT items.

The live AI HOT public API remains the primary source. This module is a
best-effort local mirror used only to make the read-only news page resilient when
the upstream source is temporarily unavailable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from quant_system.news.models import AiHotItem, AiHotItemsPage, utc_now_iso
from quant_system.storage.database import SCHEMA, get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

log = logging.getLogger(__name__)

_PROVIDER = "aihot"
_CACHE_WARNING = "Using cached AI HOT items from the local database."


@dataclass(frozen=True)
class AiHotItemsCacheQuery:
    mode: Literal["selected", "all"] = "selected"
    category: str | None = None
    q: str | None = None
    since: str | None = None
    cursor: str | None = None
    take: int = 50


def cache_aihot_items(
    page: AiHotItemsPage,
    *,
    settings: Settings,
    query: AiHotItemsCacheQuery,
) -> None:
    """Best-effort upsert of live AI HOT items into the optional database."""

    database = get_database(settings)
    if database is None:
        return
    try:
        with database.connect() as conn:
            for item in page.items:
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.ai_news_items
                        (
                            provider,
                            item_id,
                            title,
                            title_en,
                            url,
                            source,
                            published_at,
                            summary,
                            category,
                            score,
                            selected,
                            raw,
                            fetched_at,
                            updated_at
                        )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s::timestamptz,
                        %s, %s, %s, %s, %s::jsonb, %s::timestamptz, now()
                    )
                    ON CONFLICT (provider, item_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        title_en = EXCLUDED.title_en,
                        url = EXCLUDED.url,
                        source = EXCLUDED.source,
                        published_at = EXCLUDED.published_at,
                        summary = EXCLUDED.summary,
                        category = EXCLUDED.category,
                        score = EXCLUDED.score,
                        selected = EXCLUDED.selected,
                        raw = EXCLUDED.raw,
                        fetched_at = EXCLUDED.fetched_at,
                        updated_at = now()
                    """,
                    (
                        _PROVIDER,
                        item.id,
                        item.title,
                        item.title_en,
                        item.url,
                        item.source,
                        item.published_at,
                        item.summary,
                        item.category,
                        item.score,
                        item.selected,
                        json.dumps(item.raw, ensure_ascii=False),
                        page.fetched_at,
                    ),
                )
            conn.execute(
                f"""
                INSERT INTO {SCHEMA}.ai_news_fetches
                    (
                        provider,
                        fetched_at,
                        mode,
                        category,
                        search_query,
                        since,
                        cursor,
                        take_count,
                        item_count,
                        warnings
                    )
                VALUES (
                    %s, %s::timestamptz, %s, %s, %s, %s::timestamptz,
                    %s, %s, %s, %s::jsonb
                )
                """,
                (
                    _PROVIDER,
                    page.fetched_at,
                    query.mode,
                    query.category,
                    query.q,
                    query.since,
                    query.cursor,
                    query.take,
                    len(page.items),
                    json.dumps(page.warnings, ensure_ascii=False),
                ),
            )
    except Exception as exc:  # noqa: BLE001 - cache must not affect live reads
        log.warning("aihot cache write skipped: %s", exc)


def load_cached_aihot_items(
    *,
    settings: Settings,
    query: AiHotItemsCacheQuery,
) -> AiHotItemsPage | None:
    """Return cached AI HOT items for the query, or ``None`` if unavailable."""

    if query.cursor:
        return None
    database = get_database(settings)
    if database is None:
        return None
    try:
        where, params = _where_clause(query)
        take = _take_limit(query.take)
        with database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    item_id,
                    title,
                    title_en,
                    url,
                    source,
                    published_at,
                    summary,
                    category,
                    score,
                    selected,
                    raw,
                    fetched_at
                FROM {SCHEMA}.ai_news_items
                WHERE {" AND ".join(where)}
                ORDER BY published_at DESC NULLS LAST, fetched_at DESC, updated_at DESC
                LIMIT %s
                """,
                (*params, take + 1),
            ).fetchall()
    except Exception as exc:  # noqa: BLE001 - upstream error path must survive DB trouble
        log.warning("aihot cache read skipped: %s", exc)
        return None

    if not rows:
        return None
    visible_rows = rows[:take]
    items = [_item_from_row(row) for row in visible_rows]
    return AiHotItemsPage(
        count=len(items),
        has_next=False,
        next_cursor=None,
        items=items,
        warnings=[_CACHE_WARNING],
        fetched_at=_latest_fetched_at(visible_rows),
    )


def _where_clause(query: AiHotItemsCacheQuery) -> tuple[list[str], list[Any]]:
    where = ["provider = %s"]
    params: list[Any] = [_PROVIDER]
    if query.mode == "selected":
        where.append("selected IS TRUE")
    if query.category:
        where.append("category = %s")
        params.append(query.category)
    if query.q and query.q.strip():
        needle = f"%{query.q.strip()[:200]}%"
        where.append(
            "(title ILIKE %s OR title_en ILIKE %s OR summary ILIKE %s OR source ILIKE %s)"
        )
        params.extend([needle, needle, needle, needle])
    if query.since:
        where.append("published_at >= %s::timestamptz")
        params.append(query.since)
    return where, params


def _take_limit(take: int) -> int:
    return max(1, min(int(take), 100))


def _item_from_row(row: tuple) -> AiHotItem:
    raw = row[10]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return AiHotItem(
        id=str(row[0]),
        title=str(row[1]),
        title_en=row[2],
        url=str(row[3]),
        source=str(row[4]),
        published_at=_iso_or_none(row[5]),
        summary=row[6],
        category=row[7],
        score=float(row[8]) if row[8] is not None else None,
        selected=bool(row[9]) if row[9] is not None else None,
        raw=raw,
    )


def _latest_fetched_at(rows: list[tuple]) -> str:
    values = [row[11] for row in rows if row[11] is not None]
    datetimes = [value for value in values if isinstance(value, datetime)]
    if datetimes:
        return max(datetimes).isoformat()
    strings = [str(value) for value in values if value is not None]
    if strings:
        return max(strings)
    return utc_now_iso()


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
