from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Query, Request, status

from quant_system.api.dependencies import (
    OwnerSessionDep,
    SettingsDep,
    consume_owner_mutation_budget,
    require_mutation_security,
)
from quant_system.api.safety.mutation_rate_limit import D34_MANDATE_ROUTE
from quant_system.api.schemas.d34 import (
    D34ExperimentJobListResponse,
    D34MandateCreateRequest,
    D34MandateListResponse,
    D34MandateResponse,
    D34MandateTransitionRequest,
)
from quant_system.hermes.d34_job_authority import (
    JOB_STATES,
    ExperimentJob,
    JobAuthorityError,
    JobAuthorityPort,
    PostgresJobAuthority,
)
from quant_system.hermes.d34_mandate_authority import (
    CreateMandateCommand,
    Mandate,
    MandateAuthorityError,
    MandateAuthorityPort,
    PostgresMandateAuthority,
)

router = APIRouter()


def _authority(request: Request, settings: SettingsDep) -> MandateAuthorityPort:
    services = getattr(request.app.state, "services", None)
    injected = services.get("d34_mandate_authority") if isinstance(services, dict) else None
    if injected is not None:
        return injected
    return PostgresMandateAuthority(settings)


def _public(value: Mandate | dict[str, object]) -> dict[str, object]:
    return value.to_public_dict() if isinstance(value, Mandate) else value


def _job_authority(request: Request, settings: SettingsDep) -> JobAuthorityPort:
    services = getattr(request.app.state, "services", None)
    injected = services.get("d34_job_authority") if isinstance(services, dict) else None
    if injected is not None:
        return injected
    return PostgresJobAuthority(settings)


def _job_public(value: ExperimentJob | dict[str, object]) -> dict[str, object]:
    return value.to_public_dict() if isinstance(value, ExperimentJob) else value


def _http_error(exc: MandateAuthorityError) -> HTTPException:
    status_code = {
        "d34_mandate_conflict": 409,
        "d34_mandate_forbidden": 403,
        "d34_mandate_not_found": 404,
        "d34_mandate_validation": 422,
        "d34_mandate_unavailable": 503,
    }.get(exc.code, 503)
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )


@router.post(
    "/hermes/mandates",
    response_model=D34MandateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_mandate(
    body: D34MandateCreateRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    owner = require_mutation_security(request)
    consume_owner_mutation_budget(
        request,
        owner_user_id=owner.owner_user_id,
        route=D34_MANDATE_ROUTE,
    )
    try:
        command = CreateMandateCommand(
            owner_user_id=owner.owner_user_id,
            workspace_id=body.workspace_id,
            duration_days=body.duration_days,
            universe=tuple(body.universe),
            hypotheses_per_cycle=body.hypotheses_per_cycle,
            max_iterations=body.max_iterations,
            max_experiments_per_iteration=body.max_experiments_per_iteration,
            max_concurrent_jobs=body.max_concurrent_jobs,
            llm_budget_usd=Decimal(body.llm_budget_usd),
            llm_warning_fraction=Decimal(body.llm_warning_fraction),
            paper_execution_allowed=body.paper_execution_allowed,
        )
        return _public(_authority(request, settings).create(command))
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "d34_mandate_validation", "message": "mandate is invalid"},
        ) from exc
    except MandateAuthorityError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/hermes/mandates/active",
    response_model=D34MandateResponse,
)
def active_mandate(
    request: Request,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    workspace_id: str = Query(default="default", min_length=1, max_length=128),
) -> dict[str, object]:
    _ = owner
    try:
        mandate = _authority(request, settings).get_active(workspace_id=workspace_id)
    except MandateAuthorityError as exc:
        raise _http_error(exc) from exc
    if mandate is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "d34_mandate_not_found", "message": "active mandate not found"},
        )
    return _public(mandate)


@router.get(
    "/hermes/mandates",
    response_model=D34MandateListResponse,
)
def list_mandates(
    request: Request,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    workspace_id: str = Query(default="default", min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    _ = owner
    try:
        items = _authority(request, settings).list(
            workspace_id=workspace_id,
            limit=limit,
        )
    except MandateAuthorityError as exc:
        raise _http_error(exc) from exc
    return {"contract": "hqa.mandate-list/v1", "items": [_public(item) for item in items]}


def _transition(
    *,
    mandate_id: str,
    action: str,
    body: D34MandateTransitionRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    owner = require_mutation_security(request)
    consume_owner_mutation_budget(
        request,
        owner_user_id=owner.owner_user_id,
        route=D34_MANDATE_ROUTE,
    )
    try:
        return _public(
            _authority(request, settings).transition(
                mandate_id=mandate_id,
                action=action,
                expected_version=body.expected_version,
                reason=body.reason,
            )
        )
    except MandateAuthorityError as exc:
        raise _http_error(exc) from exc


@router.post("/hermes/mandates/{mandate_id}/pause", response_model=D34MandateResponse)
def pause_mandate(
    mandate_id: str,
    body: D34MandateTransitionRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    return _transition(
        mandate_id=mandate_id,
        action="pause",
        body=body,
        request=request,
        settings=settings,
    )


@router.post("/hermes/mandates/{mandate_id}/resume", response_model=D34MandateResponse)
def resume_mandate(
    mandate_id: str,
    body: D34MandateTransitionRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    return _transition(
        mandate_id=mandate_id,
        action="resume",
        body=body,
        request=request,
        settings=settings,
    )


@router.post("/hermes/mandates/{mandate_id}/revoke", response_model=D34MandateResponse)
def revoke_mandate(
    mandate_id: str,
    body: D34MandateTransitionRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    return _transition(
        mandate_id=mandate_id,
        action="revoke",
        body=body,
        request=request,
        settings=settings,
    )


@router.get(
    "/hermes/research/jobs",
    response_model=D34ExperimentJobListResponse,
)
def list_research_jobs(
    request: Request,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    workspace_id: str = Query(default="default", min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
    state: str | None = Query(default=None),
) -> dict[str, object]:
    _ = owner
    if state is not None and state not in JOB_STATES:
        raise HTTPException(
            status_code=422,
            detail={"code": "d34_job_validation", "message": "research job state is invalid"},
        )
    try:
        items = _job_authority(request, settings).list(
            workspace_id=workspace_id,
            limit=limit,
            state=state,
        )
    except JobAuthorityError as exc:
        raise HTTPException(
            status_code=422 if exc.code == "d34_job_validation" else 503,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return {
        "contract": "hqa.d34_experiment_job-list/v1",
        "items": [_job_public(item) for item in items],
    }
