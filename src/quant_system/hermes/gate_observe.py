"""V7e-Gate-Surfaces-M1: hermetic Gate 1/2/3 → workspace observe.

Projects real Domain Gate challenges (pending + recent decided/prepared) into
the durable workspace snapshot/follow surface from the in-process V7e authority.
Empty remains honest. Never invents command-approval rows, Task/Attempt rows,
always-allow, or live HTTP Hermes facts.

Separate from V7d approval projector:
* ``gates[]`` (not ``approvals[]``)
* SSE ``event: gates`` (not ``event: approvals``)
* fingerprint / journal namespace is independent
* ``authority_health.gate_1|gate_2|gate_3``
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Literal

from quant_system.hermes.gate_surface_authority import (
    GateChallenge,
    GateSurfaceAuthority,
    default_gate_surface_authority,
)

GateEventType = Literal[
    "gate.raised",
    "gate.decided",
    "gate.prepared",
    "gate.expired",
]

_PUBLIC_STATUSES = frozenset(
    {"pending", "confirmed", "reviewed", "prepared", "rejected", "expired"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt_public(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if type(value) is str and value:
        return value
    return None


def project_gate_public(row: Mapping[str, Any] | GateChallenge) -> dict[str, object]:
    """Browser-safe Gate projection (pending or decided/prepared)."""
    if isinstance(row, GateChallenge):
        return row.to_public_dict()

    status = row.get("status") or row.get("expected_status") or "pending"
    status_s = str(status) if status is not None else "pending"
    if status_s not in _PUBLIC_STATUSES:
        status_s = "pending"
    gate_kind = str(row.get("gate_kind") or "gate1")
    if gate_kind not in ("gate1", "gate2", "gate3"):
        gate_kind = "gate1"
    kind_default = {
        "gate1": "gate1.formula_source",
        "gate2": "gate2.candidate",
        "gate3": "gate3.promotion_review",
    }[gate_kind]
    payload: dict[str, object] = {
        "gate_id": str(row["gate_id"]),
        "gate_kind": gate_kind,
        "kind": str(row.get("kind") or kind_default),
        "status": status_s,
        "expected_status": "pending" if status_s == "pending" else status_s,
    }
    for key in (
        "task_id",
        "task_ref",
        "reviewed_source_sha256",
        "candidate_id",
        "candidate_ref",
        "expected_digest",
        "final_backtest_receipt_id",
        "final_backtest_receipt_ref",
        "base_commit",
        "note",
    ):
        if row.get(key) is not None:
            payload[key] = row[key]
    if row.get("expires_at") is not None:
        payload["expires_at"] = _dt_public(row.get("expires_at"))  # type: ignore[arg-type]
    if row.get("decided_at") is not None:
        payload["decided_at"] = _dt_public(row.get("decided_at"))  # type: ignore[arg-type]
    return payload


def project_workspace_gates(
    workspace_id: str,
    *,
    authority: GateSurfaceAuthority | None = None,
    decided_limit: int = 20,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Pending first, then recent decided/prepared facts. Empty is honest."""
    auth = authority or default_gate_surface_authority()
    limit = decided_limit if type(decided_limit) is int and decided_limit > 0 else 20
    rows = auth.list_observed(workspace_id, decided_limit=limit, now=now)
    return [project_gate_public(r) for r in rows]


def gate_authority_health() -> dict[str, str]:
    """Hermetic Gate surfaces are mounted; empty lists remain honest."""
    return {
        "gate_1": "ready",
        "gate_2": "ready",
        "gate_3": "ready",
    }


@dataclass
class _JournalEvent:
    seq: int
    workspace_id: str
    event_type: str
    gate: dict[str, object]
    occurred_at: str


class GateObserveJournal:
    """Hermetic append-only Gate lifecycle journal (per workspace seq).

    Used so L4b follow/SSE can surface Gate deltas without a second FE poll and
    without inventing PG command_event rows. Seq is workspace-local and is
    **not** the durable command event_id cursor, and is independent of the
    approval observe journal.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._events: list[_JournalEvent] = []
        self._heads: dict[str, int] = {}
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
        event_type: GateEventType | str,
        gate: Mapping[str, Any] | GateChallenge,
        occurred_at: datetime | str | None = None,
    ) -> dict[str, object]:
        if type(workspace_id) is not str or not workspace_id:
            raise ValueError("workspace_id required")
        public = project_gate_public(gate)
        ts = _dt_public(occurred_at) or _utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self._lock:
            seq = self._heads.get(workspace_id, 0) + 1
            self._heads[workspace_id] = seq
            self._events.append(
                _JournalEvent(
                    seq=seq,
                    workspace_id=workspace_id,
                    event_type=str(event_type),
                    gate=public,
                    occurred_at=ts,
                )
            )
            self._last_fp.pop(workspace_id, None)
        return {
            "event_id": seq,
            "type": str(event_type),
            "event_type": str(event_type),
            "gate_id": public.get("gate_id"),
            "gate_kind": public.get("gate_kind"),
            "status": public.get("status"),
            "occurred_at": ts,
            "gate": public,
        }

    def head(self, workspace_id: str) -> int:
        with self._lock:
            return int(self._heads.get(workspace_id, 0))

    def gates_fingerprint(
        self, workspace_id: str, gates: list[dict[str, object]]
    ) -> str:
        parts: list[str] = []
        for row in gates:
            evidence_digest = row.get("expected_digest") or row.get(
                "reviewed_source_sha256"
            )
            parts.append(
                f"{row.get('gate_id')}:{row.get('gate_kind')}:{row.get('status')}:"
                f"{row.get('decided_at')}:{evidence_digest}"
            )
        return "|".join(parts)

    def take_gates_if_changed(
        self, workspace_id: str, gates: list[dict[str, object]]
    ) -> list[dict[str, object]] | None:
        fp = self.gates_fingerprint(workspace_id, gates)
        with self._lock:
            prior = self._last_fp.get(workspace_id)
            if prior == fp:
                return None
            self._last_fp[workspace_id] = fp
            return list(gates)


_DEFAULT_JOURNAL = GateObserveJournal()


def default_gate_observe_journal() -> GateObserveJournal:
    return _DEFAULT_JOURNAL


def reset_default_gate_observe_journal() -> None:
    _DEFAULT_JOURNAL.reset()


def note_gate_raised(
    *,
    workspace_id: str,
    gate: Mapping[str, Any] | GateChallenge,
) -> dict[str, object]:
    return default_gate_observe_journal().append(
        workspace_id=workspace_id,
        event_type="gate.raised",
        gate=gate,
    )


def note_gate_decided(
    *,
    workspace_id: str,
    gate: Mapping[str, Any] | GateChallenge,
) -> dict[str, object]:
    status = (
        gate.status
        if isinstance(gate, GateChallenge)
        else str((gate or {}).get("status") or "")
    )
    event_type: GateEventType = (
        "gate.prepared" if status == "prepared" else "gate.decided"
    )
    return default_gate_observe_journal().append(
        workspace_id=workspace_id,
        event_type=event_type,
        gate=gate,
    )


__all__ = [
    "GateObserveJournal",
    "default_gate_observe_journal",
    "gate_authority_health",
    "note_gate_decided",
    "note_gate_raised",
    "project_gate_public",
    "project_workspace_gates",
    "reset_default_gate_observe_journal",
]
