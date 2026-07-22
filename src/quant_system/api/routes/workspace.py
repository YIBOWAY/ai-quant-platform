"""Thin AgentWorkspace transport adapter (V4 + L2a-Send composite submit).

Routes only translate HTTP ↔ PlatformAgentWorkspace / composite turn submit.
Recovery / idempotency lives in submission_saga + agent_workspace — never
reimplemented here.

Mutation defaults OFF. Local installs open POST /act and submit-turn via
``QS_LOCAL_MUTATION_ENABLED`` (session + CSRF + origin still required).
``/act`` stays prompt-free; chat prompt enters only via submit-turn.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from quant_system.api.dependencies import (
    OwnerSessionDep,
    SettingsDep,
    require_mutation_security,
)
from quant_system.hermes.agent_workspace import (
    ActorRef,
    PlatformAgentWorkspace,
    WorkspaceCursor,
    build_platform_agent_workspace,
)
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    WorkspaceRef,
)
from quant_system.hermes.composer_readiness import composer_readiness_snapshot
from quant_system.hermes.composite_turn_submit import (
    CompositeTurnSubmitError,
    parse_submit_turn_body,
    submit_composite_turn,
)
from quant_system.hermes.submission_saga import SubmissionSagaError

router = APIRouter()

# Hard body ceiling for action documents (bytes of JSON object, not prompt text).
_MAX_ACTION_DOCUMENT_BYTES = 16_384


class WorkspaceActRequest(BaseModel):
    action: dict[str, Any] = Field(min_length=1)


class WorkspaceFollowRequest(BaseModel):
    after_cursor: int | None = Field(default=None, ge=0, le=2**63 - 1)


class SubmitTurnRequest(BaseModel):
    """Closed browser body for Composite Turn Submit (A2)."""

    workspace_id: str = Field(min_length=1, max_length=200)
    managed_session_ref: str = Field(min_length=1, max_length=220)
    client_action_id: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1)


def _workspace(settings: SettingsDep) -> PlatformAgentWorkspace:
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))
    return build_platform_agent_workspace(settings, mutation_enabled=mutation_enabled)


def _actor(session_owner_user_id: object) -> ActorRef:
    return ActorRef(owner_user_id=str(session_owner_user_id))


def _http_from_saga(exc: SubmissionSagaError, *, mutation_enabled: bool = False) -> HTTPException:
    status = {
        "auth": 401,
        "forbidden": 403,
        "validation": 422,
        "conflict": 409,
        "unavailable": 503,
    }.get(exc.code, 400)
    return HTTPException(
        status_code=status,
        detail={
            "code": exc.code,
            "message": exc.message,
            "mutation_enabled": bool(mutation_enabled),
        },
    )


@router.get("/workspace/{workspace_id}/snapshot")
def workspace_snapshot(
    workspace_id: str,
    settings: SettingsDep,
    owner: OwnerSessionDep,
) -> dict[str, object]:
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))
    try:
        snap = _workspace(settings).snapshot(
            _actor(owner.owner_user_id),
            WorkspaceRef(workspace_id=workspace_id),
        )
    except (SubmissionSagaError, AgentWorkspaceActionError, ValueError, TypeError) as exc:
        if isinstance(exc, SubmissionSagaError):
            raise _http_from_saga(exc, mutation_enabled=mutation_enabled) from exc
        raise HTTPException(
            status_code=422,
            detail={"code": "validation", "message": str(exc) or "validation"},
        ) from exc
    return snap.to_public_dict()


@router.get("/workspace/{workspace_id}/follow")
def workspace_follow(
    workspace_id: str,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    after_cursor: int | None = None,
) -> dict[str, object]:
    after: WorkspaceCursor | int | None
    if after_cursor is None:
        after = None
    else:
        after = after_cursor
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))
    try:
        page = _workspace(settings).follow(
            _actor(owner.owner_user_id),
            WorkspaceRef(workspace_id=workspace_id),
            after=after,
        )
    except (SubmissionSagaError, AgentWorkspaceActionError, ValueError, TypeError) as exc:
        if isinstance(exc, SubmissionSagaError):
            raise _http_from_saga(exc, mutation_enabled=mutation_enabled) from exc
        raise HTTPException(
            status_code=422,
            detail={"code": "validation", "message": str(exc) or "validation"},
        ) from exc
    return page.to_public_dict()


@router.get("/workspace/authorities")
def workspace_authorities(
    settings: SettingsDep,
    owner: OwnerSessionDep,
) -> dict[str, object]:
    _ = owner
    # Composite readiness: schema probes + settings-gated local mutation.
    return composer_readiness_snapshot(settings)


@router.post("/workspace/{workspace_id}/act")
def workspace_act(
    workspace_id: str,
    body: WorkspaceActRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    """Mutation entry. Defaults fail-closed; opens via QS_LOCAL_MUTATION_ENABLED."""
    # Enforce owner session + CSRF + origin before any action parse / PG I/O.
    owner = require_mutation_security(request)
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))

    raw = body.action
    # Cheap size ceiling on the action object (not a prompt store).
    try:
        import json

        encoded = json.dumps(raw, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation", "message": "action must be JSON-serializable"},
        ) from exc
    if len(encoded.encode("utf-8")) > _MAX_ACTION_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "validation", "message": "action document exceeds size ceiling"},
        )

    # Defensive: workspace path param must match document workspace when present.
    doc_workspace = raw.get("workspace") if isinstance(raw, dict) else None
    if isinstance(doc_workspace, dict):
        doc_id = doc_workspace.get("workspace_id")
        if doc_id is not None and doc_id != workspace_id:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "validation",
                    "message": "workspace_id path/body mismatch",
                },
            )

    try:
        receipt = _workspace(settings).act(_actor(owner.owner_user_id), raw)
    except (SubmissionSagaError, AgentWorkspaceActionError, ValueError, TypeError) as exc:
        if isinstance(exc, SubmissionSagaError):
            raise _http_from_saga(exc, mutation_enabled=mutation_enabled) from exc
        raise HTTPException(
            status_code=422,
            detail={"code": "validation", "message": str(exc) or "validation"},
        ) from exc
    return receipt.to_public_dict()


@router.post("/agent/workspace/submit-turn")
def workspace_submit_turn(
    body: SubmitTurnRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    """Composite Turn Submit (L2a-Send A2): put intent then conversation.turn.

    Body is exactly ``workspace_id``, ``managed_session_ref``,
    ``client_action_id``, ``prompt``. Prompt never accepted on ``/act``.
    """
    owner = require_mutation_security(request)
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))

    # Reject oversized prompts before any store I/O (Pydantic already requires
    # nonempty; profile enforces 16 KiB + strip).
    try:
        parsed = parse_submit_turn_body(body.model_dump())
    except CompositeTurnSubmitError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={
                "code": exc.code,
                "message": exc.message,
                "mutation_enabled": mutation_enabled,
            },
        ) from exc

    # Optional test/double injection via app.state.services.
    port = None
    services = getattr(request.app.state, "services", None)
    if isinstance(services, dict):
        port = services.get("intent_payload_port")

    try:
        return submit_composite_turn(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=owner.owner_user_id,
            port=port,
        )
    except CompositeTurnSubmitError as exc:
        raise HTTPException(
            status_code=exc.http_status,
            detail={
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "mutation_enabled": mutation_enabled,
            },
        ) from exc
