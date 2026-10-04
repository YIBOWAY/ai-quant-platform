"""Owner actions on immutable research strategies, never implicit page mutations."""

from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from quant_system.api.dependencies import OutputDirDep, SettingsDep, require_mutation_security
from quant_system.api.schemas.strategy_library import (
    StrategyFactorOptionsResponse,
    StrategyLibraryEntryResponse,
    StrategyLibraryResponse,
)
from quant_system.research import strategy_library as service
from quant_system.research.strategy_definition import StrategyFactor
from quant_system.research.strategy_validation_process import validate_in_research_runtime

router = APIRouter()
_LOCK = Lock()
_ACTIVE: str | None = None


class StudyImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    profile_id: str
    title: str | None = Field(default=None, min_length=1, max_length=200)


class BacktestImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    title: str | None = Field(default=None, min_length=1, max_length=200)


class StrategyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class ComposeStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["factor_blend"] = "factor_blend"
    title: str = Field(min_length=1, max_length=200)
    symbols: list[str] = Field(min_length=1)
    benchmark_symbol: str = "SPY"
    rebalance: Literal["daily", "weekly", "monthly"] = "monthly"
    top_n: int = Field(default=3, ge=1)
    normalization: Literal["rank", "zscore"] = "rank"
    max_weight_per_symbol: float = Field(default=1, gt=0, le=1)
    target_gross_exposure: float = Field(default=1, ge=0, le=1)
    min_order_value: float = Field(default=0, ge=0)
    factors: list[StrategyFactor] = Field(min_length=1)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail="strategy_record_not_found") from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, detail=str(exc)) from exc


def _project_research_evidence(settings, output_dir, items):
    """Attach existing research and paper facts only on read endpoints."""
    from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
    from quant_system.research.intake_factor_evaluation import research_evidence_for_strategy
    from quant_system.research.paper_runtime_status import read_paper_runtime_status

    storage = PaperStrategySleeveStorage(output_dir / "api_runs")
    try:
        sleeves = storage.list_sleeves()
    except (OSError, ValueError, KeyError, TypeError):
        sleeves = []
    for item in items:
        try:
            item["research_evidence"] = research_evidence_for_strategy(
                settings, item["strategy_id"],
            )
        except (OSError, ValueError, KeyError, TypeError):
            item["research_evidence"] = {
                "status": "unavailable", "reason": "intake_evidence_unavailable",
            }
        matching = [sleeve for sleeve in sleeves
                    if item.get("candidate_id")
                    and sleeve.metadata.get("candidate_id") == item["candidate_id"]]
        if len(matching) == 1:
            item["sleeve_id"] = matching[0].sleeve_id
            item["paper_runtime"] = read_paper_runtime_status(storage, matching[0])
    return items


def _waiting_research_materials(settings):
    """Project accepted material that has no executable strategy; never compile it."""
    from quant_system.research.external_intake import _jobs
    from quant_system.research.intake_factor_evaluation import verified_evaluation_chain

    materials = []
    for job in _jobs(settings):
        if job.get("status") != "waiting_data":
            continue
        evidence = verified_evaluation_chain(settings, job, include_material=True)
        materials.append({
            "job_id": job["job_id"], "proposal_id": job["proposal_id"],
            "status": "waiting_data", "created_at": job.get("created_at"),
            "expression": job["proposal"].get("expression"),
            "executable_strategy_count": len(job["plans"]),
            "research_design": evidence["research_design"],
            "disposition": evidence["disposition"], "identity": evidence["identity"],
        })
    return materials


@router.get(
    "/strategy-library", response_model=StrategyLibraryResponse, response_model_exclude_unset=True
)
def list_strategies(settings: SettingsDep, output_dir: OutputDirDep) -> dict[str, Any]:
    result = service.list_strategies(settings)
    _project_research_evidence(settings, output_dir, result["items"])
    try:
        result["data_needs"] = _waiting_research_materials(settings)
    except (OSError, ValueError, KeyError, TypeError):
        result["data_needs_error"] = "waiting_research_materials_unavailable"
    for item in result["items"]:
        if item["strategy_id"] == _ACTIVE:
            item["status"] = "validating"
    return result


@router.get(
    "/strategy-library/factor-options", response_model=StrategyFactorOptionsResponse,
    response_model_exclude_unset=True,
)
def factor_options(settings: SettingsDep) -> dict[str, Any]:
    return service.factor_options(settings)


@router.post(
    "/strategy-library/compose", dependencies=[Depends(require_mutation_security)],
    response_model=StrategyLibraryEntryResponse, response_model_exclude_unset=True,
)
def compose_strategy(request: ComposeStrategy, settings: SettingsDep) -> dict[str, Any]:
    return _call(service.compose_strategy, settings, request.model_dump(mode="json"))


@router.get(
    "/strategy-library/{strategy_id}", response_model=StrategyLibraryEntryResponse,
    response_model_exclude_unset=True,
)
def get_strategy(
    strategy_id: str, settings: SettingsDep, output_dir: OutputDirDep,
) -> dict[str, Any]:
    result = _call(service.read_strategy, settings, strategy_id)
    _project_research_evidence(settings, output_dir, [result])
    return {**result, "status": "validating"} if strategy_id == _ACTIVE else result


@router.post(
    "/strategy-library/import-study", dependencies=[Depends(require_mutation_security)],
    response_model=StrategyLibraryEntryResponse, response_model_exclude_unset=True,
)
def import_study(request: StudyImport, settings: SettingsDep) -> dict[str, Any]:
    return _call(
        service.import_study, settings, request.run_id, request.profile_id, title=request.title
    )


@router.post(
    "/strategy-library/import-backtest", dependencies=[Depends(require_mutation_security)],
    response_model=StrategyLibraryEntryResponse, response_model_exclude_unset=True,
)
def import_backtest(request: BacktestImport, settings: SettingsDep) -> dict[str, Any]:
    return _call(service.import_backtest, settings, request.run_id, title=request.title)


def _validate(settings, strategy_id, digest):
    global _ACTIVE
    try:
        validate_in_research_runtime(settings, strategy_id, digest)
    finally:
        _ACTIVE = None
        _LOCK.release()


@router.post(
    "/strategy-library/{strategy_id}/validate",
    status_code=202,
    response_model=StrategyLibraryEntryResponse,
    response_model_exclude_unset=True,
    dependencies=[Depends(require_mutation_security)],
)
def validate_strategy(
    strategy_id: str, request: StrategyAction, settings: SettingsDep, tasks: BackgroundTasks
) -> dict[str, Any]:
    global _ACTIVE
    result = _call(service.read_strategy, settings, strategy_id)
    if result["definition_digest"] != request.expected_digest or result["status"] == "stale":
        raise HTTPException(409, detail="strategy_definition_changed")
    if not _LOCK.acquire(blocking=False):
        if strategy_id != _ACTIVE:
            raise HTTPException(409, detail="另一项策略验证正在进行，请完成后再启动。")
        return {**result, "status": "validating"}
    _ACTIVE = strategy_id
    tasks.add_task(_validate, settings, strategy_id, request.expected_digest)
    return {**result, "status": "validating"}


@router.post(
    "/strategy-library/{strategy_id}/enable", dependencies=[Depends(require_mutation_security)],
    response_model=StrategyLibraryEntryResponse, response_model_exclude_unset=True,
)
def enable_strategy(
    strategy_id: str, request: StrategyAction, settings: SettingsDep
) -> dict[str, Any]:
    if strategy_id == _ACTIVE:
        raise HTTPException(409, detail="strategy_validation_in_progress")
    return _call(service.enable_strategy, settings, strategy_id, request.expected_digest)
