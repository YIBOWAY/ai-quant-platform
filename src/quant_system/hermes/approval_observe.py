"""V7d-Durable-Approval-Projector-M1: hermetic approval → workspace observe.

Projects real Hermes command-approval challenges (pending + recent decided)
into the durable workspace snapshot/follow surface from the in-process V7a/V7b
authorities. Empty remains honest. Never invents Gate 1/2/3 rows, Task/Attempt
rows, always-allow, or live HTTP Hermes facts.

This is **not** a second private FE poll: snapshot + L4b follow/SSE carry the
projection. Process-global journal is hermetic M1 (same class as V7a/V7b
authorities); a later slice may bind a PG-backed store without changing the
public browser shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal, Mapping

from quant_system.hermes.command_approval_authority import (
    ApprovalChallenge,
    CommandApprovalAuthority,
    default_command_approval_authority,
)

ApprovalEventType = Literal[
    "approval.raised",
    "approval.decided",
    "approval.expired",
]

_PUBLIC_STATUSES = frozenset(
    {"pending", "allowed_once", "denied", "expired"}
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_public(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if type(value) is str and value:
        return value
    return None


def project_approval_public(row: Mapping[str, Any] | ApprovalChallenge) -> dict[str, object]:
    """Browser-safe approval projection (pending or decided).

    Decided rows include ``decision`` / ``decided_at`` when known. Never includes
    Gate fields or always-allow.
    """
    if isinstance(row, ApprovalChallenge):
        base = row.to_public_dict()
        if row.decision is not None:
            base["decision"] = row.decision
        if row.decided_at is not None:
            base["decided_at"] = row.decided_at
        return base

    status = row.get("status") or row.get("expected_status") or "pending"
    status_s = str(status) if status is not None else "pending"
    if status_s not in _PUBLIC_STATUSES:
        status_s = "pending"
    payload: dict[str, object] = {
        "approval_id": str(row["approval_id"]),
        "run_id": None if row.get("run_id") is None else str(row["run_id"]),
        "command_id": (
            None if row.get("command_id") is None else str(row["command_id"])
        ),
        "digest": None if row.get("digest") is None else str(row["digest"]),
        "expires_at": _dt_public(row.get("expires_at")),  # type: ignore[arg-type]
        "expected_status": (
            "pending" if status_s == "pending" else status_s
        ),
        "status": status_s,
        "kind": str(row.get("kind") or "hermes.command_approval"),
    }
    decision = row.get("decision")
    if decision in ("allow_once", "deny"):
        payload["decision"] = decision
    decided_at = row.get("decided_at")
    if decided_at is not None:
        payload["decided_at"] = _dt_public(decided_at)  # type: ignore[arg-type]
    return payload


def project_approval_event_public(
    *,
    event_seq: int,
    event_type: str,
    approval: Mapping[str, Any],
    occurred_at: str | None = None,
) -> dict[str, object]:
    """Browser-safe follow event for an approval lifecycle change."""
    row = project_approval_public(approval)
    return {
        "event_id": int(event_seq),
        "type": str(event_type),
        "event_type": str(event_type),
        # Approval events are not command lifecycle; keep command_id nullable.
        "command_id": row.get("command_id") or "",
        "approval_id": row.get("approval_id"),
        "run_id": row.get("run_id"),
        "digest": row.get("digest"),
        "status": row.get("status"),
        "decision": row.get("decision"),
        "expires_at": row.get("expires_at"),
        "kind": row.get("kind"),
        "occurred_at": occurred_at or _utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "approval": row,
    }


def project_workspace_approvals(
    workspace_id: str,
    *,
    authority: CommandApprovalAuthority | None = None,
    decided_limit: int = 20,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Pending first (CAS-complete), then recent decided facts. Empty is honest."""
    auth = authority or default_command_approval_authority()
    limit = decided_limit if type(decided_limit) is int and decided_limit > 0 else 20
    rows = auth.list_observed(
        workspace_id, decided_limit=limit, now=now
    )
    return [project_approval_public(r) for r in rows]


@dataclass
class _JournalEvent:
    seq: int
    workspace_id: str
    event_type: str
    approval: dict[str, object]
    occurred_at: str


