"""Hermetic Hermes Run stop port (V7c-M1).

Mirrors HQA ``HermesRunPort.stop`` / ``StopResult`` semantics without importing
``hqa``. The submission saga accepts typed ``run.stop.request`` actions, calls
:meth:`FakeHermesRunStopAdapter.stop`, and builds the plan §5.5 layered stop
receipt (Hermes Run real; Attempt/job honest not_applicable|unknown).

This is **not** live HTTP Hermes stop, **not** Task-level invention of stopped
state from a single run, **not** Gate mutation, and **not** a public write path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Literal, Mapping
import re
import time

RunStatus = Literal[
    "accepted",
    "running",
    "succeeded",
    "failed",
    "stopped",
]
LayerStatus = Literal[
    "requested",
    "confirmed",
    "already_terminal",
    "unknown",
    "not_applicable",
]
OverallStopStatus = Literal[
    "requested",
    "reconciling",
    "stopped",
    "already_terminal",
]

_TERMINAL = frozenset({"succeeded", "failed", "stopped"})
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_RUN_REF_PREFIX = "run:"


class RunStopError(RuntimeError):
    """Typed stop failure with a stable reason_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class StopResult:
    run_id: str
    status: str
    idempotent_replay: bool = False

    def to_public_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "idempotent_replay": self.idempotent_replay,
        }


@dataclass(frozen=True)
class LayeredStopReceipt:
    """Plan §5.5 layered stop observation (M1 hermetic)."""

    hermes_run: LayerStatus
    hqa_attempt: LayerStatus
    platform_job: LayerStatus
    overall: OverallStopStatus
    run_id: str | None = None
    run_status: str | None = None
    idempotent_replay: bool = False

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "hermes_run": self.hermes_run,
            "hqa_attempt": self.hqa_attempt,
            "platform_job": self.platform_job,
            "overall": self.overall,
            "idempotent_replay": self.idempotent_replay,
        }
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.run_status is not None:
            payload["run_status"] = self.run_status
        return payload


@dataclass
class _StopEvent:
    seq: int
    event_type: str
    run_id: str
    payload: dict[str, object] = field(default_factory=dict)


@dataclass
class _RunRecord:
    run_id: str
    status: str
    updated_at: float = field(default_factory=time.time)


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise RunStopError("validation", f"{field} must be a bounded identifier")
    return value


def strip_run_ref(run_ref: str) -> str:
    """Extract bare run_id from a ``run:…`` workspace ref."""
    if (
        type(run_ref) is not str
        or not run_ref.startswith(_RUN_REF_PREFIX)
        or len(run_ref) == len(_RUN_REF_PREFIX)
        or _ID.fullmatch(run_ref) is None
    ):
        raise RunStopError(
            "validation", "run_ref must be a bounded run: reference"
        )
    return run_ref[len(_RUN_REF_PREFIX) :]


def classify_optional_layer(ref: str | None) -> LayerStatus:
    """M1 honesty: absent ref → not_applicable; present without authority → unknown."""
    if ref is None:
        return "not_applicable"
    return "unknown"


def build_layered_stop_receipt(
    *,
    stop: StopResult | None,
    hermes_run_layer: LayerStatus,
    attempt_ref: str | None,
    platform_job_ref: str | None,
    transport_unknown: bool = False,
) -> LayeredStopReceipt:
    """Compose plan §5.5 layers. Never invent Attempt/job confirmed from run alone."""
    attempt_layer = classify_optional_layer(attempt_ref)
    job_layer = classify_optional_layer(platform_job_ref)

    if transport_unknown or hermes_run_layer == "unknown":
        overall: OverallStopStatus = "reconciling"
    elif hermes_run_layer == "requested":
        overall = "requested"
    elif attempt_layer == "unknown" or job_layer == "unknown":
        # Run may be terminal, but an artifact-producing target is still unknown.
        overall = "reconciling"
    elif hermes_run_layer == "already_terminal":
        overall = "already_terminal"
    elif hermes_run_layer == "confirmed":
        overall = "stopped"
    else:
        overall = "reconciling"

    return LayeredStopReceipt(
        hermes_run=hermes_run_layer,
        hqa_attempt=attempt_layer,
        platform_job=job_layer,
        overall=overall,
        run_id=None if stop is None else stop.run_id,
        run_status=None if stop is None else stop.status,
        idempotent_replay=False if stop is None else stop.idempotent_replay,
    )


