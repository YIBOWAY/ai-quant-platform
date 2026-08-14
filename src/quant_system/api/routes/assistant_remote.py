from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from quant_system.api.dependencies import SettingsDep
from quant_system.api.routes.d34 import (
    _authority,
    _http_error as _mandate_http_error,
    _job_authority,
)
from quant_system.d34.research_request import (
    enqueue_owner_research_request,
    mandate_field,
)
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    dispatch_research,
    hang_candidate,
    project_book,
    reconcile_dispatched_requests,
)
from quant_system.hermes.d34_job_authority import JobAuthorityError
from quant_system.hermes.d34_mandate_authority import MandateAuthorityError

router = APIRouter()

_WORKSPACE_ID = "default"


def _active_paper_mandate(request: Request, settings: SettingsDep):
    """Return the active paper mandate, or None when dispatch must stay book-only.

    Authority / DB failures propagate. Only a genuine missing mandate stays
    book-only; a down database must not look like a successful dispatch.
    """
    mandate = _authority(request, settings).get_active(workspace_id=_WORKSPACE_ID)
    if mandate is None:
        return None
    if str(mandate_field(mandate, "status")) != "active":
        return None
    if mandate_field(mandate, "expires_at") <= datetime.now(UTC):
        return None
    if mandate_field(mandate, "paper_execution_allowed") is not True:
        return None
    return mandate


class RemoteDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=8, max_length=4000)
    hang_if_pass: bool = False


class RemoteHangRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=128)


def _http_error(exc: AssistantRemoteError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": exc.code, "message": exc.code})


@router.get("/assistant/remote/book")
def get_remote_book(request: Request, settings: SettingsDep) -> dict[str, object]:
    try:
        reconcile_dispatched_requests(
            settings,
            jobs=_job_authority(request, settings),
            workspace_id=_WORKSPACE_ID,
        )
    except JobAuthorityError as exc:
        if exc.code == "d34_job_validation":
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        # Unavailable / other lane faults: stale book is last observed truth.
    except Exception:  # noqa: BLE001
        pass
    return project_book(settings)


@router.post("/assistant/remote/dispatch")
def post_remote_dispatch(
    body: RemoteDispatchRequest,
    request: Request,
    settings: SettingsDep,
) -> dict[str, object]:
    try:
        mandate = _active_paper_mandate(request, settings)
    except MandateAuthorityError as exc:
        raise _mandate_http_error(exc) from exc
    enqueue = None
    if mandate is not None:
        jobs = _job_authority(request, settings)

        def enqueue(objective: str, hang_if_pass: bool) -> str:
            # Isolation dispatch stops at verified candidate. Hang is a
            # separate digest-bound command; never arm worker canary.
            _ = hang_if_pass
            return enqueue_owner_research_request(
                jobs=jobs,
                mandate=mandate,
                workspace_id=_WORKSPACE_ID,
                objective=objective,
                cycle_date=datetime.now(ZoneInfo("Asia/Shanghai")).date(),
                hang_if_pass=False,
            )

    try:
        return dispatch_research(
            settings,
            objective=body.objective,
            hang_if_pass=body.hang_if_pass,
            enqueue_job=enqueue,
        )
    except AssistantRemoteError as exc:
        raise _http_error(exc) from exc
    except (JobAuthorityError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "research_job_enqueue_failed", "message": str(exc)},
        ) from exc


@router.post("/assistant/remote/hang")
def post_remote_hang(
    body: RemoteHangRequest,
    settings: SettingsDep,
) -> dict[str, object]:
    try:
        return hang_candidate(settings, candidate_id=body.candidate_id)
    except AssistantRemoteError as exc:
        raise _http_error(exc) from exc
