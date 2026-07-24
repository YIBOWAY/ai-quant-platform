"""PostgreSQL repository for Horizon-ingested AI news runs and items."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from quant_system.news import daily_report_repository, repository
from quant_system.news.horizon_inbox import HorizonInboxRun
from quant_system.news.models import AiHotDailiesPage, AiHotDaily, AiHotItemsPage, utc_now_iso
from quant_system.news.repository import AiHotItemsCacheQuery
from quant_system.storage.database import SCHEMA, get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

log = logging.getLogger(__name__)

PROVIDER = "horizon"
_STATUS_INGESTED = "ingested"
_RUN_COLUMNS = (
    "run_id",
    "generated_at",
    "window_start",
    "window_end",
    "item_count",
    "daily_date",
    "inbox_path",
    "content_digest",
    "ingested_at",
    "status",
    "error",
    "raw_meta",
)


def load_latest_horizon_run(
    *,
    settings: Settings,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return the newest fresh ingested Horizon run, or ``None``.

    Fresh means ``status='ingested'``, ``item_count > 0``, and
    ``generated_at`` within ``settings.horizon.max_age_seconds``.
    """

    database = get_database(settings)
    if database is None:
        return None
    clock = _ensure_utc(now or datetime.now(UTC))
    try:
        with database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    run_id,
                    generated_at,
                    window_start,
                    window_end,
                    item_count,
                    daily_date,
                    inbox_path,
                    content_digest,
                    ingested_at,
                    status,
                    error,
                    raw_meta
                FROM {SCHEMA}.ai_news_provider_runs
                WHERE provider = %s
                  AND status = %s
                  AND item_count > 0
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (PROVIDER, _STATUS_INGESTED),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - read path must survive DB trouble
        log.warning("horizon run read skipped: %s", exc)
        return None

    if row is None:
        return None
    payload = _run_from_row(row)
    generated_at = _parse_datetime(payload.get("generated_at"))
    if generated_at is None:
        return None
    max_age = timedelta(seconds=int(settings.horizon.max_age_seconds))
    if clock - generated_at > max_age:
        return None
    return payload


def load_horizon_items_page(
    *,
    settings: Settings,
    take: int,
    category: str | None = None,
    q: str | None = None,
    since: str | None = None,
) -> AiHotItemsPage | None:
    """Load Horizon items from PG (provider filter hardcoded to horizon)."""

    return repository.load_cached_news_items(
        settings=settings,
        query=AiHotItemsCacheQuery(
            mode="all",
            category=category,
            q=q,
            since=since,
            take=take,
        ),
        provider=PROVIDER,
    )


def load_horizon_daily(
    *,
    settings: Settings,
    date: str | None,
) -> AiHotDaily | None:
    """Load a Horizon daily report; ``date=None`` returns the latest."""

    if date:
        return daily_report_repository.load_cached_news_daily_report(
            date,
            settings=settings,
            provider=PROVIDER,
        )
    return daily_report_repository.load_latest_cached_news_daily_report(
        settings=settings,
        provider=PROVIDER,
    )


def load_horizon_dailies(
    *,
    settings: Settings,
    take: int,
) -> AiHotDailiesPage | None:
    """Load Horizon daily index rows from PG."""

    return daily_report_repository.load_cached_news_dailies(
        settings=settings,
        provider=PROVIDER,
        take=take,
    )


