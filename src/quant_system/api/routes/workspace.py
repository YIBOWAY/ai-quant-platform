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
import math
import time
from collections.abc import Iterator
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from quant_system.api.dependencies import (
    OwnerSessionDep,
    SettingsDep,
    consume_owner_mutation_budget,
    require_mutation_security,
)
from quant_system.api.safety.mutation_rate_limit import (
    WORKSPACE_ACT_ROUTE,
    WORKSPACE_SUBMIT_TURN_ROUTE,
)
from quant_system.api.schemas.workspace import (
    CompositeTurnReceiptResponse,
    WorkspaceActionReceiptResponse,
    WorkspaceAuthoritiesResponse,
    WorkspaceFollowResponse,
    WorkspaceSnapshotResponse,
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
from quant_system.hermes.command_ledger import (
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesCommandNotFound,
)
from quant_system.hermes.composer_readiness import composer_readiness_snapshot
from quant_system.hermes.composite_turn_submit import (
    CompositeTurnSubmitError,
    parse_submit_turn_body,
    submit_composite_turn,
)
from quant_system.hermes.gateway_client import (
    HermesApiReadError,
    HermesRunControlError,
    OfficialHermesRunControlClient,
)
from quant_system.hermes.session_registry import (
    HermesSessionRegistryUnavailable,
    get_workspace_session,
)
from quant_system.hermes.submission_saga import (
    SubmissionSagaError,
    control_plane_session_id,
)

router = APIRouter()

# Hard body ceiling for action documents (bytes of JSON object, not prompt text).
_MAX_ACTION_DOCUMENT_BYTES = 16_384

# Loss of release admission must never trap a user behind an unsafe open run or
# approval.  Only strictly reducing actions bypass the write admission check.
_RELEASE_ROLLBACK_ACTION_KINDS = frozenset(
    {
        "hermes.run.stop",
        "public.cutover.close",
        "v8.public.cutover.close",
        "v8.canary.grant.revoke",
    }
)
_OPERATOR_RELEASE_ACTION_KINDS = frozenset(
    {
        "public.cutover.open",
        "public.cutover.close",
    }
)


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


class WorkspaceRunActivityResponse(BaseModel):
    command_id: str
    stage: Literal[
        "queued",
        "running",
        "analyzing",
        "using_tool",
        "answering",
        "waiting_for_approval",
        "stopping",
        "succeeded",
        "failed",
        "stopped",
    ]
    terminal: bool
    last_activity_at: float | None = None
    tool_state: Literal["active", "completed", "failed"] | None = None
    tool_duration_seconds: float | None = Field(default=None, ge=0)


def _workspace(settings: SettingsDep) -> PlatformAgentWorkspace:
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))
    return build_platform_agent_workspace(settings, mutation_enabled=mutation_enabled)


def _actor(session_owner_user_id: object) -> ActorRef:
    return ActorRef(owner_user_id=str(session_owner_user_id))


def _is_release_rollback_action(action: dict[str, Any]) -> bool:
    kind = action.get("kind")
    if kind in _RELEASE_ROLLBACK_ACTION_KINDS:
        return True
    return kind == "hermes.command_approval.decide" and action.get("decision") == "deny"


def _is_operator_release_action(action: dict[str, Any]) -> bool:
    """Legacy browser cutover acts only return an operator-CLI-required receipt."""

    return action.get("kind") in _OPERATOR_RELEASE_ACTION_KINDS


