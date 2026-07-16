from __future__ import annotations

import json

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

_MAX_CANDIDATE_SOURCE_PREVIEW_CHARS = 65_536
_MAX_CANDIDATE_METADATA_RESPONSE_BYTES = 65_536


def _bounded_source_preview(payload: bytes) -> tuple[str, bool]:
    text = payload.decode("utf-8", errors="replace")
    if len(text) <= _MAX_CANDIDATE_SOURCE_PREVIEW_CHARS:
        return text, False
    return text[:_MAX_CANDIDATE_SOURCE_PREVIEW_CHARS], True


def _bounded_candidate_metadata(metadata: dict) -> tuple[dict | None, bool]:
    try:
        payload = json.dumps(
            metadata,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        return None, True
    if len(payload) > _MAX_CANDIDATE_METADATA_RESPONSE_BYTES:
        return None, True
    return metadata, False


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
        candidates = [
            item.model_dump(mode="json")
            for item in CandidatePool(agent_output_dir).list_for_read(max_entries=200)
        ]
    except (CandidateIntegrityError, OSError) as exc:
        raise _candidate_repository_unavailable() from exc
    if status is not None:
        candidates = [candidate for candidate in candidates if candidate.get("status") == status]
    return {"candidates": candidates}


@router.get("/agent/candidates/{candidate_id}", response_model=AgentCandidateDetailResponse)
def candidate_detail(candidate_id: str, agent_output_dir: AgentOutputDirDep) -> dict:
    try:
        _validate_candidate_id(candidate_id)
    except CandidateIntegrityError as exc:
        raise not_found_404("agent_candidate", candidate_id) from exc

    pool = CandidatePool(agent_output_dir)
    try:
        item = pool.read_for_read(candidate_id)
    except (CandidateIntegrityError, OSError) as exc:
        raise _candidate_repository_unavailable() from exc
    if item is None:
        raise not_found_404("agent_candidate", candidate_id)

    # Only exact digest-bound candidate controls are evidence here. Global
    # substring-matched audit logs and legacy reviews.jsonl are intentionally
    # excluded: neither is bound to this candidate manifest and both used to
    # create an unsafe, unbounded filesystem read surface.
    audits: list[str] = []

    if item.integrity_state == "corrupt":
        return {
            "candidate_id": candidate_id,
            "metadata": None,
            "source_preview": None,
            "audit": audits,
            "reviews": [],
            "evidence_truncated": False,
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
        preview_truncated = False
        if source_preview is not None and len(source_preview) > _MAX_CANDIDATE_SOURCE_PREVIEW_CHARS:
            source_preview = source_preview[:_MAX_CANDIDATE_SOURCE_PREVIEW_CHARS]
            preview_truncated = True
        return {
            "candidate_id": candidate_id,
            "metadata": None,
            "source_preview": source_preview,
            "audit": audits,
            "reviews": [],
            "evidence_truncated": preview_truncated,
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
            "evidence_truncated": False,
            "integrity_state": "corrupt",
            "manifest_digest": None,
            "observed_manifest_digest": None,
            "approval_binding": None,
            "approval_enabled": False,
            "integrity_error_code": "corrupt",
            "status": None,
        }

    source_preview = ""
    preview_truncated = False
    if snapshot.manifest.files:
        first = snapshot.manifest.files[0].path
        payload = snapshot.artifact_bytes.get(first, b"")
        source_preview, preview_truncated = _bounded_source_preview(payload)
    metadata, metadata_truncated = _bounded_candidate_metadata(snapshot.metadata)
    reviews = []
    if snapshot.review_record is not None:
        reviews = [snapshot.review_record.model_dump_json()]

    return {
        "candidate_id": snapshot.candidate_id,
        "metadata": metadata,
        "source_preview": source_preview,
        "audit": audits,
        "reviews": reviews,
        "evidence_truncated": preview_truncated or metadata_truncated,
        "integrity_state": "verified",
        "manifest_digest": snapshot.manifest_digest,
        "observed_manifest_digest": None,
        "approval_binding": snapshot.approval_binding,
        "approval_enabled": snapshot.approval_binding == "pending",
        "integrity_error_code": None,
        "status": item.status,
    }


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
        raise _candidate_conflict(candidate_id, "candidate_review_state_stale") from exc
    except CandidateMigrationRequiredError as exc:
        raise _candidate_conflict(candidate_id, "candidate_migration_required") from exc
    except CandidateIntegrityError as exc:
        # Missing candidates surface as 404; corrupt/integrity CAS as 409.
        message = str(exc).lower()
        if "does not exist" in message or "not a directory" in message:
            raise not_found_404("agent_candidate", candidate_id) from exc
        raise _candidate_conflict(candidate_id, "candidate_integrity_failed") from exc
    except CandidateStaleError as exc:
        raise _candidate_conflict(candidate_id, "candidate_revision_stale") from exc
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
