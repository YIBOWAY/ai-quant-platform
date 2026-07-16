from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from quant_system.api.dependencies import (
    AgentOutputDirDep,
    ApiRunsDirDep,
    HermesApiReadClientDep,
    HermesLoopbackRequestDep,
    OutputDirDep,
    SettingsDep,
)
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
from quant_system.hermes.artifact_catalog import HermesArtifactCatalog
from quant_system.hermes.gateway_client import (
    HermesApiReadClient,
    HermesApiReadError,
    validate_hermes_session_id,
)
from quant_system.hermes.results_catalog import HermesResultsCatalog

router = APIRouter()


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


_UPSTREAM_CHAT_WRITE_BLOCKERS = [
    "run_submission_not_idempotent",
    "request_recovery_unavailable",
    "event_id_unavailable",
    "event_replay_unavailable",
    "run_status_not_persistent",
    "provider_policy_not_immutable",
    "actual_provider_evidence_unavailable",
    "approval_exact_binding_unavailable",
    "stop_reconciliation_unavailable",
]

_PLATFORM_CHAT_DELIVERY_BLOCKERS = [
    "authenticated_mutation_bff_unavailable",
    "csrf_protection_unavailable",
    "prompt_retention_boundary_unavailable",
    "command_dispatch_adapter_unavailable",
    "hqa_task_attempt_binding_unavailable",
    "composer_resume_stop_unavailable",
    "independent_security_review_unavailable",
    "user_chat_cutover_approval_required",
]


def _chat_blockers(*operational: str) -> dict[str, list[str]]:
    upstream = list(_UPSTREAM_CHAT_WRITE_BLOCKERS)
    platform = list(_PLATFORM_CHAT_DELIVERY_BLOCKERS)
    return {
        "upstream_blockers": upstream,
        "platform_delivery_blockers": platform,
        "blockers": [*operational, *upstream, *platform],
    }


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
    if not settings.hermes_gateway.enabled:
        return {
            "read_status": "unavailable",
            "connected": False,
            "model": None,
            "session_api_available": False,
            "chat_write_ready": False,
            "features": {},
            **_chat_blockers("integration_disabled"),
            "warnings": [],
        }
    if gateway is None:
        return {
            "read_status": "unavailable",
            "connected": False,
            "model": None,
            "session_api_available": False,
            "chat_write_ready": False,
            "features": {},
            **_chat_blockers("gateway_client_unavailable"),
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
            "chat_write_ready": False,
            "features": {},
            **_chat_blockers("gateway_unavailable"),
            "warnings": _warning(exc),
        }
    features = capabilities["features"]
    session_api_available = features.get("session_resources") is True
    return {
        "read_status": "available" if session_api_available else "degraded",
        "connected": True,
        "model": capabilities.get("model"),
        "session_api_available": session_api_available,
        "chat_write_ready": False,
        "features": features,
        **_chat_blockers(),
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
            "warnings": _warning(exc),
        }
    return {"read_status": "available", "session": session, "warnings": []}


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
