"""Expected observation nights versus hung-sleeve records.

Absence is the set difference. It is not a no-signal night and does not
count as an observation day. Unexpired slots are pending, never absent.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from quant_system.d34.paper_cycle import EXECUTION_SLOT
from quant_system.research.strategy_runtime import latest_session

SHANGHAI = ZoneInfo("Asia/Shanghai")
SCHEDULE_UPDATED_ON = date(2026, 9, 11)
# Monday–Saturday. Sunday has no observation night.
NIGHT_WEEKDAYS = frozenset({0, 1, 2, 3, 4, 5})
ABSENT_YESTERDAY_LABEL_ZH = "昨日观察：缺席（未运行）"
RECORDED_YESTERDAY_LABEL_ZH = "昨日观察：已运行（成交另列）"
DATA_UNAVAILABLE_YESTERDAY_LABEL_ZH = "昨日观察：已运行，但信号数据不可用"
PENDING_YESTERDAY_LABEL_ZH = "昨日观察：未到期"
NOT_SCHEDULED_YESTERDAY_LABEL_ZH = "昨日观察：无观察窗"
_PROCESSED_EXECUTION = frozenset(
    {
        "filled",
        "partially_filled",
        "blocked",
        "skipped",
        "failed",
        "missed_window",
    }
)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation_calendar_clock_invalid")
    return value.astimezone(SHANGHAI)


def _parse_stamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _require_aware(value)
    text = str(value).strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def _slot_at(day: date) -> datetime:
    slot = time(22, 25) if day < SCHEDULE_UPDATED_ON else EXECUTION_SLOT
    return datetime.combine(day, slot, tzinfo=SHANGHAI)


def _has_observation_slot(day: date) -> bool:
    if day.weekday() not in NIGHT_WEEKDAYS:
        return False
    # Morning observes the previous real session; evening processes today's session.
    prior = day - timedelta(days=1)
    return latest_session(day).date() == day or latest_session(prior).date() == prior


def _is_official_sleeve(sleeve: Any) -> bool:
    metadata = getattr(sleeve, "metadata", None) or {}
    return metadata.get("fossil") is not True and metadata.get("official_observation") is not False


def _status_text(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").strip().lower()


def collect_recorded_nights(
    *,
    sleeves: list[Any],
    storage: Any,
    account_positions: Any | None = None,
) -> list[str]:
    """Dates with a hung-sleeve signal or processed fill. Inventory is ignored."""
    del account_positions
    nights: set[str] = set()
    for sleeve in sleeves:
        if not _is_official_sleeve(sleeve):
            continue
        sleeve_id = sleeve.sleeve_id
        for signal in storage.load_signals(sleeve_id):
            signal_date = getattr(signal, "signal_date", None)
            if signal_date:
                nights.add(str(signal_date))
        load_executions = getattr(storage, "load_executions", None)
        if not callable(load_executions):
            continue
        for execution in load_executions(sleeve_id):
            if _status_text(getattr(execution, "status", None)) not in _PROCESSED_EXECUTION:
                continue
            target_date = getattr(execution, "target_date", None)
            if target_date:
                nights.add(str(target_date))
    return sorted(nights)


def collect_data_unavailable_nights(
    *,
    sleeves: list[Any],
    storage: Any,
) -> list[str]:
    nights: set[str] = set()
    for sleeve in sleeves:
        if not _is_official_sleeve(sleeve):
            continue
        for signal in storage.load_signals(sleeve.sleeve_id):
            if _status_text(getattr(signal, "status", None)) != "data_unavailable":
                continue
            signal_date = getattr(signal, "signal_date", None)
            if signal_date:
                nights.add(str(signal_date))
    return sorted(nights)


def collect_filled_nights(*, sleeves: list[Any], storage: Any) -> list[str]:
    """Actual recorded fill dates, not signal creation or blocked plans."""
    nights: set[str] = set()
    load = getattr(storage, "load_executions", None)
    if not callable(load):
        return []
    for sleeve in sleeves:
        if not _is_official_sleeve(sleeve):
            continue
        for execution in load(sleeve.sleeve_id):
            if (
                _status_text(getattr(execution, "status", None)) in {"filled", "partially_filled"}
                and getattr(execution, "fills", None)
                and getattr(execution, "target_date", None)
            ):
                nights.add(str(execution.target_date))
    return sorted(nights)


def _yesterday_payload(
    *,
    day: date,
    status: str,
    counts_as_observation_day: bool,
) -> dict[str, Any]:
    labels = {
        "absent": ABSENT_YESTERDAY_LABEL_ZH,
        "recorded": RECORDED_YESTERDAY_LABEL_ZH,
        "data_unavailable": DATA_UNAVAILABLE_YESTERDAY_LABEL_ZH,
        "pending": PENDING_YESTERDAY_LABEL_ZH,
        "not_scheduled": NOT_SCHEDULED_YESTERDAY_LABEL_ZH,
    }
    return {
        "date": day.isoformat(),
        "status": status,
        "label_zh": labels[status],
        "counts_as_observation_day": counts_as_observation_day,
        "is_no_signal": False,
        "reason": "signal_data_unavailable" if status == "data_unavailable" else None,
    }


def reconcile_observation_nights(
    *,
    hung_at: datetime | None,
    now: datetime,
    recorded_nights: list[str] | set[str],
    data_unavailable_nights: list[str] | set[str] = (),
    filled_nights: list[str] | set[str] = (),
) -> dict[str, Any]:
    current = _require_aware(now)
    recorded = {str(item) for item in recorded_nights}
    data_unavailable = {str(item) for item in data_unavailable_nights}
    filled = {str(item) for item in filled_nights}
    yesterday = current.date() - timedelta(days=1)
    if hung_at is None:
        return {
            "yesterday": _yesterday_payload(
                day=yesterday,
                status="not_scheduled",
                counts_as_observation_day=False,
            ),
            "expected_nights": [],
            "recorded_nights": sorted(recorded),
            "absent_nights": [],
            "pending_nights": [],
            "observation_day_count": 0,
            "calendar_run_day_count": 0,
            "data_unavailable_day_count": 0,
            "filled_day_count": 0,
            "filled_nights": [],
        }

    hung = _require_aware(hung_at)
    expected: list[str] = []
    pending: list[str] = []
    cursor = hung.date()
    last = current.date() + timedelta(days=7)
    while cursor <= last:
        if _has_observation_slot(cursor):
            slot = _slot_at(cursor)
            if slot > hung:
                if slot <= current:
                    expected.append(cursor.isoformat())
                else:
                    pending.append(cursor.isoformat())
        cursor += timedelta(days=1)

    absent = [day for day in expected if day not in recorded]
    if not _has_observation_slot(yesterday) or _slot_at(yesterday) <= hung:
        yesterday_status = "not_scheduled"
        yesterday_counts = False
    elif _slot_at(yesterday) > current:
        yesterday_status = "pending"
        yesterday_counts = False
    elif yesterday.isoformat() in recorded:
        yesterday_status = (
            "data_unavailable" if yesterday.isoformat() in data_unavailable else "recorded"
        )
        yesterday_counts = yesterday.isoformat() in filled
    else:
        yesterday_status = "absent"
        yesterday_counts = False

    return {
        "yesterday": _yesterday_payload(
            day=yesterday,
            status=yesterday_status,
            counts_as_observation_day=yesterday_counts,
        ),
        "expected_nights": expected,
        "recorded_nights": sorted(day for day in recorded if day in expected or day in pending),
        "absent_nights": absent,
        "pending_nights": pending,
        # Retained compatibility field now means a day with recorded fills.
        "observation_day_count": sum(1 for day in expected if day in filled),
        "calendar_run_day_count": sum(1 for day in expected if day in recorded),
        "data_unavailable_day_count": sum(1 for day in expected if day in data_unavailable),
        "filled_day_count": sum(1 for day in expected if day in filled),
        "filled_nights": sorted(day for day in filled if day in expected or day in pending),
    }


def earliest_hung_at(sleeves: list[Any]) -> datetime | None:
    stamps = [
        parsed
        for sleeve in sleeves
        if _is_official_sleeve(sleeve)
        for parsed in [_parse_stamp(getattr(sleeve, "created_at", None))]
        if parsed is not None
    ]
    return min(stamps) if stamps else None


def build_observation_calendar(
    *,
    sleeve_storage: Any,
    now: datetime,
    account_positions: Any | None = None,
) -> dict[str, Any]:
    sleeves = [
        sleeve
        for sleeve in sleeve_storage.list_sleeves()
        if _is_official_sleeve(sleeve)
        and str((getattr(sleeve, "metadata", None) or {}).get("automation_source", "")) == "d34"
    ]
    recorded = collect_recorded_nights(
        sleeves=sleeves,
        storage=sleeve_storage,
        account_positions=account_positions,
    )
    data_unavailable = collect_data_unavailable_nights(
        sleeves=sleeves,
        storage=sleeve_storage,
    )
    return reconcile_observation_nights(
        hung_at=earliest_hung_at(sleeves),
        now=now,
        recorded_nights=recorded,
        data_unavailable_nights=data_unavailable,
        filled_nights=collect_filled_nights(sleeves=sleeves, storage=sleeve_storage),
    )


__all__ = [
    "ABSENT_YESTERDAY_LABEL_ZH",
    "NOT_SCHEDULED_YESTERDAY_LABEL_ZH",
    "PENDING_YESTERDAY_LABEL_ZH",
    "RECORDED_YESTERDAY_LABEL_ZH",
    "build_observation_calendar",
    "collect_recorded_nights",
    "collect_data_unavailable_nights",
    "collect_filled_nights",
    "earliest_hung_at",
    "reconcile_observation_nights",
]
