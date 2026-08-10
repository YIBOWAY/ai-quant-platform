"""PostgreSQL authority for append-only factor-automation lifecycle events."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.storage.database import DatabaseUnavailable, get_database

FactorAutomationEventType = Literal[
    "promotion_committed",
    "sleeve_created",
    "sleeve_paused",
    "demote_started",
    "quarantined_hold",
    "flattened",
    "transferred",
    "manually_accepted",
    "demoted_complete",
]

_EVENT_TYPES = frozenset(
    {
        "promotion_committed",
        "sleeve_created",
        "sleeve_paused",
        "demote_started",
        "quarantined_hold",
        "flattened",
        "transferred",
        "manually_accepted",
        "demoted_complete",
    }
)
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")


class FactorAutomationAuthorityError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class FactorAutomationAuthorityConflict(FactorAutomationAuthorityError):
    pass


class FactorAutomationAuthorityUnavailable(FactorAutomationAuthorityError):
    pass


@dataclass(frozen=True)
class FactorAutomationLineage:
    automation_id: str
    candidate_id: str
    candidate_digest: str
    factor_id: str
    manifest_digest: str
    automation_policy_digest: str
    intake_contract_digest: str
    gate1_digest: str
    gate2_digest: str
    gate3_digest: str
    commit_sha: str


@dataclass(frozen=True)
class FactorAutomationEventRequest:
    event_id: str
    workspace_id: str
    event_type: FactorAutomationEventType
    lineage: FactorAutomationLineage
    lifecycle_state: str
    sleeve_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FactorAutomationEventReceipt:
    event_seq: int
    event_day: date
    idempotent_replay: bool


def _valid_id(value: object, *, maximum: int = 256) -> bool:
    return (
        type(value) is str
        and len(value) <= maximum
        and _ID_RE.fullmatch(value) is not None
    )


def _validate(request: FactorAutomationEventRequest) -> None:
    if not _valid_id(request.event_id, maximum=128):
        raise FactorAutomationAuthorityError("invalid_event_id")
    if not _valid_id(request.workspace_id, maximum=128):
        raise FactorAutomationAuthorityError("invalid_workspace_id")
    if request.event_type not in _EVENT_TYPES:
        raise FactorAutomationAuthorityError("invalid_event_type")
    if not _valid_id(request.lifecycle_state):
        raise FactorAutomationAuthorityError("invalid_lifecycle_state")
    lineage = request.lineage
    for name in ("automation_id", "candidate_id", "factor_id"):
        if not _valid_id(getattr(lineage, name)):
            raise FactorAutomationAuthorityError(f"invalid_{name}")
    for name in (
        "candidate_digest",
        "manifest_digest",
        "automation_policy_digest",
        "intake_contract_digest",
        "gate1_digest",
        "gate2_digest",
        "gate3_digest",
    ):
        value = getattr(lineage, name)
        if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
            raise FactorAutomationAuthorityError(f"invalid_{name}")
    if _COMMIT_RE.fullmatch(lineage.commit_sha) is None:
        raise FactorAutomationAuthorityError("invalid_commit_sha")
    if request.event_type == "promotion_committed":
        if request.sleeve_id is not None:
            raise FactorAutomationAuthorityError("promotion_sleeve_must_be_empty")
    elif not _valid_id(request.sleeve_id):
        raise FactorAutomationAuthorityError("invalid_sleeve_id")
    if not isinstance(request.details, Mapping):
        raise FactorAutomationAuthorityError("invalid_details")


def factor_automation_schema_is_ready(settings: Settings) -> bool:
    database = get_database(settings)
    if database is None:
        return False
    try:
        with database.connect() as conn:
            return conn.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM quant_system.factor_automation_events_meta
                    WHERE singleton IS TRUE AND schema_version = 1
                )
                AND to_regprocedure(
                    'quant_system.append_factor_automation_event(text,uuid,text,text,text,text,text,text,text,text,text,text,text,text,text,text,text,jsonb)'
                ) IS NOT NULL
                """
            ).fetchone() == (True,)
    except Exception:
        return False


def append_factor_automation_event(
    settings: Settings,
    request: FactorAutomationEventRequest,
) -> FactorAutomationEventReceipt:
    _validate(request)
    database = get_database(settings)
    if database is None:
        raise FactorAutomationAuthorityUnavailable("database_unavailable")
    lineage = request.lineage
    try:
        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM quant_system.append_factor_automation_event(
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    request.event_id,
                    ROOT_USER_ID,
                    request.workspace_id,
                    request.event_type,
                    lineage.automation_id,
                    lineage.candidate_id,
                    lineage.candidate_digest,
                    lineage.factor_id,
                    lineage.manifest_digest,
                    lineage.automation_policy_digest,
                    lineage.intake_contract_digest,
                    lineage.gate1_digest,
                    lineage.gate2_digest,
                    lineage.gate3_digest,
                    lineage.commit_sha,
                    request.sleeve_id,
                    request.lifecycle_state,
                    Jsonb(dict(request.details)),
                ),
            ).fetchone()
    except DatabaseUnavailable as exc:
        raise FactorAutomationAuthorityUnavailable("database_unavailable") from exc
    except Exception as exc:
        message = str(exc).casefold()
        if "daily quota" in message:
            code = (
                "promotion_daily_quota"
                if request.event_type == "promotion_committed"
                else "demote_daily_quota"
            )
            raise FactorAutomationAuthorityConflict(code) from exc
        if "lineage" in message:
            raise FactorAutomationAuthorityConflict("lineage_missing") from exc
        if "idempotency" in message or "unique" in message:
            raise FactorAutomationAuthorityConflict("idempotency_conflict") from exc
        raise FactorAutomationAuthorityUnavailable("authority_write_failed") from exc
    if (
        row is None
        or type(row[0]) is not int
        or not isinstance(row[1], date)
        or type(row[2]) is not bool
    ):
        raise FactorAutomationAuthorityUnavailable("authority_receipt_invalid")
    return FactorAutomationEventReceipt(
        event_seq=row[0],
        event_day=row[1],
        idempotent_replay=row[2],
    )


__all__ = [
    "FactorAutomationAuthorityConflict",
    "FactorAutomationAuthorityError",
    "FactorAutomationAuthorityUnavailable",
    "FactorAutomationEventReceipt",
    "FactorAutomationEventRequest",
    "FactorAutomationEventType",
    "FactorAutomationLineage",
    "append_factor_automation_event",
    "factor_automation_schema_is_ready",
]
