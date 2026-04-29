from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from quant_system.agent.llm import build_llm_client
from quant_system.agent.runner import AgentRunner
from quant_system.api.dependencies import OutputDirDep, SettingsDep
from quant_system.api.schemas.agent import AgentReviewRequest, AgentTaskRequest
from quant_system.api.schemas.common import resolve_run_dir

router = APIRouter()


@router.get("/agent/candidates")
def list_candidates(
    output_dir: OutputDirDep,
    status: str | None = None,
) -> dict:
    candidates = AgentRunner(output_dir=output_dir).list_candidates()
    if status is not None:
        candidates = [candidate for candidate in candidates if candidate.get("status") == status]
    return {"candidates": candidates}


@router.get("/agent/candidates/{candidate_id}")
def candidate_detail(candidate_id: str, output_dir: OutputDirDep) -> dict:
    candidate_dir = resolve_run_dir(output_dir / "agent" / "candidates", candidate_id)
    metadata_path = candidate_dir / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail=f"candidate {candidate_id!r} not found")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    files = metadata.get("files", [])
    source_preview = ""
    if files:
        source_path = candidate_dir / str(files[0])
        if source_path.exists() and source_path.is_file():
            source_preview = source_path.read_text(encoding="utf-8")
    audits = []
    audit_dir = output_dir / "agent" / "audit"
    if audit_dir.exists():
        for path in sorted(audit_dir.glob("*.jsonl")):
            audits.extend(
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if candidate_id in line
            )
    reviews_path = candidate_dir / "reviews.jsonl"
    reviews = reviews_path.read_text(encoding="utf-8").splitlines() if reviews_path.exists() else []
    return {
        "candidate_id": candidate_id,
        "metadata": metadata,
        "source_preview": source_preview,
        "audit": audits,
        "reviews": reviews,
    }


@router.post("/agent/tasks")
def run_agent_task(
    request: AgentTaskRequest,
    output_dir: OutputDirDep,
    settings: SettingsDep,
) -> dict:
    try:
        llm = build_llm_client(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runner = AgentRunner(output_dir=output_dir, llm=llm)
    if request.task_type == "propose-factor":
        artifact = runner.propose_factor(goal=request.goal, universe=request.universe)
    elif request.task_type == "propose-experiment":
        artifact = runner.propose_experiment(goal=request.goal, universe=request.universe)
    elif request.task_type == "summarize":
        if not request.experiment_id:
            raise HTTPException(status_code=422, detail="experiment_id is required")
        artifact = runner.summarize(experiment_id=request.experiment_id)
    elif request.task_type == "audit-leakage":
        if not request.factor_id:
            raise HTTPException(status_code=422, detail="factor_id is required")
        artifact = runner.audit_leakage(factor_id=request.factor_id)
    else:
        raise HTTPException(status_code=422, detail="unknown agent task type")

    metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    return {
        "candidate_id": artifact.candidate_id,
        "status": artifact.status.value,
        "path": str(artifact.path),
        "metadata": metadata,
    }


@router.post("/agent/candidates/{candidate_id}/review")
def review_candidate(
    candidate_id: str,
    request: AgentReviewRequest,
    output_dir: OutputDirDep,
) -> dict:
    try:
        record = AgentRunner(output_dir=output_dir).review(
            candidate_id=candidate_id,
            decision=request.decision,
            note=request.note,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "candidate_id": record.candidate_id,
        "decision": record.decision,
        "registration": "manual_required",
    }


@router.get("/agent/llm-config")
def llm_config(settings: SettingsDep) -> dict:
    return {
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "base_url": settings.llm.base_url,
        "timeout": settings.llm.timeout,
        "has_api_key": settings.llm.api_key is not None,
    }