class FakeHermesRunStopAdapter:
    """In-process stop double matching HQA fake stop semantics.

    Scripting hooks (not a product path):
    * :meth:`ensure_run` / :meth:`set_status` seed lifecycle
    * ``next_fault``: ``None`` | ``"unavailable"`` | ``"run_not_found"`` | ``"partial_stop"``
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[str, _RunRecord] = {}
        self._events: dict[str, list[_StopEvent]] = {}
        # (workspace_id, client_action_id) → action_digest for request identity.
        self._requests: dict[tuple[str, str], str] = {}
        self.next_fault: str | None = None
        self.stop_calls: int = 0

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()
            self._events.clear()
            self._requests.clear()
            self.next_fault = None
            self.stop_calls = 0

    def ensure_run(
        self, run_id: str, *, status: str = "running"
    ) -> str:
        rid = _validate_id(run_id, "run_id")
        if type(status) is not str or not status:
            raise RunStopError("validation", "status must be a non-empty string")
        with self._lock:
            existing = self._runs.get(rid)
            if existing is None:
                self._runs[rid] = _RunRecord(run_id=rid, status=status)
                self._events.setdefault(rid, [])
            return rid

    def set_status(self, run_id: str, status: str) -> None:
        rid = _validate_id(run_id, "run_id")
        if type(status) is not str or not status:
            raise RunStopError("validation", "status must be a non-empty string")
        with self._lock:
            record = self._runs.get(rid)
            if record is None:
                raise RunStopError("run_not_found", f"Run not found: {rid}")
            if record.status in _TERMINAL:
                return
            record.status = status
            record.updated_at = time.time()

    def get_status(self, run_id: str) -> str:
        rid = _validate_id(run_id, "run_id")
        with self._lock:
            record = self._runs.get(rid)
            if record is None:
                raise RunStopError("run_not_found", f"Run not found: {rid}")
            return record.status

    def events(self, run_id: str) -> list[dict[str, object]]:
        rid = _validate_id(run_id, "run_id")
        with self._lock:
            rows = list(self._events.get(rid, ()))
        return [
            {
                "seq": e.seq,
                "event_type": e.event_type,
                "run_id": e.run_id,
                "payload": dict(e.payload),
            }
            for e in rows
        ]

    def remember_request(
        self,
        *,
        workspace_id: str,
        client_action_id: str,
        action_digest: str,
    ) -> Literal["new", "replay", "conflict"]:
        """Track stop request identity (client_action_id + digest)."""
        ws = _validate_id(workspace_id, "workspace_id")
        cid = _validate_id(client_action_id, "client_action_id")
        if type(action_digest) is not str or len(action_digest) != 64:
            raise RunStopError(
                "validation", "action_digest must be a lowercase SHA-256 digest"
            )
        key = (ws, cid)
        with self._lock:
            prior = self._requests.get(key)
            if prior is None:
                self._requests[key] = action_digest
                return "new"
            if prior == action_digest:
                return "replay"
            return "conflict"

    def _append_event_unlocked(
        self, run_id: str, event_type: str, payload: Mapping[str, object]
    ) -> None:
        bucket = self._events.setdefault(run_id, [])
        seq = (bucket[-1].seq + 1) if bucket else 1
        bucket.append(
            _StopEvent(
                seq=seq,
                event_type=event_type,
                run_id=run_id,
                payload=dict(payload),
            )
        )

    def stop(self, run_id: str) -> StopResult:
        """Atomically commit one cancellation or identify a terminal replay.

        Terminal-honest: already ``succeeded``/``failed``/``stopped`` returns
        the actual status with ``idempotent_replay=True`` (never coerce → stopped).
        ``partial_stop`` fault models committed-but-ack-lost transport error.
        """
        rid = _validate_id(run_id, "run_id")
        with self._lock:
            self.stop_calls += 1
            fault = self.next_fault
            self.next_fault = None

            if fault == "unavailable":
                raise RunStopError(
                    "stop_unavailable", "Run stop port unavailable"
                )
            record = self._runs.get(rid)
            if fault == "run_not_found" or record is None:
                raise RunStopError("run_not_found", f"Run not found: {rid}")

            if record.status in _TERMINAL:
                return StopResult(
                    run_id=rid,
                    status=record.status,
                    idempotent_replay=True,
                )

            self._append_event_unlocked(rid, "run.cancelled", {})
            record.status = "stopped"
            record.updated_at = time.time()
            result = StopResult(run_id=rid, status="stopped", idempotent_replay=False)

            if fault == "partial_stop":
                # Durable commit succeeded; acknowledgement lost. Caller must
                # classify as unknown/reconciling and heal on replay by run id.
                raise RunStopError(
                    "transport_error",
                    "stop committed but acknowledgement was lost",
                )
            return result


_DEFAULT_STOP = FakeHermesRunStopAdapter()


def default_run_stop_adapter() -> FakeHermesRunStopAdapter:
    return _DEFAULT_STOP


def reset_default_run_stop_adapter() -> None:
    _DEFAULT_STOP.reset()


__all__ = [
    "FakeHermesRunStopAdapter",
    "LayeredStopReceipt",
    "RunStopError",
    "StopResult",
    "build_layered_stop_receipt",
    "classify_optional_layer",
    "default_run_stop_adapter",
    "reset_default_run_stop_adapter",
    "strip_run_ref",
]
