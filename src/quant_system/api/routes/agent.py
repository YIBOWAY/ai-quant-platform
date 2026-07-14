from __future__ import annotations

import json
from contextlib import suppress

from fastapi import APIRouter, HTTPException

from quant_system.agent.candidate_manifest import (
    CandidateIntegrityError,
    CandidateMigrationRequiredError,
    CandidateReviewStateStaleError,
    CandidateStaleError,
    _validate_candidate_id,
)
from quant_system.agent.candidate_pool import CandidateConflictError, CandidatePool
from quant_system.agent.llm import build_llm_client
from quant_system.agent.runner import AgentRunner
from quant_system.api.dependencies import AgentOutputDirDep, OutputDirDep, SettingsDep
from quant_system.api.errors import not_found_404
from quant_system.api.schemas.agent import (
    AgentCandidateDetailResponse,
    AgentCandidatesResponse,
    AgentLLMConfigResponse,
    AgentReviewRequest,
    AgentReviewResponse,
    AgentTaskRequest,
    AgentTaskResponse,
)

router = APIRouter()


def _candidate_conflict(candidate_id: str, code: str) -> HTTPException:
    """Always HTTP 409 with stable CAS conflict codes (message-free contract)."""
    return HTTPException(
        status_code=409,
        detail={
            "code": code,
            "resource": "agent_candidate",
            "id": candidate_id,
        },
    )


def _candidate_repository_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "candidate_repository_unavailable",
            "resource": "agent_candidates",
        },
    )


@router.get("/agent/candidates", response_model=AgentCandidatesResponse)
def list_candidates(
    agent_output_dir: AgentOutputDirDep,
    status: str | None = None,
) -> dict:
    try:
        candidates = AgentRunner(agent_output_dir=agent_output_dir).list_candidates()
    except (CandidateIntegrityError, OSError) as exc:
        raise _candidate_repository_unavailable() from exc
    if status is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get("status") == status
        ]
    return {"candidates": candidates}


@router.get("/agent/candidates/{candidate_id}", response_model=AgentCandidateDetailResponse)
def candidate_detail(candidate_id: str, agent_output_dir: AgentOutputDirDep) -> dict:
    try:
        _validate_candidate_id(candidate_id)
    except CandidateIntegrityError as exc:
        raise not_found_404("agent_candidate", candidate_id) from exc

    pool = CandidatePool(agent_output_dir)
    try:
        items = {item.candidate_id: item for item in pool.list_for_read()}
    except (CandidateIntegrityError, OSError) as exc:
        raise _candidate_repository_unavailable() from exc
    item = items.get(candidate_id)
    if item is None:
        # Try get for verified path; list may have raced empty root.
        try:
            snapshot = pool.get(candidate_id)
        except (CandidateIntegrityError, CandidateMigrationRequiredError, OSError) as exc:
            raise not_found_404("agent_candidate", candidate_id) from exc
        item = None
        # Build detail from verified snapshot.
        source_preview = ""
        if snapshot.manifest.files:
            first = snapshot.manifest.files[0].path
            payload = snapshot.artifact_bytes.get(first, b"")
            source_preview = payload.decode("utf-8", errors="replace")
        reviews: list[str] = []
        if snapshot.review_record is not None:
            reviews = [snapshot.review_record.model_dump_json()]
        audits = _audit_lines(agent_output_dir, candidate_id)
        return {
            "candidate_id": snapshot.candidate_id,
            "metadata": snapshot.metadata,
            "source_preview": source_preview,
            "audit": audits,
            "reviews": reviews,
            "integrity_state": "verified",
            "manifest_digest": snapshot.manifest_digest,
            "observed_manifest_digest": None,
            "approval_binding": snapshot.approval_binding,
            "approval_enabled": snapshot.approval_binding == "pending",
            "integrity_error_code": None,
            "status": (
                snapshot.approval_binding
                if snapshot.approval_binding in {"pending", "approved", "rejected"}
                else None
            ),
        }

    audits = _audit_lines(agent_output_dir, candidate_id)

    if item.integrity_state == "corrupt":
        return {
            "candidate_id": candidate_id,
            "metadata": None,
            "source_preview": None,
            "audit": audits,
            "reviews": [],
            "integrity_state": "corrupt",
            "manifest_digest": None,
            "observed_manifest_digest": None,
            "approval_binding": None,
            "approval_enabled": False,
            "integrity_error_code": item.integrity_error_code,
            "status": None,
        }

    if item.integrity_state == "migration_required":
        # Migration preview uses the same no-symlink exact-byte reader that
        # produces observed_manifest_digest; it is diagnostic only.
        source_preview = _migration_source_preview(pool, candidate_id)
        return {
            "candidate_id": candidate_id,
            "metadata": None,
            "source_preview": source_preview,
            "audit": audits,
            "reviews": [],
            "integrity_state": "migration_required",
            "manifest_digest": None,
            "observed_manifest_digest": item.observed_manifest_digest,
            "approval_binding": item.approval_binding,
            "approval_enabled": False,
            "integrity_error_code": None,
            "status": item.status,
        }

    # verified
    try:
        snapshot = pool.get(candidate_id)
    except CandidateIntegrityError:
        return {
            "candidate_id": candidate_id,
            "metadata": None,
            "source_preview": None,
            "audit": audits,
            "reviews": [],
            "integrity_state": "corrupt",
            "manifest_digest": None,
            "observed_manifest_digest": None,
            "approval_binding": None,
            "approval_enabled": False,
            "integrity_error_code": "corrupt",
            "status": None,
        }

    source_preview = ""
    if snapshot.manifest.files:
        first = snapshot.manifest.files[0].path
        payload = snapshot.artifact_bytes.get(first, b"")
        source_preview = payload.decode("utf-8", errors="replace")
    reviews = []
    if snapshot.review_record is not None:
        reviews = [snapshot.review_record.model_dump_json()]
    # Merge historical legacy reviews.jsonl for display only (never authoritative).
    legacy_reviews = snapshot.candidate_dir / "reviews.jsonl"
    if legacy_reviews.exists() and legacy_reviews.is_file():
        with suppress(OSError):
            reviews = reviews + [
                line
                for line in legacy_reviews.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    return {
        "candidate_id": snapshot.candidate_id,
        "metadata": snapshot.metadata,
        "source_preview": source_preview,
        "audit": audits,
        "reviews": reviews,
        "integrity_state": "verified",
        "manifest_digest": snapshot.manifest_digest,
        "observed_manifest_digest": None,
        "approval_binding": snapshot.approval_binding,
        "approval_enabled": snapshot.approval_binding == "pending",
        "integrity_error_code": None,
        "status": item.status,
    }


def _audit_lines(agent_output_dir, candidate_id: str) -> list[str]:
    audits: list[str] = []
    audit_dir = agent_output_dir / "agent" / "audit"
    if audit_dir.exists():
        for path in sorted(audit_dir.glob("*.jsonl")):
            audits.extend(
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if candidate_id in line
            )
    return audits


def _migration_source_preview(pool: CandidatePool, candidate_id: str) -> str | None:
    """Exact-byte first-artifact preview for migration_required items only."""
    from quant_system.agent.candidate_manifest import (
        CandidateIntegrityError as _CIE,
    )
    from quant_system.agent.candidate_manifest import (
        build_candidate_manifest,
    )

    try:
        _manifest, _digest, artifact_bytes = build_candidate_manifest(
            pool.candidates_dir / candidate_id
        )
    except (CandidateIntegrityError, OSError, _CIE):
        return None
    if not artifact_bytes:
        return None
    first = next(iter(artifact_bytes))
    return artifact_bytes[first].decode("utf-8", errors="replace")


@router.post("/agent/tasks", response_model=AgentTaskResponse)
def run_agent_task(
    request: AgentTaskRequest,
    output_dir: OutputDirDep,
    agent_output_dir: AgentOutputDirDep,
    settings: SettingsDep,
) -> dict:
    try:
        llm = build_llm_client(settings)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runner = AgentRunner(
        agent_output_dir=agent_output_dir,
        result_output_dir=output_dir,
        llm=llm,
    )
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
        "manifest_digest": artifact.manifest_digest,
    }


