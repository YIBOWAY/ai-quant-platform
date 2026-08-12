from __future__ import annotations

import secrets
from datetime import date

from quant_system.brief.archive import (
    BriefArchiveView,
    archive_range_start,
    build_archive_view,
)
from quant_system.brief.models import (
    BriefArchivePayload,
    BriefIssue,
    BriefIssueEnvelope,
    BriefSourceWatermark,
)
from quant_system.brief.repository import BriefRepository

_TOKEN_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


class BriefSnapshotMismatch(ValueError):
    """Raised before persistence when request and snapshot identities differ."""


class BriefService:
    def __init__(self, repository: BriefRepository) -> None:
        self._repository = repository

    def generate_issue(
        self,
        *,
        issue_date: date | None,
        locale: str,
        payload: BriefArchivePayload,
        source_watermark: BriefSourceWatermark,
    ) -> BriefIssueEnvelope:
        active_date = issue_date or payload.issue_date
        normalized_locale = locale.strip() or "zh"
        if payload.issue_date != active_date:
            raise BriefSnapshotMismatch(
                "brief request issue_date must match payload issue_date"
            )
        if payload.locale != normalized_locale:
            raise BriefSnapshotMismatch("brief request locale must match payload locale")
        return self._repository.create_snapshot(
            issue_date=active_date,
            locale=normalized_locale,
            public_id=_new_public_id(active_date),
            payload=payload.model_dump(mode="json", exclude_unset=True),
            source_watermark=source_watermark.model_dump(
                mode="json",
                exclude_unset=True,
            ),
        )

    def get_issue(self, public_id: str) -> BriefIssueEnvelope:
        return self._repository.get_latest_by_public_id(public_id)

    def get_latest_issue(
        self,
        *,
        locale: str,
        issue_date: date | None = None,
    ) -> BriefIssueEnvelope:
        normalized_locale = locale.strip() or "zh"
        return self._repository.get_latest(
            locale=normalized_locale,
            issue_date=issue_date,
        )

    def list_issues(
        self,
        *,
        locale: str,
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[BriefIssue], int]:
        normalized_locale = locale.strip() or "zh"
        return self._repository.list_issues(
            locale=normalized_locale,
            limit=limit,
            offset=offset,
        )

    def list_archive(
        self,
        *,
        locale: str,
        months: int = 3,
        today: date | None = None,
    ) -> BriefArchiveView:
        normalized_locale = locale.strip() or "zh"
        safe_months = max(1, min(int(months), 24))
        end = today or date.today()
        start = archive_range_start(end, safe_months)
        rows = self._repository.list_issue_archive_rows(
            locale=normalized_locale,
            start=start,
            end=end,
        )
        return build_archive_view(rows)


def _new_public_id(issue_date: date) -> str:
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(6))
    return f"brf_{issue_date:%Y%m%d}_{token}"