def is_run_ingested(
    provider: str,
    run_id: str,
    content_digest: str,
    settings: Settings,
) -> bool:
    """True when the run is already stored as ingested with the same digest."""

    database = get_database(settings)
    if database is None:
        return False
    try:
        with database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT 1
                FROM {SCHEMA}.ai_news_provider_runs
                WHERE provider = %s
                  AND run_id = %s
                  AND content_digest = %s
                  AND status = %s
                LIMIT 1
                """,
                (provider, run_id, content_digest, _STATUS_INGESTED),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        log.warning("horizon is_run_ingested skipped: %s", exc)
        return False
    return row is not None


def record_provider_run(
    *,
    settings: Settings,
    provider: str,
    run_id: str,
    generated_at: str,
    inbox_path: str,
    content_digest: str,
    status: str,
    item_count: int = 0,
    window_start: str | None = None,
    window_end: str | None = None,
    daily_date: str | None = None,
    error: str | None = None,
    raw_meta: dict[str, Any] | None = None,
    conn: Any | None = None,
) -> None:
    """Upsert a provider run row. Pass ``conn`` to join an outer transaction."""

    params = (
        provider,
        run_id,
        generated_at,
        window_start,
        window_end,
        int(item_count),
        daily_date,
        inbox_path,
        content_digest,
        status,
        error,
        json.dumps(raw_meta or {}, ensure_ascii=False),
    )
    sql = f"""
        INSERT INTO {SCHEMA}.ai_news_provider_runs
            (
                provider,
                run_id,
                generated_at,
                window_start,
                window_end,
                item_count,
                daily_date,
                inbox_path,
                content_digest,
                ingested_at,
                status,
                error,
                raw_meta
            )
        VALUES (
            %s, %s, %s::timestamptz, %s::timestamptz, %s::timestamptz,
            %s, %s::date, %s, %s, now(), %s, %s, %s::jsonb
        )
        ON CONFLICT (provider, run_id) DO UPDATE
        SET generated_at = EXCLUDED.generated_at,
            window_start = EXCLUDED.window_start,
            window_end = EXCLUDED.window_end,
            item_count = EXCLUDED.item_count,
            daily_date = EXCLUDED.daily_date,
            inbox_path = EXCLUDED.inbox_path,
            content_digest = EXCLUDED.content_digest,
            ingested_at = now(),
            status = EXCLUDED.status,
            error = EXCLUDED.error,
            raw_meta = EXCLUDED.raw_meta
        """

    if conn is not None:
        conn.execute(sql, params)
        return

    database = get_database(settings)
    if database is None:
        raise RuntimeError("database is required to record provider runs")
    with database.connect() as owned:
        owned.execute(sql, params)


def persist_horizon_run(run: HorizonInboxRun, *, settings: Settings) -> None:
    """Transactionally upsert Horizon items, daily, and provider_runs row."""

    database = get_database(settings)
    if database is None:
        raise RuntimeError("database is required to persist horizon runs")

    page = AiHotItemsPage(
        count=len(run.items),
        has_next=False,
        next_cursor=None,
        items=list(run.items),
        warnings=[],
        fetched_at=utc_now_iso(),
    )
    query = AiHotItemsCacheQuery(mode="all", take=max(1, len(run.items) or 1))
    generated_at = str(run.meta.get("generated_at") or utc_now_iso())
    daily_date = None
    if run.daily is not None and run.daily.date:
        daily_date = run.daily.date
    elif run.meta.get("daily_date"):
        daily_date = str(run.meta.get("daily_date"))

    with database.connect() as conn:
        repository._upsert_items(  # noqa: SLF001 - shared write helper
            conn,
            page=page,
            query=query,
            provider=PROVIDER,
        )
        if run.daily is not None:
            _upsert_daily_on_conn(conn, daily=run.daily, provider=PROVIDER)
        record_provider_run(
            settings=settings,
            provider=PROVIDER,
            run_id=run.run_id,
            generated_at=generated_at,
            window_start=_optional_str(run.meta.get("window_start")),
            window_end=_optional_str(run.meta.get("window_end")),
            item_count=len(run.items),
            daily_date=daily_date,
            inbox_path=str(run.path),
            content_digest=run.content_digest,
            status=_STATUS_INGESTED,
            error=None,
            raw_meta=dict(run.meta),
            conn=conn,
        )


def _upsert_daily_on_conn(conn: Any, *, daily: AiHotDaily, provider: str) -> None:
    from uuid import UUID

    owner = UUID("00000000-0000-0000-0000-000000000001")
    conn.execute(
        f"""
        INSERT INTO {SCHEMA}.ai_news_daily_reports
            (
                owner_user_id,
                provider,
                report_date,
                fetched_at,
                generated_at,
                lead,
                sections,
                flashes,
                warnings,
                raw,
                updated_at
            )
        VALUES (
            %s, %s, %s::date, %s::timestamptz, %s::timestamptz,
            %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, now()
        )
        ON CONFLICT (owner_user_id, provider, report_date) DO UPDATE
        SET fetched_at = EXCLUDED.fetched_at,
            generated_at = EXCLUDED.generated_at,
            lead = EXCLUDED.lead,
            sections = EXCLUDED.sections,
            flashes = EXCLUDED.flashes,
            warnings = EXCLUDED.warnings,
            raw = EXCLUDED.raw,
            updated_at = now()
        """,
        (
            owner,
            provider,
            daily.date,
            daily.fetched_at,
            daily.generated_at,
            json.dumps(daily.lead, ensure_ascii=False),
            json.dumps(daily.sections, ensure_ascii=False),
            json.dumps(daily.flashes, ensure_ascii=False),
            json.dumps(daily.warnings, ensure_ascii=False),
            json.dumps(daily_report_repository._raw_with_window(daily), ensure_ascii=False),
        ),
    )


def _run_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    payload: dict[str, Any] = {"provider": PROVIDER}
    for index, key in enumerate(_RUN_COLUMNS):
        value = row[index]
        if key == "raw_meta":
            payload[key] = _json_dict(value)
        elif key in {
            "generated_at",
            "window_start",
            "window_end",
            "ingested_at",
            "daily_date",
        }:
            payload[key] = _iso_or_none(value)
        elif key == "item_count":
            payload[key] = int(value or 0)
        else:
            payload[key] = value
    return payload


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    return text if text else None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
