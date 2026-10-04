"""Saved research reads and one explicit owner-triggered background refresh."""

from datetime import date
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from quant_system.api.dependencies import SettingsDep, require_mutation_security
from quant_system.api.schemas.strategy_studies import (
    StrategyStudiesRequest,
    StrategyStudiesResponse,
    StrategyStudyProfileResponse,
)
from quant_system.research.strategy_study_service import (
    read_studies,
    read_study_profile,
    run_studies,
)

router = APIRouter()
_STUDY_LOCK = Lock()
_ACTIVE_DISCOVERY: bool | None = None


@router.get("/strategy-studies", response_model=StrategyStudiesResponse)
def get_strategy_studies(settings: SettingsDep):
    result = read_studies(settings)
    if _STUDY_LOCK.locked() and result["status"] != "updating":
        return {**result, "status": "updating", "progress": "等待计算资源或正在研究"}
    return result


@router.get(
    "/strategy-studies/{run_id}/profiles/{profile_id}", response_model=StrategyStudyProfileResponse
)
def get_strategy_study_profile(
    run_id: str, profile_id: str, settings: SettingsDep, signal_date: date | None = None
):
    try:
        return read_study_profile(
            settings,
            run_id,
            profile_id,
            signal_date=signal_date.isoformat() if signal_date else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到指定研究、方案或信号日期。") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="研究标识或已保存证据无效。") from exc


@router.get("/strategy-studies/{run_id}", response_model=StrategyStudiesResponse)
def get_strategy_study_run(run_id: str, settings: SettingsDep):
    try:
        return read_studies(settings, run_id=run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到指定研究。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="研究标识无效。") from exc


def _refresh(settings, include_discovery):
    global _ACTIVE_DISCOVERY
    try:
        run_studies(settings, include_discovery=include_discovery)
    finally:
        _ACTIVE_DISCOVERY = None
        _STUDY_LOCK.release()


@router.post(
    "/strategy-studies/refresh",
    response_model=StrategyStudiesResponse,
    status_code=202,
    dependencies=[Depends(require_mutation_security)],
)
def start_strategy_studies(
    request: StrategyStudiesRequest, settings: SettingsDep, background_tasks: BackgroundTasks
):
    global _ACTIVE_DISCOVERY
    previous = read_studies(settings)
    if _STUDY_LOCK.acquire(blocking=False):
        # An explicitly started CLI run may own the service's process lock.
        # Do not queue a second refresh behind it or silently add model work.
        if previous["status"] == "updating":
            _STUDY_LOCK.release()
            if request.include_discovery:
                raise HTTPException(
                    status_code=409,
                    detail="已有研究正在运行；请等待完成后再启动包含因子探索的研究。",
                )
            return previous
        _ACTIVE_DISCOVERY = request.include_discovery
        background_tasks.add_task(_refresh, settings, request.include_discovery)
    elif request.include_discovery != _ACTIVE_DISCOVERY:
        raise HTTPException(
            status_code=409,
            detail="另一种研究任务正在运行，不能在运行中更改因子探索选项。",
        )
    return {**previous, "status": "updating", "progress": "正在运行用途研究，完成后会保存结果"}
