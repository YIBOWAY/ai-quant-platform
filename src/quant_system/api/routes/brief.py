from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.brief import (
    BriefGenerateRequest,
    BriefIssueEnvelopeResponse,
    BriefIssueResponse,
    BriefSnapshotResponse,
)
from quant_system.brief.models import BriefIssueEnvelope
from quant_system.brief.repository import (
    BriefDatabaseUnavailable,
    BriefNotFound,
    BriefRepository,
)
from quant_system.brief.service import BriefService

router = APIRouter()


@router.post(
    "/brief/issues/generate",
    response_model=BriefIssueEnvelopeResponse,
)
def generate_brief_issue(
    request: BriefGenerateRequest,
    settings: SettingsDep,
) -> BriefIssueEnvelopeResponse:
    service = BriefService(BriefRepository(settings))
    try:
        envelope = service.generate_issue(
            issue_date=request.issue_date,
            locale=request.locale,
        )
    except BriefDatabaseUnavailable as exc:
        raise _database_unavailable_503() from exc
    return _to_response(envelope)


@router.get(
    "/brief/issues/latest",
    response_model=BriefIssueEnvelopeResponse,
)
def get_latest_brief_issue(
    settings: SettingsDep,
    locale: Annotated[str, Query()] = "zh",
    issue_date: Annotated[date | None, Query()] = None,
) -> BriefIssueEnvelopeResponse:
    service = BriefService(BriefRepository(settings))
    try:
        envelope = service.get_latest_issue(
            locale=locale,
            issue_date=issue_date,
        )
    except BriefDatabaseUnavailable as exc:
        raise _database_unavailable_503() from exc
    except BriefNotFound as exc:
        raise _latest_not_found_404() from exc
    return _to_response(envelope)


@router.get(
    "/brief/issues/{public_id}",
    response_model=BriefIssueEnvelopeResponse,
)
def get_brief_issue(
    public_id: str,
    settings: SettingsDep,
) -> BriefIssueEnvelopeResponse:
    service = BriefService(BriefRepository(settings))
    try:
        envelope = service.get_issue(public_id)
    except BriefDatabaseUnavailable as exc:
        raise _database_unavailable_503() from exc
    except BriefNotFound as exc:
        raise _not_found_404(public_id) from exc
    return _to_response(envelope)


def _to_response(envelope: BriefIssueEnvelope) -> BriefIssueEnvelopeResponse:
    return BriefIssueEnvelopeResponse(
        issue=BriefIssueResponse(
            issue_id=envelope.issue.issue_id,
            public_id=envelope.issue.public_id,
            issue_date=envelope.issue.issue_date,
            locale=envelope.issue.locale,
            status=envelope.issue.status,
        ),
        snapshot=BriefSnapshotResponse(
            snapshot_id=envelope.snapshot.snapshot_id,
            version=envelope.snapshot.version,
            payload=envelope.snapshot.payload,
            source_watermark=envelope.snapshot.source_watermark,
        ),
        warnings=envelope.warnings,
    )


def _database_unavailable_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "brief_database_unavailable",
            "message": "Brief archive database is unavailable.",
        },
    )


def _not_found_404(public_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "brief_not_found",
            "public_id": public_id,
            "message": f"Brief archive issue {public_id!r} was not found.",
        },
    )


def _latest_not_found_404() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "brief_not_found",
            "message": "No brief archive issue was found for the requested locale.",
        },
    )