@router.post(
    "/agent/candidates/{candidate_id}/review",
    response_model=AgentReviewResponse,
)
def review_candidate(
    candidate_id: str,
    request: AgentReviewRequest,
    agent_output_dir: AgentOutputDirDep,
) -> dict:
    try:
        _validate_candidate_id(candidate_id)
    except CandidateIntegrityError as exc:
        raise not_found_404("agent_candidate", candidate_id) from exc

    try:
        record = AgentRunner(agent_output_dir=agent_output_dir).review(
            candidate_id=candidate_id,
            decision=request.decision,
            note=request.note,
            expected_manifest_digest=request.expected_manifest_digest,
            expected_status=request.expected_status,
        )
    except FileNotFoundError as exc:
        raise not_found_404("agent_candidate", candidate_id) from exc
    # Most-specific first so subclasses never collapse into a coarser code.
    except CandidateReviewStateStaleError as exc:
        raise _candidate_conflict(
            candidate_id, "candidate_review_state_stale"
        ) from exc
    except CandidateMigrationRequiredError as exc:
        raise _candidate_conflict(
            candidate_id, "candidate_migration_required"
        ) from exc
    except CandidateIntegrityError as exc:
        # Missing candidates surface as 404; corrupt/integrity CAS as 409.
        message = str(exc).lower()
        if "does not exist" in message or "not a directory" in message:
            raise not_found_404("agent_candidate", candidate_id) from exc
        raise _candidate_conflict(
            candidate_id, "candidate_integrity_failed"
        ) from exc
    except CandidateStaleError as exc:
        raise _candidate_conflict(
            candidate_id, "candidate_revision_stale"
        ) from exc
    except CandidateConflictError as exc:
        raise _candidate_conflict(candidate_id, "candidate_conflict") from exc
    return {
        "candidate_id": record.candidate_id,
        "decision": record.decision,
        "registration": "manual_required",
        "manifest_digest": record.manifest_digest,
    }


@router.get("/agent/llm-config", response_model=AgentLLMConfigResponse)
def llm_config(settings: SettingsDep) -> dict:
    return {
        "provider": settings.llm.provider,
        "model": settings.llm.model,
        "base_url": settings.llm.base_url,
        "timeout": settings.llm.timeout,
        "has_api_key": settings.llm.api_key is not None,
    }
