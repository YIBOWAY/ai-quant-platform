"""Existing-account read-only evaluation, with explicit owner-triggered computation."""

from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from quant_system.api.dependencies import SettingsDep, require_mutation_security
from quant_system.api.schemas.research_evaluation import (
    RESEARCH_KEY_PATTERN,
    PaperEvaluationResponse,
    ResearchEvaluationRequest,
    ResearchEvaluationResponse,
)
from quant_system.research.evaluation_service import read_evaluation, refresh_evaluation
from quant_system.research.paper_evaluation import read_paper_evaluation, refresh_paper_evaluation

router = APIRouter()
_RESEARCH_LOCK = Lock()
_PAPER_LOCK = Lock()
_ACTIVE_KEY: str | None = None


@router.get("/research-evaluation", response_model=ResearchEvaluationResponse)
def get_evaluation(
    settings: SettingsDep,
    key: str | None = Query(default=None, pattern=RESEARCH_KEY_PATTERN),
):
    result = read_evaluation(settings, key)
    if _RESEARCH_LOCK.locked() and key == _ACTIVE_KEY:
        result = {**result, "status": "updating", "progress": "等待计算资源或正在评价"}
    return result


def _research_refresh(settings, key):
    try:
        refresh_evaluation(settings, key)
    finally:
        _RESEARCH_LOCK.release()


@router.post(
    "/research-evaluation/refresh",
    response_model=ResearchEvaluationResponse,
    status_code=202,
    dependencies=[Depends(require_mutation_security)],
)
def start_evaluation(
    request: ResearchEvaluationRequest, settings: SettingsDep, background_tasks: BackgroundTasks
):
    global _ACTIVE_KEY
    if request.key and request.key.startswith("research:strategy-"):
        raise HTTPException(
            status_code=409,
            detail="这是一份完整策略，请在“我的策略”按它自己的持仓与调仓规则验证；不能改用旧单因子评价。",
        )
    previous = read_evaluation(settings, request.key)
    if _RESEARCH_LOCK.acquire(blocking=False):
        _ACTIVE_KEY = request.key
        background_tasks.add_task(_research_refresh, settings, request.key)
    elif request.key != _ACTIVE_KEY:
        raise HTTPException(status_code=409, detail="另一项评价正在运行，请在它完成后启动此项。")
    return {**previous, "status": "updating", "progress": "正在运行研究评价，完成后会保存结果"}


@router.get("/paper-evaluation", response_model=PaperEvaluationResponse)
def get_paper_evaluation(settings: SettingsDep):
    result = read_paper_evaluation(settings)
    if _PAPER_LOCK.locked():
        result = {**result, "status": "updating"}
    return result


def _paper_refresh(settings):
    try:
        refresh_paper_evaluation(settings)
    finally:
        _PAPER_LOCK.release()


@router.post(
    "/paper-evaluation/refresh",
    response_model=PaperEvaluationResponse,
    status_code=202,
    dependencies=[Depends(require_mutation_security)],
)
def start_paper_evaluation(settings: SettingsDep, background_tasks: BackgroundTasks):
    if _PAPER_LOCK.acquire(blocking=False):
        background_tasks.add_task(_paper_refresh, settings)
    return {**read_paper_evaluation(settings), "status": "updating"}
