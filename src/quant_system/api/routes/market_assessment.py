from __future__ import annotations

import json
from datetime import UTC, date, datetime
from threading import Lock
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends

from quant_system.api.dependencies import SettingsDep, require_mutation_security
from quant_system.api.schemas.market_assessment import (
    MarketAssessmentRefreshRequest,
    MarketAssessmentResponse,
)
from quant_system.brief.rollup_llm import RollupLlmClient
from quant_system.factors.market_assessment import (
    ANALYSIS_VERSION,
    add_ai_analysis,
    assessment_path,
    collect_assessment,
)

router = APIRouter()
_REFRESH_LOCKS = {"us": Lock(), "asia": Lock()}


def _empty(scope: str) -> dict:
    return {
        "scope": scope,
        "status": "unavailable",
        "as_of": None,
        "updated_at": None,
        "input_digest": None,
        "score": None,
        "scores": {"pressure": None, "valuation": None, "bubble": None},
        "coverage": {"available": 0, "total": 0, "weight_pct": 0},
        "factors": [],
        "rule_assessment": {
            "headline": "尚未生成市场研判",
            "stance": "等待更新",
            "reasons": ["更新后将取得公开估值与现有行情，并生成有来源的判断。"],
            "watch_next": [],
            "invalidations": [],
        },
        "ai_analysis": None,
        "ai_error": None,
        "market_rows": [],
    }


def _read(settings, scope) -> dict:
    path = assessment_path(settings, scope)
    if not path.exists():
        return _empty(scope)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        MarketAssessmentResponse.model_validate(document)
        if document["scope"] != scope:
            raise ValueError("cached_scope_mismatch")
        now = datetime.now(UTC)
        if document["updated_at"] is not None:
            updated = datetime.fromisoformat(document["updated_at"])
            if updated.tzinfo is None or updated > now:
                raise ValueError("cached_update_time_invalid")
        if document["as_of"] is not None and date.fromisoformat(document["as_of"]) > now.date():
            raise ValueError("cached_as_of_future")
        return document
    except (OSError, ValueError):
        document = _empty(scope)
        document["status"] = "failed"
        document["ai_error"] = "上次市场研判缓存无法读取，请重新更新。"
        return document


def _write(settings, scope, document):
    path = assessment_path(settings, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    temporary.replace(path)


@router.get("/market-assessment", response_model=MarketAssessmentResponse)
def market_assessment(settings: SettingsDep, scope: Literal["us", "asia"] = "us") -> dict:
    document = _read(settings, scope)
    if document["status"] == "updating" and not _REFRESH_LOCKS[scope].locked():
        document["status"] = "failed"
        document["ai_error"] = "上次更新已中断，请重新更新；页面读取不会自动调用模型。"
    elif document["updated_at"] and document["status"] != "updating":
        updated = datetime.fromisoformat(document["updated_at"])
        if (datetime.now(UTC) - updated).total_seconds() > 36 * 3600:
            document["status"] = "partial"
            document["rule_assessment"]["headline"] = "这是上次研判，数据已超过36小时，请先更新"
            document["rule_assessment"]["stance"] = "等待更新"
    return document


def _refresh(settings, request, previous):
    scope = request.scope
    try:
        result = collect_assessment(settings, scope)
        terminal_status = result["status"]
        result["status"] = "updating"
        _write(settings, scope, result)
        if request.include_ai:
            prior = previous.get("ai_analysis")
            llm = RollupLlmClient()
            if (
                prior
                and prior.get("input_digest") == result["input_digest"]
                and prior.get("model") == llm.model
                and prior.get("reasoning_effort") == llm.reasoning_effort
                and prior.get("analysis_version") == ANALYSIS_VERSION
            ):
                result["ai_analysis"] = prior
            else:
                add_ai_analysis(result)
            if result["ai_error"] and prior and prior.get("input_digest") == result["input_digest"]:
                result["ai_analysis"] = prior
        result["status"] = (
            "partial" if result["ai_error"] and terminal_status == "ready" else terminal_status
        )
        _write(settings, scope, result)
    except Exception as exc:  # Network/IO boundary; never mark an incomplete refresh as success.
        previous["status"] = "failed"
        previous["ai_error"] = f"市场研判更新失败：{type(exc).__name__}；未生成新的判断。"
        _write(settings, scope, previous)
    finally:
        _REFRESH_LOCKS[scope].release()


@router.post(
    "/market-assessment/refresh",
    response_model=MarketAssessmentResponse,
    status_code=202,
    dependencies=[Depends(require_mutation_security)],
)
def refresh_market_assessment(
    request: MarketAssessmentRefreshRequest,
    settings: SettingsDep,
    background_tasks: BackgroundTasks,
) -> dict:
    previous = _read(settings, request.scope)
    if not _REFRESH_LOCKS[request.scope].acquire(blocking=False):
        return {**previous, "status": "updating"}
    try:
        queued = {**previous, "status": "updating", "ai_error": None}
        _write(settings, request.scope, queued)
        background_tasks.add_task(_refresh, settings, request, previous)
        return queued
    except Exception:
        _REFRESH_LOCKS[request.scope].release()
        raise
