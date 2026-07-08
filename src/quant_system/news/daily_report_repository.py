"""Optional PostgreSQL cache for AI HOT daily reports."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from quant_system.news.models import AiHotDaily, utc_now_iso
from quant_system.storage.database import SCHEMA, get_database

if TYPE_CHECKING:
    from quant_system.config.settings import Settings

log = logging.getLogger(__name__)

_PROVIDER = "aihot"
_ROOT_OWNER_USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def daily_report_cache_warning(report_date: str) -> str:
    return f"Using cached AI HOT daily report for {report_date} from the local database."


def cache_aihot_daily_report(daily: AiHotDaily, *, settings: Settings) -> None:
    """Best-effort upsert of a live AI HOT daily report into the optional DB."""

    database = get_database(settings)
    if database is None:
        return
    try:
        with database.connect() as conn:
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
                    _ROOT_OWNER_USER_ID,
                    _PROVIDER,
                    daily.date,
                    daily.fetched_at,
                    daily.generated_at,
                    _json_param(daily.lead),
                    _json_param(daily.sections),
                    _json_param(daily.flashes),
                    _json_param(daily.warnings),
                    _json_param(_raw_with_window(daily)),
                ),
            )
    except Exception as exc:  # noqa: BLE001 - cache must not affect live reads
        log.warning("aihot daily report cache write skipped: %s", exc)


def load_cached_aihot_daily_report(
    date: str,
    *,
    settings: Settings,
) -> AiHotDaily | None:
    """Return a cached AI HOT daily report, or ``None`` if unavailable."""

    database = get_database(settings)
    if database is None:
        return None
    try:
        with database.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    report_date::text,
                    fetched_at::text,
                    generated_at::text,
                    lead,
                    sections,
                    flashes,
                    warnings,
                    raw
                FROM {SCHEMA}.ai_news_daily_reports
                WHERE owner_user_id = %s
                  AND provider = %s
                  AND report_date = %s::date
                """,
                (_ROOT_OWNER_USER_ID, _PROVIDER, date),
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 - upstream error path must survive DB trouble
        log.warning("aihot daily report cache read skipped: %s", exc)
        return None

    if row is None:
        return None
    return _daily_from_row(row)


def _daily_from_row(row: tuple[Any, ...]) -> AiHotDaily:
    report_date = _iso_or_none(row[0]) or ""
    raw = _json_dict(row[7])
    warnings = [
        *_json_string_list(row[6]),
        daily_report_cache_warning(report_date),
    ]
    return AiHotDaily(
        date=report_date,
        fetched_at=_iso_or_none(row[1]) or utc_now_iso(),
        generated_at=_iso_or_none(row[2]),
        window_start=_raw_text(raw, "window_start", "windowStart"),
        window_end=_raw_text(raw, "window_end", "windowEnd"),
        lead=_json_dict_or_none(row[3]),
        sections=_json_dict_list(row[4]),
        flashes=_json_dict_list(row[5]),
        warnings=warnings,
        raw=raw,
    )


def _json_param(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _raw_with_window(daily: AiHotDaily) -> dict[str, Any]:
    raw = dict(daily.raw)
    if daily.window_start is not None:
        raw.setdefault("window_start", daily.window_start)
    if daily.window_end is not None:
        raw.setdefault("window_end", daily.window_end)
    return raw


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _json_dict(value: Any) -> dict[str, Any]:
    parsed = _json_value(value)
    return parsed if isinstance(parsed, dict) else {}


def _json_dict_or_none(value: Any) -> dict[str, Any] | None:
    parsed = _json_value(value)
    return parsed if isinstance(parsed, dict) else None


def _json_dict_list(value: Any) -> list[dict[str, Any]]:
    parsed = _json_value(value)
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _json_string_list(value: Any) -> list[str]:
    parsed = _json_value(value)
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item is not None]


def _raw_text(raw: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value is not None:
            text = str(value)
            return text if text else None
    return None


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value)
    return text if text else None
