"""Weekly/monthly brief rollup core: periods, facts, draft validation, payload.

Everything here is pure code and unit-testable: the LLM is injected behind the
``RollupLlm`` protocol and only ever writes prose (title, storyline, topic
syntheses). All numbers are computed in code from the daily brief payloads,
and every model claim is validated programmatically — a draft whose
``item_refs`` point outside the supplied item ids, or that fails the critic
pass twice, is rejected fail-closed and never persisted.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quant_system.brief.auto_archive import BRIEF_TIME_ZONE

ROLLUP_SCHEMA_VERSION = "brief_rollup_v1"
ROLLUP_KINDS = ("weekly", "monthly")
MAX_DRAFT_ATTEMPTS = 2
MAX_AGGREGATED_WARNINGS = 20

_WEEKLY_KEY = re.compile(r"^(\d{4})-W(\d{2})$")
_MONTHLY_KEY = re.compile(r"^(\d{4})-(\d{2})$")


class RollupEmpty(RuntimeError):
    """Raised when a period contains no daily brief issues to roll up."""


class RollupRejected(RuntimeError):
    """Raised when no drafted rollup survives validation plus critique."""


class RollupLlm(Protocol):
    def draft(self, facts: dict[str, Any]) -> dict[str, Any]: ...

    def critique(self, facts: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]: ...


class RollupDraftTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    synthesis: str = Field(min_length=1)
    item_refs: list[str] = Field(default_factory=list)


class RollupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    main_storyline: str = Field(min_length=1)
    topics: list[RollupDraftTopic] = Field(min_length=3, max_length=7)


def weekly_period(day: date) -> tuple[str, date, date]:
    """ISO week (Monday..Sunday) containing ``day``; key ``YYYY-Www``."""
    iso = day.isocalendar()
    start = day - timedelta(days=day.isoweekday() - 1)
    end = start + timedelta(days=6)
    return f"{iso.year}-W{iso.week:02d}", start, end


def monthly_period(year: int, month: int) -> tuple[str, date, date]:
    """Calendar month period; key ``YYYY-MM``."""
    start = date(year, month, 1)
    end = (
        date(year, 12, 31)
        if month == 12
        else date(year, month + 1, 1) - timedelta(days=1)
    )
    return f"{year}-{month:02d}", start, end


def default_period(kind: str, today: date) -> tuple[str, date, date]:
    """weekly = today's ISO week; monthly = the previous calendar month."""
    if kind == "weekly":
        return weekly_period(today)
    if kind == "monthly":
        previous_month_last_day = today.replace(day=1) - timedelta(days=1)
        return monthly_period(previous_month_last_day.year, previous_month_last_day.month)
    raise ValueError(f"unsupported rollup kind {kind!r}; expected weekly or monthly")


def parse_period(kind: str, text: str) -> tuple[str, date, date]:
    """Validate ``2026-W33`` (weekly) or ``2026-08`` (monthly) into a period."""
    value = text.strip()
    if kind == "weekly":
        match = _WEEKLY_KEY.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid weekly period {text!r}; expected YYYY-Www")
        year, week = int(match.group(1)), int(match.group(2))
        try:
            monday = date.fromisocalendar(year, week, 1)
        except ValueError:
            raise ValueError(f"invalid weekly period {text!r}; ISO week does not exist") from None
        return weekly_period(monday)
    if kind == "monthly":
        match = _MONTHLY_KEY.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid monthly period {text!r}; expected YYYY-MM")
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise ValueError(f"invalid monthly period {text!r}; month must be 01-12")
        return monthly_period(year, month)
    raise ValueError(f"unsupported rollup kind {kind!r}; expected weekly or monthly")


