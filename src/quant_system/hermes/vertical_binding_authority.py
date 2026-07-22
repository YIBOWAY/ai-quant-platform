"""V7g-A-M1: hermetic Vertical A (options research) binding authority.

End-to-end hermetic chain for Plan 纵切 A without live Futu:

  NL goal -> durable action receipt -> Task/Attempt/Run
  -> fixture typed options result (V7f shape) -> exact links
  -> completed | completed_degraded

Zero live provider quotes. Zero orders/account mutation. Hermetic ≠ live
HQA Task final authority. Public write stays OFF.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Literal

from quant_system.hermes.result_surface_authority import (
    ResultSurfaceAuthority,
    TypedResultRecord,
    default_result_surface_authority,
)

VerticalTerminal = Literal["completed", "completed_degraded", "running", "failed"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class VerticalBindingAuthorityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt_public(value: datetime | str | None = None) -> str:
    if isinstance(value, str) and value:
        return value
    dt = value if isinstance(value, datetime) else _utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _validate_id(value: str, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise VerticalBindingAuthorityError(
            "validation", f"{field} must be a bounded identifier"
        )
    return value


def _bounded_text(value: str, field: str, *, max_len: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > max_len:
        raise VerticalBindingAuthorityError(
            "validation", f"{field} must be bounded nonempty text"
        )
    cleaned = value.strip()
    if any(ord(ch) < 9 or (13 < ord(ch) < 32) for ch in cleaned):
        raise VerticalBindingAuthorityError(
            "validation", f"{field} contains control characters"
        )
    return cleaned


def _optional_number(value: object, field: str) -> float | int:
    if type(value) is bool or value is None:
        raise VerticalBindingAuthorityError("validation", f"{field} must be a number")
    if type(value) is int:
        return value
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise VerticalBindingAuthorityError(
                "validation", f"{field} must be a finite number"
            )
        return value
    raise VerticalBindingAuthorityError("validation", f"{field} must be a number")


def _stable_id(prefix: str, digest: str, salt: str) -> str:
    h = hashlib.sha256(f"{digest}:{salt}".encode()).hexdigest()[:20]
    return f"{prefix}-{h}"


@dataclass
class VerticalTaskRecord:
    workspace_id: str
    task_id: str
    kind: str
    status: VerticalTerminal
    display_title: str
    goal_note: str
    ticker: str
    attempt_id: str
    run_id: str
    result_id: str | None
    client_action_id: str
    action_digest: str
    occurred_at: str
    terminal_reason: str | None = None
    provider_evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "task_id": self.task_id,
            "id": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "display_title": self.display_title,
            "goal_note": self.goal_note,
            "ticker": self.ticker,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "client_action_id": self.client_action_id,
            "action_digest": self.action_digest,
            "occurred_at": self.occurred_at,
            "vertical": "options_a",
        }
        if self.result_id is not None:
            payload["result_id"] = self.result_id
        if self.terminal_reason is not None:
            payload["terminal_reason"] = self.terminal_reason
        if self.provider_evidence:
            payload["provider_evidence"] = list(self.provider_evidence)
        if self.limitations:
            payload["limitations"] = list(self.limitations)
        return payload


@dataclass
class VerticalAttemptRecord:
    workspace_id: str
    attempt_id: str
    task_id: str
    run_id: str
    status: VerticalTerminal
    occurred_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "id": self.attempt_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "status": self.status,
            "occurred_at": self.occurred_at,
            "vertical": "options_a",
        }


@dataclass
class VerticalRunRecord:
    workspace_id: str
    run_id: str
    task_id: str
    attempt_id: str
    status: VerticalTerminal
    occurred_at: str
    mode: str = "hermetic_fixture"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "id": self.run_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "mode": self.mode,
            "occurred_at": self.occurred_at,
            "vertical": "options_a",
        }


@dataclass
class VerticalBindOutcome:
    task: VerticalTaskRecord
    attempt: VerticalAttemptRecord
    run: VerticalRunRecord
    result: TypedResultRecord
    terminal: VerticalTerminal


class VerticalBindingAuthority:
    """Thread-safe hermetic Vertical A binding store."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._tasks: dict[tuple[str, str], VerticalTaskRecord] = {}
        self._attempts: dict[tuple[str, str], VerticalAttemptRecord] = {}
        self._runs: dict[tuple[str, str], VerticalRunRecord] = {}
        # Idempotency: (workspace_id, client_action_id) -> task_id
        self._by_action: dict[tuple[str, str], str] = {}
        # Digest conflict detection: (workspace_id, client_action_id) -> digest
        self._action_digest: dict[tuple[str, str], str] = {}

    def reset(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._attempts.clear()
            self._runs.clear()
            self._by_action.clear()
            self._action_digest.clear()

    def bind_options_vertical_a(
        self,
        *,
        workspace_id: str,
        client_action_id: str,
        action_digest: str,
        ticker: str,
        goal_note: str,
        expiry: str,
        strike: float | int,
        bid: float | int,
        ask: float | int,
        delta: float | int,
        iv: float | int,
        apr: float | int,
        include_provider_evidence: bool = True,
        result_authority: ResultSurfaceAuthority | None = None,
    ) -> VerticalBindOutcome:
        """Bind NL options research goal → Task/Attempt/Run → typed result.

        completed when fixture provider_evidence present;
        completed_degraded when evidence intentionally omitted (still no live call).

        Race safety: binder lock is held across digest CAS + result seed + row
        store so a losing concurrent bind cannot leave an orphan typed result.
        """
        ws = _validate_id(workspace_id, "workspace_id")
        act = _validate_id(client_action_id, "client_action_id")
        if type(action_digest) is not str or len(action_digest) != 64:
            raise VerticalBindingAuthorityError(
                "validation", "action_digest must be 64-hex"
            )
        tkr = _bounded_text(ticker, "ticker", max_len=32).upper()
        goal = _bounded_text(goal_note, "goal_note", max_len=1000)
        exp = _bounded_text(expiry, "expiry", max_len=32)
        strike_n = _optional_number(strike, "strike")
        bid_n = _optional_number(bid, "bid")
        ask_n = _optional_number(ask, "ask")
        delta_n = _optional_number(delta, "delta")
        iv_n = _optional_number(iv, "iv")
        apr_n = _optional_number(apr, "apr")
        if type(include_provider_evidence) is not bool:
            raise VerticalBindingAuthorityError(
                "validation", "include_provider_evidence must be a boolean"
            )

        key = (ws, act)
        rauth = result_authority or default_result_surface_authority()

        with self._lock:
            prior_digest = self._action_digest.get(key)
            if prior_digest is not None and prior_digest != action_digest:
                raise VerticalBindingAuthorityError(
                    "conflict",
                    "client_action_id already bound to a different action_digest",
                )
            prior_task_id = self._by_action.get(key)
            if prior_task_id is not None:
                task = self._tasks[(ws, prior_task_id)]
                attempt = self._attempts[(ws, task.attempt_id)]
                run = self._runs[(ws, task.run_id)]
                result = rauth.get(ws, task.result_id or "")
                if result is None:
                    raise VerticalBindingAuthorityError(
                        "internal", "idempotent replay missing result"
                    )
                return VerticalBindOutcome(
                    task=task,
                    attempt=attempt,
                    run=run,
                    result=result,
                    terminal=task.status,  # type: ignore[arg-type]
                )

            task_id = _stable_id("task", action_digest, "task")
            attempt_id = _stable_id("attempt", action_digest, "attempt")
            run_id = _stable_id("run", action_digest, "run")
            result_id = _stable_id("result", action_digest, "result")
            ts = _dt_public()

            if include_provider_evidence:
                terminal: VerticalTerminal = "completed"
                evidence = ("hermetic_fixture_apr", "hermetic_options_chain")
                terminal_reason = "fixture_provider_evidence_present"
                limitations = (
                    "hermetic_fixture",
                    "not_live_futu_quote",
                    "not_tradeable",
                    "zero_orders",
                )
            else:
                terminal = "completed_degraded"
                evidence = ()
                terminal_reason = "provider_evidence_missing"
                limitations = (
                    "hermetic_fixture",
                    "not_live_futu_quote",
                    "not_tradeable",
                    "zero_orders",
                    "unverified_without_provider_evidence",
                )

            # Seed under binder lock so conflict cannot publish unbound results.
            # Always sample — hermetic fixture, never claim REAL live quote.
            try:
                result = rauth.seed_result(
                    workspace_id=ws,
                    result_id=result_id,
                    kind="options_vertical_a",
                    display_title=f"{tkr} sell-put research ({terminal})",
                    status=terminal,
                    sample_or_real="sample",
                    freshness="fresh" if include_provider_evidence else "unknown",
                    read_status=(
                        "available" if include_provider_evidence else "degraded"
                    ),
                    summary=goal,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    run_id=run_id,
                    command_id=None,
                    ticker=tkr,
                    expiry=exp,
                    strike=strike_n,
                    bid=bid_n,
                    ask=ask_n,
                    delta=delta_n,
                    iv=iv_n,
                    apr=apr_n,
                    provider_evidence=evidence,
                    filters=("delta_band", "dte_window", "sell_put_research"),
                    exclusions=("earnings_week",),
                    limitations=limitations,
                    source="hermetic_vertical_a_binding",
                    authority="hermetic_vertical_binding_authority",
                )
            except Exception:
                # Never leave half-written binder state (we have not stored yet).
                raise

            task = VerticalTaskRecord(
                workspace_id=ws,
                task_id=task_id,
                kind="options_vertical_a_research",
                status=terminal,
                display_title=f"Research {tkr} sell put",
                goal_note=goal,
                ticker=tkr,
                attempt_id=attempt_id,
                run_id=run_id,
                result_id=result_id,
                client_action_id=act,
                action_digest=action_digest,
                occurred_at=ts,
                terminal_reason=terminal_reason,
                provider_evidence=evidence,
                limitations=limitations,
            )
            attempt = VerticalAttemptRecord(
                workspace_id=ws,
                attempt_id=attempt_id,
                task_id=task_id,
                run_id=run_id,
                status=terminal,
                occurred_at=ts,
            )
            run = VerticalRunRecord(
                workspace_id=ws,
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                status=terminal,
                occurred_at=ts,
                mode="hermetic_fixture",
            )

            self._tasks[(ws, task_id)] = task
            self._attempts[(ws, attempt_id)] = attempt
            self._runs[(ws, run_id)] = run
            self._by_action[key] = task_id
            self._action_digest[key] = action_digest

            return VerticalBindOutcome(
                task=task,
                attempt=attempt,
                run=run,
                result=result,
                terminal=terminal,
            )

    def list_tasks(self, workspace_id: str, *, limit: int = 50) -> list[VerticalTaskRecord]:
        lim = limit if type(limit) is int and limit > 0 else 50
        with self._lock:
            rows = [t for (ws, _), t in self._tasks.items() if ws == workspace_id]
        rows.sort(key=lambda r: (r.occurred_at, r.task_id), reverse=True)
        return rows[:lim]

    def list_attempts(
        self, workspace_id: str, *, limit: int = 50
    ) -> list[VerticalAttemptRecord]:
        lim = limit if type(limit) is int and limit > 0 else 50
        with self._lock:
            rows = [t for (ws, _), t in self._attempts.items() if ws == workspace_id]
        rows.sort(key=lambda r: (r.occurred_at, r.attempt_id), reverse=True)
        return rows[:lim]

    def list_runs(self, workspace_id: str, *, limit: int = 50) -> list[VerticalRunRecord]:
        lim = limit if type(limit) is int and limit > 0 else 50
        with self._lock:
            rows = [t for (ws, _), t in self._runs.items() if ws == workspace_id]
        rows.sort(key=lambda r: (r.occurred_at, r.run_id), reverse=True)
        return rows[:lim]


_DEFAULT = VerticalBindingAuthority()


def default_vertical_binding_authority() -> VerticalBindingAuthority:
    return _DEFAULT


def reset_default_vertical_binding_authority() -> None:
    _DEFAULT.reset()


__all__ = [
    "VerticalBindOutcome",
    "VerticalBindingAuthority",
    "VerticalBindingAuthorityError",
    "VerticalTaskRecord",
    "VerticalAttemptRecord",
    "VerticalRunRecord",
    "default_vertical_binding_authority",
    "reset_default_vertical_binding_authority",
]
