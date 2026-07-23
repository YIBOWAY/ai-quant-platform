from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from quant_system.api.dependencies import (
    AgentOutputDirDep,
    ApiRunsDirDep,
    HermesApiReadClientDep,
    HermesLoopbackRequestDep,
    OutputDirDep,
    SettingsDep,
    consume_owner_mutation_budget,
    require_mutation_security,
)
from quant_system.api.safety.mutation_rate_limit import WORKSPACE_ACT_ROUTE
from quant_system.api.schemas.hermes import (
    HermesArtifactFeedResponse,
    HermesGatewayStatusResponse,
    HermesSessionDetailResponse,
    HermesSessionMessagesResponse,
    HermesSessionsResponse,
)
from quant_system.api.schemas.hermes_results import (
    HermesResultDetailResponse,
    HermesResultKind,
    HermesResultSource,
    HermesResultsResponse,
)
from quant_system.api.schemas.workspace import WorkspaceActionReceiptResponse
from quant_system.hermes.agent_workspace_actions import AgentWorkspaceActionError
from quant_system.hermes.artifact_catalog import HermesArtifactCatalog
from quant_system.hermes.composer_readiness import (
    authority_readiness,
    composer_readiness_snapshot,
)
from quant_system.hermes.composer_readiness import (
    chat_write_blockers as _chat_blockers,
)
from quant_system.hermes.external_session_fork import (
    ExternalSessionForkError,
    external_session_fork_context,
    submit_external_session_fork,
)
from quant_system.hermes.gateway_client import (
    HermesApiReadClient,
    HermesApiReadError,
    validate_hermes_session_id,
)
from quant_system.hermes.results_catalog import HermesResultsCatalog
from quant_system.hermes.submission_saga import SubmissionSagaError

router = APIRouter()


class HermesForkToManagedRequest(BaseModel):
    """Closed browser body; authority-bearing source facts remain server-owned."""

    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    fork_point: str = Field(
        min_length=9,
        max_length=256,
        pattern=r"^message:[1-9][0-9]*$",
    )


def _chat_write_ready(settings: SettingsDep) -> bool:
    return bool(authority_readiness(settings)["chat_write_ready"])


def _require_effective_release(settings: SettingsDep) -> None:
    readiness = composer_readiness_snapshot(settings, fresh=True)
    if readiness.get("chat_write_ready") is True:
        return
    raw_blockers = readiness.get("release_blockers")
    blockers = (
        [str(item) for item in raw_blockers]
        if isinstance(raw_blockers, list)
        else ["effective_release_gate_unavailable"]
    )
    raise HTTPException(
        status_code=503,
        detail={
            "code": "agent_v02_release_not_ready",
            "message": "Agent v0.2 durable release admission is closed",
            "blockers": blockers[:64],
            "mutation_enabled": bool(settings.local_mutation.enabled),
        },
    )


@router.get("/hermes/results", response_model=HermesResultsResponse)
def hermes_results(
    api_runs_dir: ApiRunsDirDep,
    output_dir: OutputDirDep,
    agent_output_dir: AgentOutputDirDep,
    settings: SettingsDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    kind: HermesResultKind | None = None,
    status: str | None = Query(default=None, min_length=1, max_length=128),
    source: HermesResultSource | None = None,
    search: str | None = Query(default=None, min_length=1, max_length=256),
) -> dict:
    return HermesResultsCatalog(
        api_runs_dir=api_runs_dir,
        output_dir=output_dir,
        agent_output_dir=agent_output_dir,
        settings=settings,
    ).list(
        limit=limit,
        offset=offset,
        kind=kind,
        status=status,
        source=source,
        search=search,
    )


@router.get(
    "/hermes/results/{kind}/{resource_id}",
    response_model=HermesResultDetailResponse,
)
def hermes_result_detail(
    kind: HermesResultKind,
    resource_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=256,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$",
        ),
    ],
    api_runs_dir: ApiRunsDirDep,
    output_dir: OutputDirDep,
    agent_output_dir: AgentOutputDirDep,
    settings: SettingsDep,
) -> dict:
    return HermesResultsCatalog(
        api_runs_dir=api_runs_dir,
        output_dir=output_dir,
        agent_output_dir=agent_output_dir,
        settings=settings,
    ).detail(
        kind=kind,
        resource_id=resource_id,
    )