def build_facts(
    *,
    kind: str,
    period_key: str,
    period_start: date,
    period_end: date,
    locale: str,
    issues: list[tuple[str, date, dict[str, Any]]],
) -> dict[str, Any]:
    """Build the model-facing facts package from daily ``brief_snapshot_v1`` payloads.

    ``issues`` are ``(public_id, issue_date, payload)`` tuples as returned by
    ``BriefRepository.list_issue_payloads`` (ascending by date). Every number
    the payload later carries is computed here, in code.
    """
    days: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    aggregated_warnings: list[str] = []
    for public_id, issue_date, payload in issues:
        account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
        ai_news = payload.get("ai_news") if isinstance(payload.get("ai_news"), list) else []
        hermes_log = (
            payload.get("hermes_log") if isinstance(payload.get("hermes_log"), list) else []
        )
        day_items: list[dict[str, Any]] = []
        for raw_item in ai_news:
            if not isinstance(raw_item, dict):
                continue
            item_id = str(raw_item.get("id") or "").strip()
            if not item_id:
                continue
            entry = {
                "id": item_id,
                "title": str(raw_item.get("title") or ""),
                "url": str(raw_item.get("url") or ""),
                "source": str(raw_item.get("source") or ""),
                "published_at": _json_scalar(raw_item.get("published_at")),
                # Provenance: the same item id may recur across days; each
                # occurrence keeps the daily issue it was archived under.
                "issue_date": issue_date.isoformat(),
            }
            day_items.append(entry)
            items.append(entry)
        day_warnings = [str(w) for w in payload.get("warnings") or []]
        for warning in day_warnings:
            if warning not in aggregated_warnings:
                aggregated_warnings.append(warning)
        days.append(
            {
                "issue_date": issue_date.isoformat(),
                "public_id": public_id,
                "lede": str(payload.get("lede") or ""),
                "market_note": str(payload.get("market_note") or ""),
                "markets": [
                    {
                        "symbol": str(market.get("symbol") or ""),
                        "change_pct": _json_scalar(market.get("change_pct")),
                    }
                    for market in payload.get("markets") or []
                    if isinstance(market, dict)
                ],
                "account": {
                    key: _json_scalar(account.get(key))
                    for key in ("equity", "cash", "pnl_abs", "pnl_pct", "invested_pct")
                },
                "ai_news": day_items,
                "hermes_log_count": len(hermes_log),
                "hermes_log_warn_count": sum(
                    1
                    for entry_log in hermes_log
                    if isinstance(entry_log, dict) and entry_log.get("status") == "warn"
                ),
                "warnings": day_warnings,
            }
        )

    warnings = aggregated_warnings[:MAX_AGGREGATED_WARNINGS]
    stats = {
        "daily_count": len(days),
        "event_count": len(items),
        "equity_start": _account_number(days[0]["account"], "equity") if days else None,
        "equity_end": _account_number(days[-1]["account"], "equity") if days else None,
        "period_change_pct": _period_change_pct(
            _account_number(days[0]["account"], "equity") if days else None,
            _account_number(days[-1]["account"], "equity") if days else None,
        ),
        "warning_count": len(warnings),
    }
    account_summary = {
        "start": _account_snapshot(days[0]) if days else None,
        "end": _account_snapshot(days[-1]) if days else None,
        "period_change_pct": stats["period_change_pct"],
    }
    return {
        "kind": kind,
        "period_key": period_key,
        "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
        "locale": locale,
        "days": days,
        "items": items,
        "stats": stats,
        "account_summary": account_summary,
        "warnings": warnings,
    }


def generate_rollup(
    *,
    kind: str,
    period_key: str,
    period_start: date,
    period_end: date,
    locale: str,
    issues: list[tuple[str, date, dict[str, Any]]],
    llm: RollupLlm,
) -> dict[str, Any]:
    """Draft, validate, critique and assemble a ``brief_rollup_v1`` payload.

    Fail-closed: raises :class:`RollupEmpty` when the period has no daily
    issues and :class:`RollupRejected` when neither the first draft nor one
    redraft passes both the programmatic checks and the critic pass.
    """
    if not issues:
        raise RollupEmpty(
            f"no daily brief issues inside {period_start.isoformat()}..{period_end.isoformat()}"
        )
    facts = build_facts(
        kind=kind,
        period_key=period_key,
        period_start=period_start,
        period_end=period_end,
        locale=locale,
        issues=issues,
    )
    item_ids = {item["id"] for item in facts["items"]}

    last_problems: list[str] = []
    for _attempt in range(MAX_DRAFT_ATTEMPTS):
        raw_draft = llm.draft(facts)
        draft, problems = _validate_draft(raw_draft, item_ids)
        if draft is not None and not problems:
            critique = llm.critique(facts, draft.model_dump(mode="json"))
            if critique.get("ok") is True:
                return _assemble_payload(
                    kind=kind,
                    period_key=period_key,
                    period_start=period_start,
                    period_end=period_end,
                    locale=locale,
                    draft=draft,
                    facts=facts,
                    issues=issues,
                    llm=llm,
                )
            violations = critique.get("violations")
            last_problems = (
                [str(v) for v in violations] if isinstance(violations, list) and violations
                else ["critic rejected the draft without listing violations"]
            )
        else:
            last_problems = problems
    raise RollupRejected(
        "rollup draft rejected after "
        f"{MAX_DRAFT_ATTEMPTS} attempts: {'; '.join(last_problems[:3])}"
    )


