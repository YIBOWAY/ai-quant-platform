"""V7f-Typed-Results-M1: hermetic typed results → workspace observe.

Projects real typed result records into the durable workspace snapshot/follow
surface from the in-process V7f authority. Empty remains honest. Never invents
Task/Attempt/Run rows, Gate rows, command-approval rows, or live provider quotes.

Separate namespaces:
* ``results[]`` typed public objects (promoted from L5b bare id strings)
* SSE ``event: results``
* fingerprint / journal independent of approvals/gates
* ``authority_health.result = ready`` when projector mounted
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal, Mapping

from quant_system.hermes.result_surface_authority import (
    ResultSurfaceAuthority,
    TypedResultRecord,
    default_result_surface_authority,
)

ResultEventType = Literal["result.raised", "result.updated", "result.cleared"]

_PUBLIC_MARKS = frozenset({"sample", "real"})
_PUBLIC_FRESHNESS = frozenset({"fresh", "stale", "not_applicable", "unknown"})
_PUBLIC_READ = frozenset(
    {"available", "degraded", "missing", "corrupt", "unavailable"}
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


def project_result_public(
    row: Mapping[str, Any] | TypedResultRecord,
) -> dict[str, object]:
    """Browser-safe typed result projection."""
    if isinstance(row, TypedResultRecord):
        return row.to_public_dict()

    result_id = str(row.get("result_id") or row.get("id") or "")
    if not result_id:
        raise ValueError("result_id required")
    # Fail-closed marks: only exact "real" is real; invalid/missing → sample.
    raw_mark = row.get("sample_or_real")
    if raw_mark is None or raw_mark == "":
        mark = "sample"
    else:
        mark_s = str(raw_mark).lower()
        mark = "real" if mark_s == "real" else "sample"
    freshness = str(row.get("freshness") or "unknown")
    if freshness not in _PUBLIC_FRESHNESS:
        freshness = "unknown"
    # Never invent read_status=available for unknown/invalid Mapping input.
    raw_read = row.get("read_status")
    if raw_read is None or raw_read == "":
        read_status = "unavailable"
    else:
        read_s = str(raw_read)
        read_status = read_s if read_s in _PUBLIC_READ else "unavailable"
    payload: dict[str, object] = {
        "result_id": result_id,
        "id": result_id,
        "kind": str(row.get("kind") or "generic"),
        "display_title": str(row.get("display_title") or result_id),
        "status": str(row.get("status") or "unknown"),
        "sample_or_real": mark,
        "freshness": freshness,
        "read_status": read_status,
        "occurred_at": _dt_public(row.get("occurred_at"))  # type: ignore[arg-type]
        or _utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    for key in (
        "summary",
        "task_id",
        "attempt_id",
        "run_id",
        "artifact_id",
        "command_id",
        "ticker",
        "expiry",
        "strike",
        "bid",
        "ask",
        "delta",
        "iv",
        "apr",
        "detail_href",
        "original_href",
        "source",
        "authority",
        "payload_digest",
    ):
        if row.get(key) is not None:
            payload[key] = row[key]
    for list_key in (
        "provider_evidence",
        "filters",
        "exclusions",
        "limitations",
    ):
        val = row.get(list_key)
        if isinstance(val, list) and val:
            payload[list_key] = list(val)
    if isinstance(row.get("exact_links"), dict):
        payload["exact_links"] = dict(row["exact_links"])  # type: ignore[arg-type]
    else:
        links: dict[str, object] = {}
        for id_key, ref_prefix in (
            ("task_id", "task"),
            ("attempt_id", "attempt"),
            ("run_id", "run"),
            ("artifact_id", "artifact"),
        ):
            if row.get(id_key):
                links[id_key] = row[id_key]
                links[f"{ref_prefix}_ref"] = f"{ref_prefix}:{row[id_key]}"
        if row.get("command_id"):
            links["command_id"] = row["command_id"]
        if links:
            payload["exact_links"] = links
    return payload


def project_workspace_results(
    workspace_id: str,
    *,
    authority: ResultSurfaceAuthority | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    """Newest-first typed results. Empty is honest."""
    auth = authority or default_result_surface_authority()
    lim = limit if type(limit) is int and limit > 0 else 50
    rows = auth.list_observed(workspace_id, limit=lim)
    return [project_result_public(r) for r in rows]


def result_authority_health() -> dict[str, str]:
    """Hermetic typed-result projector is mounted; empty lists remain honest."""
    return {"result": "ready"}


@dataclass
class _JournalEvent:
    seq: int
    workspace_id: str
    event_type: str
    result: dict[str, object]
    occurred_at: str


class ResultObserveJournal:
    """Hermetic append-only result lifecycle journal (per workspace seq).

    Used so L4b follow/SSE can surface result deltas without a second FE poll
    and without inventing PG command_event rows. Seq is workspace-local and is
    **not** the durable command event_id cursor; independent of approval/gate
    journals.
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
        event_type: ResultEventType | str,
        result: Mapping[str, Any] | TypedResultRecord,
        occurred_at: datetime | str | None = None,
    ) -> dict[str, object]:
        if type(workspace_id) is not str or not workspace_id:
            raise ValueError("workspace_id required")
        public = project_result_public(result)
        ts = _dt_public(occurred_at) or _utc_now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self._lock:
            seq = self._heads.get(workspace_id, 0) + 1
            self._heads[workspace_id] = seq
            self._events.append(
                _JournalEvent(
                    seq=seq,
                    workspace_id=workspace_id,
                    event_type=str(event_type),
                    result=public,
                    occurred_at=ts,
                )
            )
            self._last_fp.pop(workspace_id, None)
        return {
            "event_id": seq,
            "type": str(event_type),
            "event_type": str(event_type),
            "result_id": public.get("result_id"),
            "kind": public.get("kind"),
            "sample_or_real": public.get("sample_or_real"),
            "occurred_at": ts,
            "result": public,
        }

    def head(self, workspace_id: str) -> int:
        with self._lock:
            return int(self._heads.get(workspace_id, 0))

    def results_fingerprint(
        self, workspace_id: str, results: list[dict[str, object]]
    ) -> str:
        parts: list[str] = []
        for row in results:
            parts.append(
                f"{row.get('result_id')}:{row.get('kind')}:{row.get('status')}:"
                f"{row.get('sample_or_real')}:{row.get('freshness')}:"
                f"{row.get('payload_digest') or row.get('occurred_at')}"
            )
        return "|".join(parts)

    def take_results_if_changed(
        self, workspace_id: str, results: list[dict[str, object]]
    ) -> list[dict[str, object]] | None:
        fp = self.results_fingerprint(workspace_id, results)
        with self._lock:
            prior = self._last_fp.get(workspace_id)
            if prior == fp:
                return None
            self._last_fp[workspace_id] = fp
            return list(results)


_DEFAULT_JOURNAL = ResultObserveJournal()


def default_result_observe_journal() -> ResultObserveJournal:
    return _DEFAULT_JOURNAL


def reset_default_result_observe_journal() -> None:
    _DEFAULT_JOURNAL.reset()


def note_result_raised(
    *,
    workspace_id: str,
    result: Mapping[str, Any] | TypedResultRecord,
) -> dict[str, object]:
    return default_result_observe_journal().append(
        workspace_id=workspace_id,
        event_type="result.raised",
        result=result,
    )


def note_result_updated(
    *,
    workspace_id: str,
    result: Mapping[str, Any] | TypedResultRecord,
) -> dict[str, object]:
    return default_result_observe_journal().append(
        workspace_id=workspace_id,
        event_type="result.updated",
        result=result,
    )


__all__ = [
    "ResultObserveJournal",
    "default_result_observe_journal",
    "note_result_raised",
    "note_result_updated",
    "project_result_public",
    "project_workspace_results",
    "reset_default_result_observe_journal",
    "result_authority_health",
]
