from __future__ import annotations

from collections.abc import Mapping

from fastapi import APIRouter, HTTPException, Query

from quant_system.api.dependencies import (
    HermesApiReadClientDep,
    HermesLoopbackRequestDep,
    SettingsDep,
)
from quant_system.api.schemas.hermes import (
    HermesArtifactFeedResponse,
    HermesGatewayStatusResponse,
    HermesSessionDetailResponse,
    HermesSessionMessagesResponse,
    HermesSessionsResponse,
)
from quant_system.hermes.artifact_catalog import HermesArtifactCatalog
from quant_system.hermes.gateway_client import (
    HermesApiReadClient,
    HermesApiReadError,
    validate_hermes_session_id,
)

router = APIRouter()


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


_CHAT_WRITE_BLOCKERS = [
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
            "blockers": ["integration_disabled", *_CHAT_WRITE_BLOCKERS],
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
            "blockers": ["gateway_client_unavailable", *_CHAT_WRITE_BLOCKERS],
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
            "blockers": ["gateway_unavailable", *_CHAT_WRITE_BLOCKERS],
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
        "blockers": list(_CHAT_WRITE_BLOCKERS),
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