def _validate_draft(
    raw_draft: Any, item_ids: set[str]
) -> tuple[RollupDraft | None, list[str]]:
    if not isinstance(raw_draft, dict):
        return None, ["draft is not a JSON object"]
    try:
        draft = RollupDraft.model_validate(raw_draft)
    except ValidationError as exc:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", ())) or "draft"
        return None, [f"draft schema invalid at {location}: {first.get('msg', exc)}"]
    problems: list[str] = []
    for index, topic in enumerate(draft.topics):
        unknown = [ref for ref in topic.item_refs if ref not in item_ids]
        if unknown:
            problems.append(
                f"topics[{index}] references unknown item ids: {', '.join(sorted(set(unknown)))}"
            )
    return (None, problems) if problems else (draft, [])


def _assemble_payload(
    *,
    kind: str,
    period_key: str,
    period_start: date,
    period_end: date,
    locale: str,
    draft: RollupDraft,
    facts: dict[str, Any],
    issues: list[tuple[str, date, dict[str, Any]]],
    llm: RollupLlm,
) -> dict[str, Any]:
    items_by_id: dict[str, dict[str, Any]] = {}
    for entry in facts["items"]:
        items_by_id.setdefault(entry["id"], entry)
    topics = [
        {
            "index": index,
            "title": topic.title,
            "synthesis": topic.synthesis,
            "item_refs": list(topic.item_refs),
            "source_items": [
                dict(items_by_id[ref]) for ref in topic.item_refs if ref in items_by_id
            ],
        }
        for index, topic in enumerate(draft.topics)
    ]
    facts_digest = hashlib.sha256(
        json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": ROLLUP_SCHEMA_VERSION,
        "kind": kind,
        "period_key": period_key,
        "locale": locale,
        "title": draft.title,
        "date_range": {
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
        },
        "main_storyline": draft.main_storyline,
        "stats": facts["stats"],
        "topics": topics,
        "account_summary": facts["account_summary"],
        "provenance": {
            "model": getattr(llm, "model", None),
            "critic_model": getattr(llm, "critic_model", getattr(llm, "model", None)),
            "generated_at": datetime.now(tz=BRIEF_TIME_ZONE).isoformat(),
            "source_issue_public_ids": [public_id for public_id, _, _ in issues],
            "facts_digest": facts_digest,
        },
        "warnings": facts["warnings"],
    }


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _account_number(account: dict[str, Any], key: str) -> float | None:
    value = account.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _account_snapshot(day: dict[str, Any]) -> dict[str, Any]:
    account = day["account"]
    return {
        "issue_date": day["issue_date"],
        "equity": _account_number(account, "equity"),
        "cash": _account_number(account, "cash"),
        "pnl_abs": _account_number(account, "pnl_abs"),
        "pnl_pct": _account_number(account, "pnl_pct"),
        "invested_pct": _account_number(account, "invested_pct"),
    }


def _period_change_pct(equity_start: float | None, equity_end: float | None) -> float | None:
    if equity_start is None or equity_end is None or equity_start == 0:
        return None
    # Percentage points (not a ratio), matching the platform's *_pct convention.
    return round((equity_end / equity_start - 1) * 100, 6)
