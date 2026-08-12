from __future__ import annotations

import hashlib
import json
import re
import sys
import types
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from quant_system.brief.rollup import (
    RollupEmpty,
    RollupRejected,
    build_facts,
    default_period,
    generate_rollup,
    monthly_period,
    parse_period,
    weekly_period,
)
from quant_system.brief.rollup_llm import RollupLlmUnavailable
from quant_system.brief.rollup_service import BriefRollupService, _new_rollup_public_id
from quant_system.cli import app

runner = CliRunner()


def _ensure_rollup_repository_module() -> Any:
    """Return the rollup archive module, installing a contract-faithful stand-in
    when agent A's ``rollup_repository.py`` has not landed yet. The CLI command
    imports it lazily at invocation time, so tests only need the names to exist.
    """
    try:
        from quant_system.brief import rollup_repository as module

        return module
    except ModuleNotFoundError:
        pass

    module = types.ModuleType("quant_system.brief.rollup_repository")

    @dataclass(frozen=True)
    class BriefRollupIssue:
        rollup_id: str
        public_id: str
        kind: str
        period_key: str
        period_start: date
        period_end: date
        locale: str
        status: str

    @dataclass(frozen=True)
    class BriefRollupSnapshot:
        snapshot_id: str
        version: int
        payload: dict[str, Any]
        source_watermark: dict[str, Any] = field(default_factory=dict)

    @dataclass(frozen=True)
    class BriefRollupEnvelope:
        issue: BriefRollupIssue
        snapshot: BriefRollupSnapshot
        warnings: list[str] = field(default_factory=list)

    @dataclass(frozen=True)
    class BriefRollupListItem:
        public_id: str
        kind: str
        period_key: str
        period_start: date
        period_end: date
        locale: str
        status: str
        title: str
        snippet: str

    class BriefRollupDatabaseUnavailable(RuntimeError):
        pass

    class BriefRollupNotFound(LookupError):
        pass

    class BriefRollupRepository:
        def __init__(self, settings: Any) -> None:
            self._settings = settings

    names = {
        "BriefRollupIssue": BriefRollupIssue,
        "BriefRollupSnapshot": BriefRollupSnapshot,
        "BriefRollupEnvelope": BriefRollupEnvelope,
        "BriefRollupListItem": BriefRollupListItem,
        "BriefRollupDatabaseUnavailable": BriefRollupDatabaseUnavailable,
        "BriefRollupNotFound": BriefRollupNotFound,
        "BriefRollupRepository": BriefRollupRepository,
    }
    for name, value in names.items():
        setattr(module, name, value)
    module.__all__ = list(names)
    sys.modules["quant_system.brief.rollup_repository"] = module
    return module


_ensure_rollup_repository_module()


def _daily_payload(
    *,
    equity: float,
    lede: str,
    market_note: str = "SPY 小幅上涨。",
    news_ids: tuple[str, ...] = (),
    hermes_statuses: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    issue_date: str = "2026-08-10",
) -> dict[str, Any]:
    return {
        "schema_version": "brief_snapshot_v1",
        "title": "每日晨报",
        "issue_date": issue_date,
        "locale": "zh",
        "lede": lede,
        "account": {
            "account_id": "default",
            "base_currency": "USD",
            "equity": equity,
            "cash": equity * 0.6,
            "pnl_abs": equity - 100_000,
            "pnl_pct": round(equity / 100_000 - 1, 6),
            "invested_pct": 0.4,
        },
        "markets": [
            {"symbol": "SPY", "change_pct": 0.004},
            {"symbol": "QQQ", "change_pct": None},
        ],
        "market_note": market_note,
        "ai_news": [
            {
                "id": news_id,
                "title": f"标题 {news_id}",
                "url": f"https://example.com/{news_id}",
                "source": "example",
                "published_at": f"{issue_date}T01:00:00Z",
            }
            for news_id in news_ids
        ],
        "hermes_log": [{"status": status, "text": "日志"} for status in hermes_statuses],
        "warnings": list(warnings),
    }


