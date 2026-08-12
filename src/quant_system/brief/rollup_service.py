"""Weekly/monthly brief rollup service orchestration.

Reads the period's daily brief payloads through ``BriefRepository``, runs the
two-pass LLM rollup pipeline in :mod:`quant_system.brief.rollup`, and persists
the validated payload through ``BriefRollupRepository``. The rollup repository
is duck-typed at runtime (typed under ``TYPE_CHECKING``) so this module stays
importable while that module lands independently.
"""

from __future__ import annotations

import secrets
from datetime import date
from typing import TYPE_CHECKING

from quant_system.brief.repository import BriefRepository
from quant_system.brief.rollup import RollupLlm
from quant_system.brief.rollup import generate_rollup as _generate_rollup_payload
from quant_system.brief.rollup_llm import RollupLlmUnavailable

if TYPE_CHECKING:
    from quant_system.brief.rollup_repository import (
        BriefRollupEnvelope,
        BriefRollupListItem,
        BriefRollupRepository,
    )

_TOKEN_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


class BriefRollupService:
    def __init__(
        self,
        brief_repository: BriefRepository,
        rollup_repository: BriefRollupRepository,
        llm: RollupLlm | None = None,
    ) -> None:
        self._brief_repository = brief_repository
        self._rollup_repository = rollup_repository
        self._llm = llm

    def generate_rollup(
        self,
        *,
        kind: str,
        period_key: str,
        period_start: date,
        period_end: date,
        locale: str,
    ) -> BriefRollupEnvelope:
        if self._llm is None:
            raise RollupLlmUnavailable("brief rollup LLM is not configured")
        normalized_locale = locale.strip() or "zh"
        issues = self._brief_repository.list_issue_payloads(
            locale=normalized_locale,
            start=period_start,
            end=period_end,
        )
        payload = _generate_rollup_payload(
            kind=kind,
            period_key=period_key,
            period_start=period_start,
            period_end=period_end,
            locale=normalized_locale,
            issues=issues,
            llm=self._llm,
        )
        provenance = payload.get("provenance") or {}
        return self._rollup_repository.create_snapshot(
            kind=kind,
            period_key=period_key,
            period_start=period_start,
            period_end=period_end,
            locale=normalized_locale,
            public_id=_new_rollup_public_id(kind, period_start),
            payload=payload,
            source_watermark={
                "kind": kind,
                "period_key": period_key,
                "captured_at": provenance.get("generated_at"),
                "facts_digest": provenance.get("facts_digest"),
                "source_issue_public_ids": provenance.get("source_issue_public_ids") or [],
            },
        )

    def get_rollup(self, public_id: str) -> BriefRollupEnvelope:
        return self._rollup_repository.get_latest_by_public_id(public_id)

    def list_rollups(
        self,
        *,
        kind: str,
        locale: str,
        limit: int = 30,
    ) -> list[BriefRollupListItem]:
        normalized_locale = locale.strip() or "zh"
        return self._rollup_repository.list_rollups(
            kind=kind,
            locale=normalized_locale,
            limit=limit,
        )


def _new_rollup_public_id(kind: str, period_start: date) -> str:
    token = "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(6))
    prefix = "brw" if kind == "weekly" else "brm"
    return f"{prefix}_{period_start:%Y%m%d}_{token}"
