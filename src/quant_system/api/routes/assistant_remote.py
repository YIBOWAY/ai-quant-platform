from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from quant_system.api.dependencies import SettingsDep, require_mutation_security
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    hang_candidate,
    intake_research_operation,
    project_book,
    project_research_evidence,
    project_research_request,
)
from quant_system.hermes.d34_job_authority import (
    JobAuthorityError,
    PostgresJobAuthority,
)

router = APIRouter()

_WORKSPACE_ID = "default"


def _job_authority(request: Request, settings: SettingsDep):
    services = getattr(request.app.state, "services", None)
    injected = services.get("d34_job_authority") if isinstance(services, dict) else None
    return injected if injected is not None else PostgresJobAuthority(settings)


class RemoteHangRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=128)
    expected_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class RemoteResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    material_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    command_id: str = Field(min_length=1, max_length=255)
    platform_session_id: str = Field(min_length=1, max_length=255)
    hermes_session_id: str = Field(min_length=1, max_length=255)
    hermes_run_id: str = Field(min_length=1, max_length=255)
    note: str = Field(min_length=8, max_length=8000)
    formula: str = Field(min_length=1, max_length=4000)
    universe: list[str] = Field(min_length=1)


class RemoteBookResponse(BaseModel):
    contract: str
    candidates: list[dict[str, object]] = Field(default_factory=list)
    requests: list[dict[str, object]] = Field(default_factory=list)
    verified_count: int = 0
    hung_count: int = 0
    fossil_count: int = 0
    fossils: list[dict[str, object]] = Field(default_factory=list)


class RemoteHangResponse(BaseModel):
    contract: str
    status: str
    candidate_id: str
    sleeve_id: str | None = None
    source_digest: str
    factor_id: str
    universe: list[str]
    dsr: dict[str, object] | None = None
    max_hung_correlation: float | None = None
    already_hung: bool = False


class RemoteResearchResponse(BaseModel):
    contract: str
    operation_id: str
    material_digest: str
    request_id: str
    job_id: str
    job_key: str
    status: str
    terminal: bool
    outcome: str
    result_reply: dict[str, object]
    command_id: str
    platform_session_id: str
    hermes_session_id: str
    hermes_run_id: str
    candidate_id: str | None = None
    source_digest: str | None = None
    evidence: dict[str, object] | None = None


class RemoteResearchEvidenceResponse(BaseModel):
    contract: str
    operation_id: str
    material_digest: str
    status: str
    outcome: str
    candidate_id: str | None = None
    source_digest: str | None = None
    evidence: dict[str, object]


def _http_error(exc: AssistantRemoteError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": exc.code, "message": exc.code})


def _hang_http_error(exc: AssistantRemoteError) -> HTTPException:
    if exc.code in {
        "hang_account_outcome_unknown",
        "hang_book_persist_failed",
        "hang_recovery_sleeve_outcome_unknown",
        "hang_sleeve_persist_failed",
        "hang_sleeve_pending",
        "hang_sleeve_activation_failed",
    }:
        return HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": "Hang outcome is unknown; refresh the book before any retry.",
                "outcome": "outcome_unknown",
                "retryable": False,
                "recovery_action": "refresh_remote_book",
            },
        )
    return _http_error(exc)


@router.get("/assistant/remote/book", response_model=RemoteBookResponse)
def get_remote_book(request: Request, settings: SettingsDep) -> dict[str, object]:
    del request
    try:
        return project_book(settings)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "remote_book_unavailable",
                "message": "Remote research book is unavailable.",
            },
        ) from exc


@router.post("/assistant/remote/hang", response_model=RemoteHangResponse)
def post_remote_hang(
    body: RemoteHangRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    require_mutation_security(request)
    try:
        return hang_candidate(
            settings,
            candidate_id=body.candidate_id,
            expected_source_digest=body.expected_source_digest,
        )
    except AssistantRemoteError as exc:
        raise _hang_http_error(exc) from exc


@router.post(
    "/assistant/remote/research",
    response_model=RemoteResearchResponse,
    response_model_exclude_none=True,
)
def post_remote_research(
    body: RemoteResearchRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    require_mutation_security(request)
    try:
        return intake_research_operation(
            settings,
            jobs=_job_authority(request, settings),
            operation_id=body.operation_id,
            material_digest=body.material_digest,
            command_id=body.command_id,
            platform_session_id=body.platform_session_id,
            hermes_session_id=body.hermes_session_id,
            hermes_run_id=body.hermes_run_id,
            note=body.note,
            formula=body.formula,
            universe=body.universe,
            workspace_id=_WORKSPACE_ID,
        )
    except AssistantRemoteError as exc:
        raise _http_error(exc) from exc
    except (JobAuthorityError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "research_job_enqueue_failed", "message": str(exc)},
        ) from exc


@router.get(
    "/assistant/remote/request/{operation_id}",
    response_model=RemoteResearchResponse,
    response_model_exclude_none=True,
)
def get_remote_research_request(
    operation_id: str,
    settings: SettingsDep,
) -> dict[str, object]:
    try:
        projection = project_research_request(
            settings,
            operation_id=operation_id,
        )
    except AssistantRemoteError as exc:
        raise _http_error(exc) from exc
    if projection is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "research_operation_not_found",
                "message": "research_operation_not_found",
            },
        )
    return projection


@router.get(
    "/assistant/remote/evidence/{operation_id}/{manifest_digest}",
    response_model=RemoteResearchEvidenceResponse,
)
def get_remote_research_evidence(
    operation_id: str,
    manifest_digest: str,
    settings: SettingsDep,
) -> dict[str, object]:
    try:
        projection = project_research_evidence(
            settings,
            operation_id=operation_id,
            manifest_digest=manifest_digest,
        )
    except AssistantRemoteError as exc:
        raise _http_error(exc) from exc
    if projection is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "research_evidence_not_found",
                "message": "research_evidence_not_found",
            },
        )
    return projection
