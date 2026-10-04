"""Stored factor scorecard dashboard, with explicit owner-triggered refresh.

Mirrors ``api/routes/research_evaluation.py``: the GET path only reads the stored
result or frozen wide selection (never recomputing statistics) while an explicit, mutation-secured
POST schedules one refresh under a module-level lock and answers ``202``.
"""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from quant_system.api.dependencies import (
    OutputDirDep,
    SettingsDep,
    require_mutation_security,
)
from quant_system.api.schemas.factor_scorecards import (
    FactorScorecardRefreshRequest,
    FactorScorecardsResponse,
)
from quant_system.factors.scorecard_service import (
    SCORECARD_DIR_NAME,
    read_factor_scorecards,
    record_scorecard_operation,
    refresh_factor_scorecards,
)

router = APIRouter()
_SCORECARD_LOCK = Lock()


def _scorecard_dir(output_dir: Path) -> Path:
    """Root the store under ``<output_dir>/factor_scorecards`` (design §1.3 layout).

    ``scorecard_service`` treats an explicit ``output_dir`` as the final base, so the
    route appends the directory name itself; with the default app output dir this
    resolves to ``<data_dir>/factor_scorecards``.
    """
    return Path(output_dir) / SCORECARD_DIR_NAME


@router.get("/factor-scorecards", response_model=FactorScorecardsResponse)
def get_factor_scorecards(settings: SettingsDep, output_dir: OutputDirDep) -> dict:
    result = read_factor_scorecards(settings, output_dir=_scorecard_dir(output_dir))
    if _SCORECARD_LOCK.locked():
        result = {
            **result,
            "status": "updating",
            "progress": "正在刷新因子记分卡，完成后会保存结果",
        }
    return result


def _scorecard_refresh(settings, output_dir: Path, request: dict) -> None:
    try:
        record_scorecard_operation(
            settings, output_dir=_scorecard_dir(output_dir), action="refresh", status="running"
        )
        result = refresh_factor_scorecards(settings, request, output_dir=_scorecard_dir(output_dir))
        reason = result.get("reason") if isinstance(result, dict) else None
        record_scorecard_operation(
            settings,
            output_dir=_scorecard_dir(output_dir),
            action="refresh",
            status="failed" if reason else "completed",
            reason=reason,
        )
    except Exception as exc:
        record_scorecard_operation(
            settings,
            output_dir=_scorecard_dir(output_dir),
            action="refresh",
            status="failed",
            reason=f"scorecard_refresh_failed:{type(exc).__name__}",
        )
    finally:
        _SCORECARD_LOCK.release()


@router.post(
    "/factor-scorecards/refresh",
    response_model=FactorScorecardsResponse,
    status_code=202,
    dependencies=[Depends(require_mutation_security)],
)
def start_factor_scorecard_refresh(
    request: FactorScorecardRefreshRequest,
    settings: SettingsDep,
    output_dir: OutputDirDep,
    background_tasks: BackgroundTasks,
) -> dict:
    previous = read_factor_scorecards(settings, output_dir=_scorecard_dir(output_dir))
    if not _SCORECARD_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="另一次因子记分卡刷新正在运行，请在它完成后启动此项。",
        )
    background_tasks.add_task(_scorecard_refresh, settings, output_dir, request.model_dump())
    return {
        **previous,
        "status": "updating",
        "progress": "正在刷新因子记分卡，完成后会保存结果",
    }