def _finite_nonnegative(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _summarize_run_activity(events: tuple[dict[str, object], ...]) -> dict[str, object]:
    stage: str | None = None
    last_activity_at: float | None = None
    tool_state: str | None = None
    tool_duration_seconds: float | None = None
    for event in events:
        name = event.get("event")
        if not isinstance(name, str):
            continue
        timestamp = _finite_nonnegative(event.get("timestamp"))
        if timestamp is not None:
            last_activity_at = timestamp
        if name == "reasoning.available":
            stage = "analyzing"
        elif name == "message.delta":
            stage = "answering"
        elif name == "tool.started":
            stage = "using_tool"
            tool_state = "active"
            tool_duration_seconds = None
        elif name == "tool.completed":
            stage = "running"
            tool_state = "failed" if event.get("error") is True else "completed"
            tool_duration_seconds = _finite_nonnegative(event.get("duration"))
        elif name == "approval.request":
            stage = "waiting_for_approval"
        elif name == "run.completed":
            stage = "succeeded"
        elif name == "run.failed":
            stage = "failed"
        elif name in {"run.cancelled", "run.stopped"}:
            stage = "stopped"
    return {
        "stage": stage,
        "last_activity_at": last_activity_at,
        "tool_state": tool_state,
        "tool_duration_seconds": tool_duration_seconds,
    }


def _run_activity_stage(
    status: str,
    substate: object,
    stage: object,
) -> str:
    if status == "succeeded":
        return "succeeded"
    if status == "failed":
        return "failed"
    if status == "stopped":
        return "stopped"
    if substate == "waiting_for_approval":
        return "waiting_for_approval"
    if substate == "stopping":
        return "stopping"
    if status == "queued":
        return "queued"
    return str(stage) if stage in {"analyzing", "using_tool", "answering"} else "running"


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


@router.get(
    "/workspace/{workspace_id}/snapshot",
    response_model=WorkspaceSnapshotResponse,
)
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


@router.get(
    "/workspace/{workspace_id}/commands/{command_id}/activity",
    response_model=WorkspaceRunActivityResponse,
)
def workspace_command_activity(
    workspace_id: str,
    command_id: str,
    settings: SettingsDep,
    owner: OwnerSessionDep,
) -> dict[str, object]:
    try:
        command_uuid = UUID(command_id)
        canonical_command_id = str(command_uuid)
        control_session_id = control_plane_session_id(workspace_id)
    except (ValueError, SubmissionSagaError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation", "message": "workspace or command is invalid"},
        ) from exc

    try:
        command = HermesCommandLedger(settings).get_command(command_uuid)
    except HermesCommandNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "command_not_found", "message": "workspace command not found"},
        ) from exc
    except HermesCommandLedgerUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "command_unavailable", "message": "workspace command is unavailable"},
        ) from exc

    if command.platform_session_id != control_session_id:
        try:
            session = get_workspace_session(
                settings,
                platform_session_id=command.platform_session_id,
            )
        except LookupError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": "command_not_found", "message": "workspace command not found"},
            ) from exc
        except HermesSessionRegistryUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "command_unavailable",
                    "message": "workspace command is unavailable",
                },
            ) from exc
        if session.workspace_id != workspace_id:
            raise HTTPException(
                status_code=404,
                detail={"code": "command_not_found", "message": "workspace command not found"},
            )

    run_id = command.hermes_run_id
    if not isinstance(run_id, str) or not run_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "run_not_bound", "message": "Hermes Run is not bound yet"},
        )

    try:
        gateway = OfficialHermesRunControlClient(settings.hermes_gateway)
        status = gateway.run_status(run_id)
        activity = _summarize_run_activity(gateway.run_events(run_id))
    except (HermesApiReadError, HermesRunControlError) as exc:
        raise HTTPException(
            status_code=404 if exc.code == "run_not_found" else 503,
            detail={
                "code": "run_activity_unavailable",
                "message": "Hermes Run activity is unavailable",
            },
        ) from exc

    run_status = str(status["status"])
    return {
        "command_id": canonical_command_id,
        "stage": _run_activity_stage(
            run_status,
            status.get("substate"),
            activity["stage"],
        ),
        "terminal": run_status in {"succeeded", "failed", "stopped"},
        "last_activity_at": activity["last_activity_at"],
        "tool_state": activity["tool_state"],
        "tool_duration_seconds": activity["tool_duration_seconds"],
    }


@router.get(
    "/workspace/{workspace_id}/follow",
    response_model=WorkspaceFollowResponse,
    response_model_exclude_none=True,
)
def workspace_follow(
    workspace_id: str,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    after_cursor: int | None = None,
) -> dict[str, object]:
    after: WorkspaceCursor | int | None = None if after_cursor is None else after_cursor
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


class WorkspaceEventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