@router.get("/hermes/artifacts", response_model=HermesArtifactFeedResponse)
def hermes_artifacts(
    settings: SettingsDep,
    limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    catalog = HermesArtifactCatalog(
        settings.hermes_artifacts.feed_path,
        freshness_budget_seconds=settings.hermes_artifacts.freshness_budget_seconds,
        max_future_clock_skew_seconds=(settings.hermes_artifacts.max_future_clock_skew_seconds),
        max_manifest_bytes=settings.hermes_artifacts.max_manifest_bytes,
    )
    return catalog.latest(limit=limit)


def _warning(exc: HermesApiReadError) -> list[dict[str, str]]:
    return [{"code": exc.code, "message": exc.message}]


def _validated_route_session_id(value: str) -> str:
    try:
        return validate_hermes_session_id(value)
    except HermesApiReadError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


def _require_session_resources(gateway: HermesApiReadClient) -> None:
    capabilities = gateway.capabilities()
    features = capabilities.get("features")
    if not isinstance(features, Mapping) or features.get("session_resources") is not True:
        raise HermesApiReadError(
            "session_resources_unavailable",
            "Hermes API does not advertise persisted session resources",
        )


@router.get("/hermes/gateway", response_model=HermesGatewayStatusResponse)
def hermes_gateway_status(
    settings: SettingsDep,
    gateway: HermesApiReadClientDep,
    _loopback: HermesLoopbackRequestDep,
) -> dict:
    chat_ready = _chat_write_ready(settings)
    if not settings.hermes_gateway.enabled:
        return {
            "read_status": "unavailable",
            "connected": False,
            "model": None,
            "session_api_available": False,
            "chat_write_ready": chat_ready,
            "features": {},
            **_chat_blockers(settings, "integration_disabled"),
            "warnings": [],
        }
    if gateway is None:
        return {
            "read_status": "unavailable",
            "connected": False,
            "model": None,
            "session_api_available": False,
            "chat_write_ready": chat_ready,
            "features": {},
            **_chat_blockers(settings, "gateway_client_unavailable"),
            "warnings": [
                {
                    "code": "gateway_client_unavailable",
                    "message": "Hermes API read client is unavailable",
                }
            ],
        }
    try:
        capabilities = gateway.capabilities()
    except HermesApiReadError as exc:
        return {
            "read_status": "unavailable",
            "connected": False,
            "model": None,
            "session_api_available": False,
            "chat_write_ready": chat_ready,
            "features": {},
            **_chat_blockers(settings, "gateway_unavailable"),
            "warnings": _warning(exc),
        }
    features = capabilities["features"]
    session_api_available = features.get("session_resources") is True
    return {
        "read_status": "available" if session_api_available else "degraded",
        "connected": True,
        "model": capabilities.get("model"),
        "session_api_available": session_api_available,
        "chat_write_ready": chat_ready,
        "features": features,
        **_chat_blockers(settings),
        "warnings": (
            []
            if session_api_available
            else [
                {
                    "code": "session_resources_unavailable",
                    "message": "Hermes API does not advertise persisted session resources",
                }
            ]
        ),
    }


@router.get("/hermes/sessions", response_model=HermesSessionsResponse)
def hermes_sessions(
    settings: SettingsDep,
    gateway: HermesApiReadClientDep,
    _loopback: HermesLoopbackRequestDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict:
    if not settings.hermes_gateway.enabled:
        return {
            "read_status": "unavailable",
            "sessions": [],
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "warnings": [
                {
                    "code": "integration_disabled",
                    "message": "Hermes API session integration is disabled",
                }
            ],
        }
    if gateway is None:
        return {
            "read_status": "unavailable",
            "sessions": [],
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "warnings": [
                {
                    "code": "gateway_client_unavailable",
                    "message": "Hermes API read client is unavailable",
                }
            ],
        }
    try:
        _require_session_resources(gateway)
        result = gateway.list_sessions(limit=limit, offset=offset)
    except HermesApiReadError as exc:
        return {
            "read_status": "unavailable",
            "sessions": [],
            "limit": limit,
            "offset": offset,
            "has_more": False,
            "warnings": _warning(exc),
        }
    return {
        "read_status": "available",
        "sessions": result["data"],
        "limit": result["limit"],
        "offset": result["offset"],
        "has_more": result["has_more"],
        "warnings": [],
    }


@router.get(
    "/hermes/sessions/{session_id}",
    response_model=HermesSessionDetailResponse,
)
def hermes_session_detail(
    session_id: str,
    settings: SettingsDep,
    gateway: HermesApiReadClientDep,
    _loopback: HermesLoopbackRequestDep,
) -> dict:
    safe_session_id = _validated_route_session_id(session_id)
    if not settings.hermes_gateway.enabled:
        return {
            "read_status": "unavailable",
            "session": None,
            "fork_context": {
                "eligible": False,
                "source_channel": None,
                "reason_code": "integration_disabled",
            },
            "warnings": [
                {
                    "code": "integration_disabled",
                    "message": "Hermes API session integration is disabled",
                }
            ],
        }
    if gateway is None:
        return {
            "read_status": "unavailable",
            "session": None,
            "fork_context": {
                "eligible": False,
                "source_channel": None,
                "reason_code": "gateway_client_unavailable",
            },
            "warnings": [
                {
                    "code": "gateway_client_unavailable",
                    "message": "Hermes API read client is unavailable",
                }
            ],
        }
    try:
        _require_session_resources(gateway)
        session = gateway.session_detail(safe_session_id)
    except HermesApiReadError as exc:
        return {
            "read_status": "unavailable",
            "session": None,
            "fork_context": {
                "eligible": False,
                "source_channel": None,
                "reason_code": exc.code,
            },
            "warnings": _warning(exc),
        }
    return {
        "read_status": "available",
        "session": session,
        "fork_context": external_session_fork_context(session),
        "warnings": [],
    }


@router.get(
    "/hermes/sessions/{session_id}/messages",
    response_model=HermesSessionMessagesResponse,
)
def hermes_session_messages(
    session_id: str,
    settings: SettingsDep,
    gateway: HermesApiReadClientDep,
    _loopback: HermesLoopbackRequestDep,
) -> dict:
    safe_session_id = _validated_route_session_id(session_id)
    if not settings.hermes_gateway.enabled:
        return {
            "read_status": "unavailable",
            "session_id": safe_session_id,
            "messages": [],
            "omitted_message_count": 0,
            "warnings": [
                {
                    "code": "integration_disabled",
                    "message": "Hermes API session integration is disabled",
                }
            ],
        }
    if gateway is None:
        return {
            "read_status": "unavailable",
            "session_id": safe_session_id,
            "messages": [],
            "omitted_message_count": 0,
            "warnings": [
                {
                    "code": "gateway_client_unavailable",
                    "message": "Hermes API read client is unavailable",
                }
            ],
        }
    try:
        _require_session_resources(gateway)
        result = gateway.session_messages(safe_session_id)
    except HermesApiReadError as exc:
        return {
            "read_status": "unavailable",
            "session_id": safe_session_id,
            "messages": [],
            "omitted_message_count": 0,
            "warnings": _warning(exc),
        }
    return {
        "read_status": "available",
        "session_id": result["session_id"],
        "messages": result["data"],
        "omitted_message_count": result["omitted_message_count"],
        "warnings": [],
    }


@router.post(
    "/hermes/sessions/{session_id}/forks-to-managed",
    response_model=WorkspaceActionReceiptResponse,
    response_model_exclude_none=True,
)
def hermes_session_fork_to_managed(
    session_id: str,
    body: HermesForkToManagedRequest,
    request: Request,
    settings: SettingsDep,
    gateway: HermesApiReadClientDep,
    _loopback: HermesLoopbackRequestDep,
) -> dict[str, object]:
    """Fork one exact external message into a new server-managed Session."""

    owner = require_mutation_security(request)
    consume_owner_mutation_budget(
        request,
        owner_user_id=owner.owner_user_id,
        route=WORKSPACE_ACT_ROUTE,
    )
    _require_effective_release(settings)
    safe_session_id = _validated_route_session_id(session_id)
    if gateway is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "gateway_client_unavailable",
                "message": "Hermes API client is unavailable",
            },
        )

    mutation_enabled = bool(settings.local_mutation.enabled)
    try:
        receipt = submit_external_session_fork(
            settings,
            gateway,
            hermes_session_id=safe_session_id,
            fork_point=body.fork_point,
            client_action_id=body.client_action_id,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=owner.owner_user_id,
        )
    except HermesApiReadError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except ExternalSessionForkError as exc:
        status = {
            "actor_invalid": 403,
            "fork_point_invalid": 422,
            "fork_point_not_authoritative": 409,
            "session_identity_mismatch": 409,
            "source_session_not_external": 409,
            "source_session_identity_conflict": 409,
            "session_resources_unavailable": 503,
            "source_session_registry_unavailable": 503,
        }.get(exc.code, 503)
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except (AgentWorkspaceActionError, SubmissionSagaError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation", "message": str(exc) or "validation"},
        ) from exc
    return receipt.to_public_dict()