def _issues() -> list[tuple[str, date, dict[str, Any]]]:
    return [
        (
            "brf_20260810_abc123",
            date(2026, 8, 10),
            _daily_payload(
                equity=100_000.0,
                lede="周一晨报。",
                news_ids=("n1", "n2"),
                hermes_statuses=("ok", "warn"),
                warnings=("w-a",),
                issue_date="2026-08-10",
            ),
        ),
        (
            "brf_20260812_def456",
            date(2026, 8, 12),
            _daily_payload(
                equity=103_000.0,
                lede="周三晨报。",
                news_ids=("n1", "n3"),
                hermes_statuses=("ok",),
                warnings=("w-a", "w-b"),
                issue_date="2026-08-12",
            ),
        ),
    ]


def _valid_draft() -> dict[str, Any]:
    return {
        "title": "本周主线",
        "main_storyline": "本期主线叙述。",
        "topics": [
            {"title": "主题一", "synthesis": "综合一。", "item_refs": ["n1"]},
            {"title": "主题二", "synthesis": "综合二。", "item_refs": ["n2", "n3"]},
            {"title": "主题三", "synthesis": "综合三。", "item_refs": []},
        ],
    }


class _StubLlm:
    model = "stub-model"
    critic_model = "stub-critic"

    def __init__(
        self,
        drafts: list[dict[str, Any]],
        critiques: list[dict[str, Any]],
    ) -> None:
        self._drafts = list(drafts)
        self._critiques = list(critiques)
        self.draft_calls = 0
        self.critique_calls = 0

    def draft(self, facts: dict[str, Any]) -> dict[str, Any]:
        self.draft_calls += 1
        return self._drafts.pop(0)

    def critique(self, facts: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
        self.critique_calls += 1
        return self._critiques.pop(0)


# --- period helpers -------------------------------------------------------


def test_weekly_period_is_iso_monday_to_sunday() -> None:
    key, start, end = weekly_period(date(2026, 8, 12))
    assert key == "2026-W33"
    assert start == date(2026, 8, 10)
    assert end == date(2026, 8, 16)
    assert start.strftime("%A") == "Monday"
    assert end.strftime("%A") == "Sunday"


def test_weekly_period_uses_iso_year_across_new_year() -> None:
    key, start, end = weekly_period(date(2026, 1, 1))
    assert key == "2026-W01"
    assert start == date(2025, 12, 29)
    assert end == date(2026, 1, 4)


def test_monthly_period_covers_full_calendar_month() -> None:
    assert monthly_period(2026, 8) == ("2026-08", date(2026, 8, 1), date(2026, 8, 31))
    assert monthly_period(2024, 2) == ("2024-02", date(2024, 2, 1), date(2024, 2, 29))
    assert monthly_period(2026, 12) == ("2026-12", date(2026, 12, 1), date(2026, 12, 31))


def test_default_period_weekly_is_current_iso_week() -> None:
    assert default_period("weekly", date(2026, 8, 12)) == (
        "2026-W33",
        date(2026, 8, 10),
        date(2026, 8, 16),
    )


def test_default_period_monthly_is_previous_calendar_month() -> None:
    assert default_period("monthly", date(2026, 8, 12)) == (
        "2026-07",
        date(2026, 7, 1),
        date(2026, 7, 31),
    )
    assert default_period("monthly", date(2026, 1, 5)) == (
        "2025-12",
        date(2025, 12, 1),
        date(2025, 12, 31),
    )


def test_default_period_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unsupported rollup kind"):
        default_period("yearly", date(2026, 8, 12))


def test_parse_period_weekly_normalizes_and_validates() -> None:
    assert parse_period("weekly", "2026-W33") == (
        "2026-W33",
        date(2026, 8, 10),
        date(2026, 8, 16),
    )
    with pytest.raises(ValueError, match="expected YYYY-Www"):
        parse_period("weekly", "2026-08")
    with pytest.raises(ValueError, match="ISO week does not exist"):
        parse_period("weekly", "2026-W99")


def test_parse_period_monthly_validates_shape_and_range() -> None:
    assert parse_period("monthly", "2026-08") == (
        "2026-08",
        date(2026, 8, 1),
        date(2026, 8, 31),
    )
    with pytest.raises(ValueError, match="expected YYYY-MM"):
        parse_period("monthly", "2026-W33")
    with pytest.raises(ValueError, match="month must be 01-12"):
        parse_period("monthly", "2026-13")
    with pytest.raises(ValueError, match="unsupported rollup kind"):
        parse_period("yearly", "2026")


# --- facts package ---------------------------------------------------------


def test_build_facts_extracts_days_items_and_computes_stats() -> None:
    facts = build_facts(
        kind="weekly",
        period_key="2026-W33",
        period_start=date(2026, 8, 10),
        period_end=date(2026, 8, 16),
        locale="zh",
        issues=_issues(),
    )

    assert facts["kind"] == "weekly"
    assert facts["period"] == {"start": "2026-08-10", "end": "2026-08-16"}
    assert [day["issue_date"] for day in facts["days"]] == ["2026-08-10", "2026-08-12"]
    first, second = facts["days"]
    assert first["lede"] == "周一晨报。"
    assert first["markets"] == [
        {"symbol": "SPY", "change_pct": 0.004},
        {"symbol": "QQQ", "change_pct": None},
    ]
    assert first["hermes_log_count"] == 2
    assert first["hermes_log_warn_count"] == 1
    assert second["hermes_log_count"] == 1
    assert second["hermes_log_warn_count"] == 0

    assert [item["id"] for item in facts["items"]] == ["n1", "n2", "n1", "n3"]
    recurring = [item for item in facts["items"] if item["id"] == "n1"]
    assert [item["issue_date"] for item in recurring] == ["2026-08-10", "2026-08-12"]
    assert recurring[0]["url"] == "https://example.com/n1"

    assert facts["stats"] == {
        "daily_count": 2,
        "event_count": 4,
        "equity_start": 100_000.0,
        "equity_end": 103_000.0,
        "period_change_pct": pytest.approx(0.03),
        "warning_count": 2,
    }
    assert facts["account_summary"]["start"]["equity"] == 100_000.0
    assert facts["account_summary"]["end"]["equity"] == 103_000.0
    assert facts["account_summary"]["period_change_pct"] == pytest.approx(0.03)
    assert facts["warnings"] == ["w-a", "w-b"]


# --- generate_rollup pipeline ----------------------------------------------


def _generate(llm: _StubLlm) -> dict[str, Any]:
    return generate_rollup(
        kind="weekly",
        period_key="2026-W33",
        period_start=date(2026, 8, 10),
        period_end=date(2026, 8, 16),
        locale="zh",
        issues=_issues(),
        llm=llm,
    )


def test_generate_rollup_empty_period_raises_without_calling_llm() -> None:
    llm = _StubLlm([_valid_draft()], [{"ok": True, "violations": []}])
    with pytest.raises(RollupEmpty, match="no daily brief issues"):
        generate_rollup(
            kind="weekly",
            period_key="2026-W33",
            period_start=date(2026, 8, 10),
            period_end=date(2026, 8, 16),
            locale="zh",
            issues=[],
            llm=llm,
        )
    assert llm.draft_calls == 0
    assert llm.critique_calls == 0


def test_generate_rollup_happy_path_assembles_validated_payload() -> None:
    llm = _StubLlm([_valid_draft()], [{"ok": True, "violations": []}])

    payload = _generate(llm)

    assert payload["schema_version"] == "brief_rollup_v1"
    assert payload["kind"] == "weekly"
    assert payload["period_key"] == "2026-W33"
    assert payload["locale"] == "zh"
    assert payload["title"] == "本周主线"
    assert payload["date_range"] == {"start": "2026-08-10", "end": "2026-08-16"}
    assert payload["main_storyline"] == "本期主线叙述。"
    assert payload["stats"]["daily_count"] == 2
    assert payload["stats"]["period_change_pct"] == pytest.approx(0.03)

    topics = payload["topics"]
    assert [topic["index"] for topic in topics] == [0, 1, 2]
    assert topics[0]["item_refs"] == ["n1"]
    assert topics[0]["source_items"] == [
        {
            "id": "n1",
            "title": "标题 n1",
            "url": "https://example.com/n1",
            "source": "example",
            "published_at": "2026-08-10T01:00:00Z",
            "issue_date": "2026-08-10",
        }
    ]
    assert [item["id"] for item in topics[1]["source_items"]] == ["n2", "n3"]
    assert topics[2]["source_items"] == []

    assert payload["account_summary"]["start"]["equity"] == 100_000.0
    assert payload["account_summary"]["end"]["cash"] == pytest.approx(61_800.0)

    provenance = payload["provenance"]
    assert provenance["model"] == "stub-model"
    assert provenance["critic_model"] == "stub-critic"
    assert provenance["source_issue_public_ids"] == [
        "brf_20260810_abc123",
        "brf_20260812_def456",
    ]
    assert isinstance(provenance["generated_at"], str) and provenance["generated_at"]
    facts = build_facts(
        kind="weekly",
        period_key="2026-W33",
        period_start=date(2026, 8, 10),
        period_end=date(2026, 8, 16),
        locale="zh",
        issues=_issues(),
    )
    expected_digest = hashlib.sha256(
        json.dumps(facts, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    assert provenance["facts_digest"] == expected_digest
    assert payload["warnings"] == ["w-a", "w-b"]
    assert llm.draft_calls == 1
    assert llm.critique_calls == 1


def test_generate_rollup_redrafts_once_after_unknown_item_refs() -> None:
    bad_draft = _valid_draft()
    bad_draft["topics"][0]["item_refs"] = ["ghost-id"]
    llm = _StubLlm(
        [bad_draft, _valid_draft()],
        [{"ok": True, "violations": []}],
    )

    payload = _generate(llm)

    assert payload["title"] == "本周主线"
    assert llm.draft_calls == 2
    # The programmatic ref check rejects the first draft before any critique.
    assert llm.critique_calls == 1


def test_generate_rollup_redrafts_once_after_critic_rejection() -> None:
    llm = _StubLlm(
        [_valid_draft(), _valid_draft()],
        [
            {"ok": False, "violations": ["草稿引入了事实包之外的数字"]},
            {"ok": True, "violations": []},
        ],
    )

    payload = _generate(llm)

    assert payload["schema_version"] == "brief_rollup_v1"
    assert llm.draft_calls == 2
    assert llm.critique_calls == 2


def test_generate_rollup_rejects_after_two_failed_drafts() -> None:
    bad_draft = _valid_draft()
    bad_draft["topics"][0]["item_refs"] = ["ghost-id"]
    llm = _StubLlm([bad_draft, dict(bad_draft)], [])

    with pytest.raises(RollupRejected, match="unknown item ids"):
        _generate(llm)
    assert llm.draft_calls == 2
    assert llm.critique_calls == 0


def test_generate_rollup_rejects_after_two_critic_rejections() -> None:
    llm = _StubLlm(
        [_valid_draft(), _valid_draft()],
        [
            {"ok": False, "violations": ["主线与主题不一致"]},
            {"ok": False, "violations": ["主线与主题不一致"]},
        ],
    )

    with pytest.raises(RollupRejected, match="主线与主题不一致"):
        _generate(llm)
    assert llm.draft_calls == 2
    assert llm.critique_calls == 2


@pytest.mark.parametrize(
    "broken",
    [
        [],  # not a JSON object at all
        {**_valid_draft(), "title": ""},  # title must be non-empty
        {**_valid_draft(), "topics": _valid_draft()["topics"][:2]},  # needs 3-7 topics
        {**_valid_draft(), "extra": True},  # extra=forbid
    ],
)
def test_generate_rollup_rejects_schema_invalid_drafts(broken: Any) -> None:
    llm = _StubLlm([broken, broken], [])

    with pytest.raises(RollupRejected):
        _generate(llm)
    assert llm.draft_calls == 2
    assert llm.critique_calls == 0


# --- service orchestration ---------------------------------------------------


class _FakeBriefRepository:
    def __init__(self, issues: list[tuple[str, date, dict[str, Any]]]) -> None:
        self._issues = issues
        self.calls: list[dict[str, Any]] = []

    def list_issue_payloads(
        self, *, locale: str, start: date, end: date
    ) -> list[tuple[str, date, dict[str, Any]]]:
        self.calls.append({"locale": locale, "start": start, "end": end})
        return self._issues


class _FakeRollupRepository:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.list_calls: list[dict[str, Any]] = []

    def create_snapshot(self, **kwargs: Any) -> Any:
        self.created.append(kwargs)
        return SimpleNamespace(
            issue=SimpleNamespace(
                public_id=kwargs["public_id"],
                kind=kwargs["kind"],
                period_key=kwargs["period_key"],
            ),
            snapshot=SimpleNamespace(version=1, payload=kwargs["payload"]),
            warnings=kwargs["payload"].get("warnings", []),
        )

    def get_latest_by_public_id(self, public_id: str) -> Any:
        self.get_calls.append(public_id)
        return f"envelope:{public_id}"

    def list_rollups(self, *, kind: str, locale: str, limit: int = 30) -> list[str]:
        self.list_calls.append({"kind": kind, "locale": locale, "limit": limit})
        return ["item"]


def test_service_generate_rollup_orchestrates_read_pipeline_write() -> None:
    brief_repository = _FakeBriefRepository(_issues())
    rollup_repository = _FakeRollupRepository()
    service = BriefRollupService(
        brief_repository,  # type: ignore[arg-type]
        rollup_repository,  # type: ignore[arg-type]
        _StubLlm([_valid_draft()], [{"ok": True, "violations": []}]),
    )

    envelope = service.generate_rollup(
        kind="weekly",
        period_key="2026-W33",
        period_start=date(2026, 8, 10),
        period_end=date(2026, 8, 16),
        locale="zh",
    )

    assert brief_repository.calls == [
        {"locale": "zh", "start": date(2026, 8, 10), "end": date(2026, 8, 16)}
    ]
    assert len(rollup_repository.created) == 1
    created = rollup_repository.created[0]
    assert created["kind"] == "weekly"
    assert created["period_key"] == "2026-W33"
    assert created["period_start"] == date(2026, 8, 10)
    assert created["period_end"] == date(2026, 8, 16)
    assert created["locale"] == "zh"
    assert re.fullmatch(r"brw_20260810_[a-z0-9]{6}", created["public_id"])
    payload = created["payload"]
    assert payload["schema_version"] == "brief_rollup_v1"
    assert created["source_watermark"]["facts_digest"] == (
        payload["provenance"]["facts_digest"]
    )
    assert created["source_watermark"]["source_issue_public_ids"] == [
        "brf_20260810_abc123",
        "brf_20260812_def456",
    ]
    assert envelope.issue.public_id == created["public_id"]
    assert envelope.snapshot.version == 1


def test_new_rollup_public_id_prefixes_by_kind() -> None:
    assert re.fullmatch(
        r"brw_20260810_[a-z0-9]{6}", _new_rollup_public_id("weekly", date(2026, 8, 10))
    )
    assert re.fullmatch(
        r"brm_20260701_[a-z0-9]{6}", _new_rollup_public_id("monthly", date(2026, 7, 1))
    )


def test_service_generate_rollup_requires_llm() -> None:
    service = BriefRollupService(
        _FakeBriefRepository(_issues()),  # type: ignore[arg-type]
        _FakeRollupRepository(),  # type: ignore[arg-type]
    )
    with pytest.raises(RollupLlmUnavailable, match="not configured"):
        service.generate_rollup(
            kind="weekly",
            period_key="2026-W33",
            period_start=date(2026, 8, 10),
            period_end=date(2026, 8, 16),
            locale="zh",
        )


def test_service_read_methods_delegate_to_rollup_repository() -> None:
    rollup_repository = _FakeRollupRepository()
    service = BriefRollupService(
        _FakeBriefRepository([]),  # type: ignore[arg-type]
        rollup_repository,  # type: ignore[arg-type]
    )

    assert service.get_rollup("brw_20260810_x1") == "envelope:brw_20260810_x1"
    assert rollup_repository.get_calls == ["brw_20260810_x1"]

    assert service.list_rollups(kind="monthly", locale=" zh ", limit=5) == ["item"]
    assert rollup_repository.list_calls == [
        {"kind": "monthly", "locale": "zh", "limit": 5}
    ]


# --- CLI ---------------------------------------------------------------------


def _cli_envelope() -> Any:
    return SimpleNamespace(
        issue=SimpleNamespace(
            public_id="brw_20260810_x1y2z3",
            kind="weekly",
            period_key="2026-W33",
        ),
        snapshot=SimpleNamespace(version=1),
        warnings=[],
    )


def _patch_cli_service(monkeypatch: pytest.MonkeyPatch, service_instance: Any) -> None:
    monkeypatch.setattr(
        "quant_system.brief.rollup_service.BriefRollupService",
        lambda *args, **kwargs: service_instance,
    )


def _last_output_json(result: Any) -> dict[str, Any]:
    lines = [line for line in result.output.strip().splitlines() if line.strip()]
    return json.loads(lines[-1])


def test_cli_rollup_success_emits_machine_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SimpleNamespace(
        generate_rollup=lambda **kwargs: _cli_envelope(),
    )
    _patch_cli_service(monkeypatch, service)

    result = runner.invoke(
        app, ["brief", "rollup", "--kind", "weekly", "--period", "2026-W33"]
    )

    assert result.exit_code == 0
    body = _last_output_json(result)
    assert body == {
        "ok": True,
        "public_id": "brw_20260810_x1y2z3",
        "kind": "weekly",
        "period_key": "2026-W33",
        "snapshot_version": 1,
        "warnings": [],
    }


def test_cli_rollup_invalid_period_exits_two() -> None:
    result = runner.invoke(
        app, ["brief", "rollup", "--kind", "weekly", "--period", "2026-08"]
    )

    assert result.exit_code == 2
    body = _last_output_json(result)
    assert body["ok"] is False
    assert body["error"]["code"] == "brief_rollup_invalid_period"


def test_cli_rollup_invalid_kind_exits_two() -> None:
    result = runner.invoke(app, ["brief", "rollup", "--kind", "yearly"])

    assert result.exit_code == 2
    body = _last_output_json(result)
    assert body["ok"] is False
    assert body["error"]["code"] == "brief_rollup_invalid_kind"


def test_cli_rollup_empty_period_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_empty(**kwargs: Any) -> Any:
        raise RollupEmpty("no daily brief issues inside 2026-08-10..2026-08-16")

    _patch_cli_service(monkeypatch, SimpleNamespace(generate_rollup=_raise_empty))

    result = runner.invoke(
        app, ["brief", "rollup", "--kind", "weekly", "--period", "2026-W33"]
    )

    assert result.exit_code == 1
    body = _last_output_json(result)
    assert body["ok"] is False
    assert body["error"]["code"] == "brief_rollup_empty"
