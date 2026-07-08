from __future__ import annotations

import secrets
from datetime import date
from typing import Any

from quant_system.brief.models import BriefIssueEnvelope
from quant_system.brief.repository import BriefRepository

_TOKEN_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


class BriefService:
    def __init__(self, repository: BriefRepository) -> None:
        self._repository = repository

    def generate_issue(
        self,
        *,
        issue_date: date | None,
        locale: str,
    ) -> BriefIssueEnvelope:
        active_date = issue_date or date.today()
        normalized_locale = locale.strip() or "zh"
        return self._repository.create_snapshot(
            issue_date=active_date,
            locale=normalized_locale,
            public_id=_new_public_id(active_date),
            payload=_build_payload(issue_date=active_date, locale=normalized_locale),
            source_watermark={},
        )

    def get_issue(self, public_id: str) -> BriefIssueEnvelope:
        return self._repository.get_latest_by_public_id(public_id)


def _build_payload(*, issue_date: date, locale: str) -> dict[str, Any]:
    return {
        "title": "每日晨报" if locale == "zh" else "Daily Brief",
        "issue_date": issue_date.isoformat(),
        "sections": {
            "market": [],
            "ai_news": [],
            "paper_equity": [],
            "hermes_log": [],
        },
    }


def _new_public_id(issue_date: date) -> str:
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(6))
    return f"brf_{issue_date:%Y%m%d}_{token}"
