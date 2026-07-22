"""Thin AgentWorkspace transport adapter (V4 + L2a-Send composite submit).

Routes only translate HTTP ↔ PlatformAgentWorkspace / composite turn submit.
Recovery / idempotency lives in submission_saga + agent_workspace — never
reimplemented here.

Mutation defaults OFF. Local installs open POST /act and submit-turn via
``QS_LOCAL_MUTATION_ENABLED`` (session + CSRF + origin still required).
``/act`` stays prompt-free; chat prompt enters only via submit-turn.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
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


# L4b-SSE-Follow-M1: long-poll style SSE over the same durable follow page.
# Not assistant token stream; no message bodies; owner cookie required.
_SSE_POLL_SECONDS = 1.0
_SSE_HEARTBEAT_EVERY = 3
_SSE_MAX_TICKS = 600  # ~10 min then client reconnects
_SSE_MAX_TICKS_CEILING = 600


@router.get("/workspace/{workspace_id}/follow/stream")
def workspace_follow_stream(
    workspace_id: str,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    after_cursor: int | None = Query(default=0, ge=0, le=2**63 - 1),
    max_ticks: int | None = Query(default=None, ge=1, le=_SSE_MAX_TICKS_CEILING),
    poll_seconds: float | None = Query(default=None, ge=0.0, le=5.0),
) -> StreamingResponse:
    """Server-Sent Events over workspace follow pages (command lifecycle only)."""
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))
    workspace = _workspace(settings)
    actor = _actor(owner.owner_user_id)
    start_cursor = 0 if after_cursor is None else int(after_cursor)
    tick_limit = int(max_ticks) if max_ticks is not None else _SSE_MAX_TICKS
    sleep_s = float(poll_seconds) if poll_seconds is not None else _SSE_POLL_SECONDS

    def _sse_pack(event: str, data: dict[str, object]) -> str:
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return f"event: {event}\ndata: {payload}\n\n"

    def event_iter() -> Iterator[str]:
        cursor = start_cursor
        idle = 0
        yield _sse_pack(
            "ready",
            {
                "workspace_id": workspace_id,
                "after_cursor": cursor,
                "mutation_enabled": mutation_enabled,
                "transport": "sse",
                # Honest scope marker for FE/docs.
                "scope": "command_lifecycle",
            },
        )
        for _tick in range(tick_limit):
            try:
                page = workspace.follow(
                    actor,
                    WorkspaceRef(workspace_id=workspace_id),
                    after=cursor,
                )
            except (SubmissionSagaError, AgentWorkspaceActionError, ValueError, TypeError) as exc:
                code = getattr(exc, "code", "validation")
                message = str(getattr(exc, "message", "") or exc)
                yield _sse_pack(
                    "error",
                    {
                        "code": str(code),
                        "message": message,
                        "mutation_enabled": mutation_enabled,
                    },
                )
                return
            except Exception as exc:  # noqa: BLE001 — stream must not 500 mid-body
                yield _sse_pack(
                    "error",
                    {
                        "code": "unavailable",
                        "message": str(exc) or "follow_stream_failed",
                        "mutation_enabled": mutation_enabled,
                    },
                )
                return

            public = page.to_public_dict()
            if public.get("resync_required"):
                yield _sse_pack(
                    "resync",
                    {
                        "after_cursor": public.get("after_cursor"),
                        "recovery_action": public.get("recovery_action"),
                        "mutation_enabled": public.get("mutation_enabled"),
                    },
                )
                # Client must snapshot; keep cursor until they reconnect with new head.
                idle = 0
                if sleep_s > 0:
                    time.sleep(sleep_s)
                continue

            events = public.get("events") or []
            if isinstance(events, list) and events:
                for item in events:
                    if isinstance(item, dict):
                        yield _sse_pack("command", dict(item))
                next_cursor = public.get("next_cursor")
                if isinstance(next_cursor, int):
                    cursor = next_cursor
                yield _sse_pack(
                    "cursor",
                    {
                        "next_cursor": cursor,
                        "mutation_enabled": public.get("mutation_enabled"),
                    },
                )
                idle = 0
            else:
                idle += 1
                if idle % _SSE_HEARTBEAT_EVERY == 0:
                    yield _sse_pack(
                        "heartbeat",
                        {
                            "cursor": cursor,
                            "mutation_enabled": public.get("mutation_enabled"),
                        },
                    )
            if sleep_s > 0:
                time.sleep(sleep_s)

        yield _sse_pack(
            "reconnect",
            {
                "next_cursor": cursor,
                "reason": "max_ticks",
            },
        )

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers=headers,
    )


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
