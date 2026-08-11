from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException, Query, Request, status

from quant_system.api.dependencies import (
    ApiRunsDirDep,
    OwnerSessionDep,
    SettingsDep,
    consume_owner_mutation_budget,
    require_mutation_security,
)
from quant_system.api.safety.mutation_rate_limit import D34_MANDATE_ROUTE
from quant_system.api.schemas.d34 import (
    D34ArtifactListResponse,
    D34CanaryListResponse,
    D34CanaryResponse,
    D34CanaryTransitionRequest,
    D34ExperimentJobListResponse,
    D34MandateCreateRequest,
    D34MandateListResponse,
    D34MandateRenewRequest,
    D34MandateResponse,
    D34MandateTransitionRequest,
    D34RollbackRequest,
    D34RollbackResponse,
)
from quant_system.execution.d34_canary_control import (
    D34CanaryControlError,
    D34CanaryController,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
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
from quant_system.hermes.d34_registry_authority import (
    D34Artifact,
    D34Canary,
    PostgresRegistryAuthority,
    RegistryAuthorityError,
    RegistryAuthorityPort,
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


def _registry_authority(request: Request, settings: SettingsDep) -> RegistryAuthorityPort:
    services = getattr(request.app.state, "services", None)
    injected = services.get("d34_registry_authority") if isinstance(services, dict) else None
    if injected is not None:
        return injected
    return PostgresRegistryAuthority(settings)


def _registry_public(
    value: D34Artifact | D34Canary | dict[str, object],
) -> dict[str, object]:
    if isinstance(value, (D34Artifact, D34Canary)):
        return value.to_public_dict()
    return value


def _canary_controller(
    request: Request,
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
) -> D34CanaryController:
    services = getattr(request.app.state, "services", None)
    injected = services.get("d34_canary_controller") if isinstance(services, dict) else None
    if injected is not None:
        return injected
    return D34CanaryController(
        registry=_registry_authority(request, settings),
        sleeve_storage=PaperStrategySleeveStorage(api_runs_dir),
    )


def _canary_http_error(exc: Exception) -> HTTPException:
    code = str(getattr(exc, "code", "d34_canary_control_unavailable"))
    status_code = (
        404
        if code in {"d34_registry_not_found", "d34_canary_sleeve_missing"}
        else 409
        if code in {
            "d34_registry_conflict",
            "d34_canary_control_conflict",
            "d34_canary_sleeve_conflict",
            "d34_canary_lineage_invalid",
        }
        else 422
        if code in {"d34_registry_validation", "d34_canary_control_validation"}
        else 503
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(getattr(exc, "message", code))},
    )


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


def _job_http_error(exc: JobAuthorityError) -> HTTPException:
    status_code = {
        "d34_job_conflict": 409,
        "d34_job_validation": 422,
        "d34_job_unavailable": 503,
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


@router.post("/hermes/mandates/{mandate_id}/renew", response_model=D34MandateResponse)
def renew_mandate(
    mandate_id: str,
    body: D34MandateRenewRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    owner = require_mutation_security(request)
    consume_owner_mutation_budget(
        request, owner_user_id=owner.owner_user_id, route=D34_MANDATE_ROUTE
    )
    try:
        return _public(
            _authority(request, settings).renew(
                mandate_id=mandate_id,
                duration_days=body.duration_days,
                expected_version=body.expected_version,
                reason=body.reason,
            )
        )
    except MandateAuthorityError as exc:
        raise _http_error(exc) from exc


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
        raise _job_http_error(exc) from exc
    return {
        "contract": "hqa.d34_experiment_job-list/v1",
        "items": [_job_public(item) for item in items],
    }


@router.get("/hermes/d34/artifacts", response_model=D34ArtifactListResponse)
def list_d34_artifacts(
    request: Request,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    workspace_id: str = Query(default="default", min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    _ = owner
    try:
        items = _registry_authority(request, settings).list_artifacts(
            workspace_id=workspace_id, limit=limit
        )
    except RegistryAuthorityError as exc:
        raise HTTPException(
            status_code=422 if exc.code == "d34_registry_validation" else 503,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return {
        "contract": "hqa.d34_artifact-list/v1",
        "items": [_registry_public(item) for item in items],
    }


@router.get("/hermes/canaries", response_model=D34CanaryListResponse)
def list_d34_canaries(
    request: Request,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    workspace_id: str = Query(default="default", min_length=1, max_length=128),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    _ = owner
    try:
        items = _registry_authority(request, settings).list_canaries(
            workspace_id=workspace_id, limit=limit
        )
    except RegistryAuthorityError as exc:
        raise HTTPException(
            status_code=422 if exc.code == "d34_registry_validation" else 503,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return {
        "contract": "hqa.d34_canary-list/v1",
        "items": [_registry_public(item) for item in items],
    }


def _control_canary(
    *,
    canary_id: str,
    action: str,
    body: D34CanaryTransitionRequest,
    request: Request,
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
) -> dict[str, object]:
    owner = require_mutation_security(request)
    consume_owner_mutation_budget(
        request, owner_user_id=owner.owner_user_id, route=D34_MANDATE_ROUTE
    )
    try:
        return _registry_public(
            _canary_controller(request, settings, api_runs_dir).transition(
                canary_id=canary_id,
                action=action,
                expected_version=body.expected_version,
                reason=body.reason,
            )
        )
    except (D34CanaryControlError, RegistryAuthorityError) as exc:
        raise _canary_http_error(exc) from exc


@router.post("/hermes/canaries/{canary_id}/pause", response_model=D34CanaryResponse)
def pause_d34_canary(
    canary_id: str,
    body: D34CanaryTransitionRequest,
    request: Request,
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
) -> dict[str, object]:
    return _control_canary(
        canary_id=canary_id,
        action="pause",
        body=body,
        request=request,
        settings=settings,
        api_runs_dir=api_runs_dir,
    )


@router.post("/hermes/canaries/{canary_id}/demote", response_model=D34CanaryResponse)
def demote_d34_canary(
    canary_id: str,
    body: D34CanaryTransitionRequest,
    request: Request,
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
) -> dict[str, object]:
    return _control_canary(
        canary_id=canary_id,
        action="demote",
        body=body,
        request=request,
        settings=settings,
        api_runs_dir=api_runs_dir,
    )


@router.post("/hermes/d34/rollback", response_model=D34RollbackResponse)
def rollback_d34(
    body: D34RollbackRequest,
    request: Request,
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
) -> dict[str, object]:
    owner = require_mutation_security(request)
    consume_owner_mutation_budget(
        request, owner_user_id=owner.owner_user_id, route=D34_MANDATE_ROUTE
    )
    mandate_id: str | None = None
    mandate_status: str | None = None
    try:
        mandates = _authority(request, settings)
        active = mandates.get_active(workspace_id=body.workspace_id)
        if active is not None:
            active_public = _public(active)
            mandate_id = str(active_public["mandate_id"])
            if active_public["status"] == "active":
                active = mandates.transition(
                    mandate_id=mandate_id,
                    action="pause",
                    expected_version=int(active_public["version"]),
                    reason=body.reason,
                )
                active_public = _public(active)
            mandate_status = str(active_public["status"])
        jobs_cancelled = _job_authority(request, settings).cancel_queued(
            workspace_id=body.workspace_id,
            reason=body.reason,
        )
        result = _canary_controller(request, settings, api_runs_dir).rollback_all(
            workspace_id=body.workspace_id, reason=body.reason
        )
    except MandateAuthorityError as exc:
        raise _http_error(exc) from exc
    except JobAuthorityError as exc:
        raise _job_http_error(exc) from exc
    except (D34CanaryControlError, RegistryAuthorityError) as exc:
        raise _canary_http_error(exc) from exc
    return {
        "contract": "hqa.d34_rollback/v1",
        "mandate_id": mandate_id,
        "mandate_status": mandate_status,
        "jobs_cancelled": jobs_cancelled,
        **result,
    }
