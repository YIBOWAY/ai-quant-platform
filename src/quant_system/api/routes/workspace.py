"""Thin AgentWorkspace transport adapter (V4).

Routes only translate HTTP ↔ PlatformAgentWorkspace. Recovery / idempotency
lives in submission_saga + agent_workspace — never reimplemented here.

Public mutation stays OFF: POST /act always runs require_mutation_security with
mutation_enabled=False → 403 authenticated_mutation_bff_unavailable and zero
authority writes.
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
from quant_system.hermes.submission_saga import SubmissionSagaError

router = APIRouter()

# Hard body ceiling for action documents (bytes of JSON object, not prompt text).
_MAX_ACTION_DOCUMENT_BYTES = 16_384


class WorkspaceActRequest(BaseModel):
    action: dict[str, Any] = Field(min_length=1)


class WorkspaceFollowRequest(BaseModel):
    after_cursor: int | None = Field(default=None, ge=0, le=2**63 - 1)


def _workspace(settings: SettingsDep) -> PlatformAgentWorkspace:
    # Public factory: mutation_enabled always False.
    return build_platform_agent_workspace(settings, mutation_enabled=False)


def _actor(session_owner_user_id: object) -> ActorRef:
    return ActorRef(owner_user_id=str(session_owner_user_id))


def _http_from_saga(exc: SubmissionSagaError) -> HTTPException:
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
            "mutation_enabled": False,
        },
    )


@router.get("/workspace/{workspace_id}/snapshot")
def workspace_snapshot(
    workspace_id: str,
    settings: SettingsDep,
    owner: OwnerSessionDep,
) -> dict[str, object]:
    try:
        snap = _workspace(settings).snapshot(
            _actor(owner.owner_user_id),
            WorkspaceRef(workspace_id=workspace_id),
        )
    except (SubmissionSagaError, AgentWorkspaceActionError, ValueError, TypeError) as exc:
        if isinstance(exc, SubmissionSagaError):
            raise _http_from_saga(exc) from exc
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
    try:
        page = _workspace(settings).follow(
            _actor(owner.owner_user_id),
            WorkspaceRef(workspace_id=workspace_id),
            after=after,
        )
    except (SubmissionSagaError, AgentWorkspaceActionError, ValueError, TypeError) as exc:
        if isinstance(exc, SubmissionSagaError):
            raise _http_from_saga(exc) from exc
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
    # Composite readiness: schema probes + permanent platform blockers.
    # Public mutation / composer write stay hard OFF regardless of schema.
    return composer_readiness_snapshot(settings)


@router.post("/workspace/{workspace_id}/act")
def workspace_act(
    workspace_id: str,
    body: WorkspaceActRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    """Mutation entry. Fail-closed until the V4/V8 write gate opens.

    require_mutation_security hard-codes mutation_enabled=False, so this path
    never reaches PlatformAgentWorkspace.act against PostgreSQL.
    """
    # Enforce owner session + CSRF + origin before any action parse / PG I/O.
    owner = require_mutation_security(request)

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

    # Unreachable for public traffic today: mutation precheck raises first.
    # Kept so hermetic future enablement only flips the dependency gate.
    try:
        receipt = _workspace(settings).act(_actor(owner.owner_user_id), raw)
    except (SubmissionSagaError, AgentWorkspaceActionError, ValueError, TypeError) as exc:
        if isinstance(exc, SubmissionSagaError):
            raise _http_from_saga(exc) from exc
        raise HTTPException(
            status_code=422,
            detail={"code": "validation", "message": str(exc) or "validation"},
        ) from exc
    return receipt.to_public_dict()
