from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from quant_system.api.dependencies import SettingsDep
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    dispatch_research,
    hang_candidate,
    project_book,
)

router = APIRouter()


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
def get_remote_book(settings: SettingsDep) -> dict[str, object]:
    return project_book(settings)


@router.post("/assistant/remote/dispatch")
def post_remote_dispatch(
    body: RemoteDispatchRequest,
    settings: SettingsDep,
) -> dict[str, object]:
    try:
        return dispatch_research(
            settings,
            objective=body.objective,
            hang_if_pass=body.hang_if_pass,
        )
    except AssistantRemoteError as exc:
        raise _http_error(exc) from exc


@router.post("/assistant/remote/hang")
def post_remote_hang(
    body: RemoteHangRequest,
    settings: SettingsDep,
) -> dict[str, object]:
    try:
        return hang_candidate(settings, candidate_id=body.candidate_id)
    except AssistantRemoteError as exc:
        raise _http_error(exc) from exc