class ApprovalObserveJournal:
    """Hermetic append-only approval lifecycle journal (per workspace seq).

    Used so L4b follow/SSE can surface approval deltas without a second FE poll
    and without inventing PG command_event rows. Seq is workspace-local and is
    **not** the durable command event_id cursor.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._events: list[_JournalEvent] = []
        self._heads: dict[str, int] = {}
        # fingerprint of last projected approvals list per workspace (for SSE)
        self._last_fp: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._heads.clear()
            self._last_fp.clear()

    def append(
        self,
        *,
        workspace_id: str,
        event_type: ApprovalEventType | str,
        approval: Mapping[str, Any] | ApprovalChallenge,
        occurred_at: datetime | str | None = None,
    ) -> dict[str, object]:
        if type(workspace_id) is not str or not workspace_id:
            raise ValueError("workspace_id required")
        public = project_approval_public(approval)
        ts = _dt_public(occurred_at) or _utc_now().strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        with self._lock:
            seq = self._heads.get(workspace_id, 0) + 1
            self._heads[workspace_id] = seq
            ev = _JournalEvent(
                seq=seq,
                workspace_id=workspace_id,
                event_type=str(event_type),
                approval=public,
                occurred_at=ts,
            )
            self._events.append(ev)
            # Invalidate fingerprint so next follow/SSE re-emits approvals.
            self._last_fp.pop(workspace_id, None)
        return project_approval_event_public(
            event_seq=seq,
            event_type=str(event_type),
            approval=public,
            occurred_at=ts,
        )

    def head(self, workspace_id: str) -> int:
        with self._lock:
            return int(self._heads.get(workspace_id, 0))

    def events_after(
        self, workspace_id: str, *, after_seq: int, limit: int = 100
    ) -> list[dict[str, object]]:
        if type(after_seq) is not int or after_seq < 0:
            after_seq = 0
        page_limit = limit if type(limit) is int and 1 <= limit <= 200 else 100
        with self._lock:
            rows = [
                e
                for e in self._events
                if e.workspace_id == workspace_id and e.seq > after_seq
            ]
            rows = rows[:page_limit]
        return [
            project_approval_event_public(
                event_seq=e.seq,
                event_type=e.event_type,
                approval=e.approval,
                occurred_at=e.occurred_at,
            )
            for e in rows
        ]

    def approvals_fingerprint(self, workspace_id: str, approvals: list[dict[str, object]]) -> str:
        """Stable fingerprint so SSE only emits when projection changes."""
        parts: list[str] = []
        for row in approvals:
            parts.append(
                f"{row.get('approval_id')}:{row.get('status')}:{row.get('decision')}:{row.get('expires_at')}"
            )
        return "|".join(parts)

    def take_approvals_if_changed(
        self, workspace_id: str, approvals: list[dict[str, object]]
    ) -> list[dict[str, object]] | None:
        fp = self.approvals_fingerprint(workspace_id, approvals)
        with self._lock:
            prior = self._last_fp.get(workspace_id)
            if prior == fp:
                return None
            self._last_fp[workspace_id] = fp
            return list(approvals)


_DEFAULT_JOURNAL = ApprovalObserveJournal()


def default_approval_observe_journal() -> ApprovalObserveJournal:
    return _DEFAULT_JOURNAL


def reset_default_approval_observe_journal() -> None:
    _DEFAULT_JOURNAL.reset()


def note_approval_raised(
    *,
    workspace_id: str,
    approval: Mapping[str, Any] | ApprovalChallenge,
) -> dict[str, object]:
    return default_approval_observe_journal().append(
        workspace_id=workspace_id,
        event_type="approval.raised",
        approval=approval,
    )


def note_approval_decided(
    *,
    workspace_id: str,
    approval: Mapping[str, Any] | ApprovalChallenge,
) -> dict[str, object]:
    return default_approval_observe_journal().append(
        workspace_id=workspace_id,
        event_type="approval.decided",
        approval=approval,
    )


__all__ = [
    "ApprovalObserveJournal",
    "default_approval_observe_journal",
    "note_approval_decided",
    "note_approval_raised",
    "project_approval_event_public",
    "project_approval_public",
    "project_workspace_approvals",
    "reset_default_approval_observe_journal",
]