@router.get(
    "/workspace/{workspace_id}/follow/stream",
    response_class=WorkspaceEventStreamResponse,
)
def workspace_follow_stream(
    workspace_id: str,
    request: Request,
    settings: SettingsDep,
    owner: OwnerSessionDep,
    after_cursor: int | None = Query(default=None, ge=0, le=2**63 - 1),
    max_ticks: int | None = Query(default=None, ge=1, le=_SSE_MAX_TICKS_CEILING),
    poll_seconds: float | None = Query(default=None, ge=0.0, le=5.0),
) -> StreamingResponse:
    """Server-Sent Events over workspace follow pages.

    Command lifecycle + approvals/results/vertical ids
    transcript **hints only**. Assistant bodies never ride this stream;
    text authority remains GET /api/hermes/sessions/{id}/messages
    (spine-refetch, not provider-token passthrough).
    """
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))
    workspace = _workspace(settings)
    actor = _actor(owner.owner_user_id)
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None and last_event_id != "":
        if (
            len(last_event_id) <= 19
            and last_event_id.isascii()
            and last_event_id.isdecimal()
            and int(last_event_id) <= 2**63 - 1
        ):
            start_cursor = int(last_event_id)
        else:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_last_event_id",
                    "message": "Last-Event-ID must be a non-negative 63-bit integer",
                },
            )
    elif after_cursor is not None:
        start_cursor = int(after_cursor)
    else:
        start_cursor = 0
    tick_limit = int(max_ticks) if max_ticks is not None else _SSE_MAX_TICKS
    sleep_s = float(poll_seconds) if poll_seconds is not None else _SSE_POLL_SECONDS
    cursor_state = [start_cursor]

    def _sse_pack(event: str, data: dict[str, object]) -> str:
        payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        return f"id: {cursor_state[0]}\nevent: {event}\ndata: {payload}\n\n"

    def event_iter() -> Iterator[str]:
        from quant_system.hermes.approval_observe import (
            ApprovalObserveJournal,
        )
        from quant_system.hermes.result_observe import (
            ResultObserveJournal,
        )
        from quant_system.hermes.transcript_observe import (
            TranscriptObserveJournal,
            hints_from_command_events,
        )
        from quant_system.hermes.vertical_observe import (
            VerticalObserveJournal,
        )

        cursor = start_cursor
        idle = 0
        # Projection fingerprints are delivery state for this connection, not
        # process authority. A process-global fingerprint lets the first
        # browser consume a projection and starves every later subscriber.
        journal = ApprovalObserveJournal()
        result_journal = ResultObserveJournal()
        vertical_journal = VerticalObserveJournal()
        transcript_journal = TranscriptObserveJournal()
        yield _sse_pack(
            "ready",
            {
                "workspace_id": workspace_id,
                "after_cursor": cursor,
                "mutation_enabled": mutation_enabled,
                "transport": "sse",
                # Honest scope marker for FE/docs (V7d–V7g).
                "scope": "command_lifecycle+approvals+results+vertical_ids+transcript_hints",
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
                return
            events = public.get("events") or []
            emitted = False
            if isinstance(events, list) and events:
                for item in events:
                    if isinstance(item, dict):
                        item_event_id = item.get("event_id")
                        if (
                            isinstance(item_event_id, int)
                            and not isinstance(item_event_id, bool)
                            and item_event_id >= cursor
                        ):
                            cursor = item_event_id
                            cursor_state[0] = cursor
                        yield _sse_pack("command", dict(item))
                next_cursor = public.get("next_cursor")
                if (
                    isinstance(next_cursor, int)
                    and not isinstance(next_cursor, bool)
                    and next_cursor >= cursor
                ):
                    cursor = next_cursor
                    cursor_state[0] = cursor
                yield _sse_pack(
                    "cursor",
                    {
                        "next_cursor": cursor,
                        "mutation_enabled": public.get("mutation_enabled"),
                    },
                )
                emitted = True
            # V7d: approvals projection on the same follow spine (not a dual poll).
            # Emit only when the projected set changes (fingerprint), so idle
            # heartbeats still work and we do not flood the stream.
            approvals = public.get("approvals")
            if isinstance(approvals, list):
                changed = journal.take_approvals_if_changed(workspace_id, list(approvals))
                if changed is not None:
                    yield _sse_pack(
                        "approvals",
                        {
                            "approvals": changed,
                            "authority_health": public.get("authority_health")
                            or {"command_approval": "ready"},
                            "mutation_enabled": public.get("mutation_enabled"),
                        },
                    )
                    emitted = True
            # V7f: typed results projection on the same follow spine.
            results = public.get("results")
            if isinstance(results, list):
                r_changed = result_journal.take_results_if_changed(workspace_id, list(results))
                if r_changed is not None:
                    health = public.get("authority_health") or {}
                    yield _sse_pack(
                        "results",
                        {
                            "results": r_changed,
                            "authority_health": {
                                # Prefer explicit health; missing key stays unavailable
                                # rather than inventing ready.
                                "result": health.get("result", "unavailable")
                                if isinstance(health, dict)
                                else "unavailable",
                            },
                            "mutation_enabled": public.get("mutation_enabled"),
                        },
                    )
                    emitted = True
            # V7g: Task/Attempt/Run id lists on the same follow spine (not only
            # snapshot). Fingerprint-gated; never invent from commands.
            tasks = public.get("tasks")
            attempts = public.get("attempts")
            runs = public.get("runs")
            if isinstance(tasks, list) and isinstance(attempts, list) and isinstance(runs, list):
                v_changed = vertical_journal.take_vertical_ids_if_changed(
                    workspace_id,
                    [str(x) for x in tasks],
                    [str(x) for x in attempts],
                    [str(x) for x in runs],
                )
                if v_changed is not None:
                    health = public.get("authority_health") or {}
                    yield _sse_pack(
                        "vertical",
                        {
                            "tasks": v_changed["tasks"],
                            "attempts": v_changed["attempts"],
                            "runs": v_changed["runs"],
                            "authority_health": {
                                "task": health.get("task", "unavailable")
                                if isinstance(health, dict)
                                else "unavailable",
                                "attempt": health.get("attempt", "unavailable")
                                if isinstance(health, dict)
                                else "unavailable",
                                "run": health.get("run", "unavailable")
                                if isinstance(health, dict)
                                else "unavailable",
                            },
                            "mutation_enabled": public.get("mutation_enabled"),
                        },
                    )
                    emitted = True
            # Plan-V6-Token-Stream-M1: body-free transcript hints derived from
            # command events that carry hermes_session_id. Never advances the
            # durable command cursor; never includes assistant text.
            cmd_events = public.get("events") or []
            if isinstance(cmd_events, list) and cmd_events:
                hints = hints_from_command_events(
                    workspace_id=workspace_id,
                    events=cmd_events,  # type: ignore[arg-type]
                    mutation_enabled=bool(public.get("mutation_enabled")),
                )
                t_changed = transcript_journal.take_hints_if_changed(workspace_id, hints)
                if t_changed is not None:
                    for hint in t_changed:
                        yield _sse_pack("transcript", dict(hint))
                    emitted = True
            if emitted:
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
    return WorkspaceEventStreamResponse(
        event_iter(),
        headers=headers,
    )


@router.get(
    "/workspace/authorities",
    response_model=WorkspaceAuthoritiesResponse,
)
def workspace_authorities(
    settings: SettingsDep,
    owner: OwnerSessionDep,
) -> dict[str, object]:
    _ = owner
    # Composite readiness: schema probes + settings-gated local mutation.
    return composer_readiness_snapshot(settings)


@router.post(
    "/workspace/{workspace_id}/act",
    response_model=WorkspaceActionReceiptResponse,
    response_model_exclude_none=True,
)
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
    # A burst guard must never trap the owner behind an unsafe open run or
    # cutover. Strictly reducing/idempotent rollback actions retain their
    # release-admission bypass; every other /act mutation consumes the budget.
    if not _is_release_rollback_action(raw):
        consume_owner_mutation_budget(
            request,
            owner_user_id=owner.owner_user_id,
            route=WORKSPACE_ACT_ROUTE,
        )
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

    if not _is_release_rollback_action(raw) and not _is_operator_release_action(raw):
        _require_effective_release(settings)

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


@router.post(
    "/agent/workspace/submit-turn",
    response_model=CompositeTurnReceiptResponse,
    response_model_exclude_none=True,
)
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
    consume_owner_mutation_budget(
        request,
        owner_user_id=owner.owner_user_id,
        route=WORKSPACE_SUBMIT_TURN_ROUTE,
    )
    mutation_enabled = bool(getattr(settings.local_mutation, "enabled", False))
    _require_effective_release(settings)

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
