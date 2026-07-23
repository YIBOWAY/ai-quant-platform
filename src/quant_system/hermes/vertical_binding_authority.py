"""V7g vertical binding authority (A options + B factor).

Vertical A (options):
  M1 hermetic + M2 authorized live Futu RO thin overlay.
  NL goal -> Task/Attempt/Run -> typed options result -> completed|degraded.
  Live path requires auth envelope; real only with verifiable evidence.

Vertical B (factor) — V7g-B-M1 hermetic only:
  NL + paper ref -> Task/Attempt/Run -> typed factor result -> completed|degraded.
  Always sample. Never StartResearch/Confirm/Gate/backtest/Git/live provider.

Zero orders/account mutation. Public write stays OFF.

Race safety: one in-flight owner per (workspace, client_action_id); waiters
join via Condition and idempotent-replay. Grant budget keyed by grant_digest;
only the owner decrements/refunds.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Condition, Lock
from typing import Any, Callable, Literal

from quant_system.hermes.result_surface_authority import (
    ResultSurfaceAuthority,
    TypedResultRecord,
    default_result_surface_authority,
)
from quant_system.hermes.vertical_ro_provider import (
    FutuReadOnlyOptionsFacade,
    VerticalRoProviderError,
    VerticalRoQuote,
)

VerticalTerminal = Literal["completed", "completed_degraded", "running", "failed"]

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REQUIRED_LIVE_FIELDS = frozenset(
    {"bid", "ask", "delta", "iv", "expiry", "strike"}
)


class VerticalBindingAuthorityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_public(value: datetime | str | None = None) -> str:
    if isinstance(value, str) and value:
        return value
    dt = value if isinstance(value, datetime) else _utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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
    h = hashlib.sha256(f"{digest}:{salt}".encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{h}"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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
    provider_mode: str = "hermetic_fixture"
    vertical: str = "options_a"
    # Optional factor-B fields (absent/empty on options_a rows).
    factor_name: str | None = None
    paper_ref: str | None = None
    paper_digest: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "task_id": self.task_id,
            "id": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "display_title": self.display_title,
            "goal_note": self.goal_note,
            "attempt_id": self.attempt_id,
            "run_id": self.run_id,
            "client_action_id": self.client_action_id,
            "action_digest": self.action_digest,
            "occurred_at": self.occurred_at,
            "vertical": self.vertical,
            "provider_mode": self.provider_mode,
        }
        # ticker is options-A specific; omit empty on factor_b for field isolation.
        if self.ticker:
            payload["ticker"] = self.ticker
        if self.factor_name is not None:
            payload["factor_name"] = self.factor_name
        if self.paper_ref is not None:
            payload["paper_ref"] = self.paper_ref
        if self.paper_digest is not None:
            payload["paper_digest"] = self.paper_digest
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
    vertical: str = "options_a"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "id": self.attempt_id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "status": self.status,
            "occurred_at": self.occurred_at,
            "vertical": self.vertical,
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
    vertical: str = "options_a"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "id": self.run_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "status": self.status,
            "mode": self.mode,
            "occurred_at": self.occurred_at,
            "vertical": self.vertical,
        }


@dataclass
class VerticalBindOutcome:
    task: VerticalTaskRecord
    attempt: VerticalAttemptRecord
    run: VerticalRunRecord
    result: TypedResultRecord
    terminal: VerticalTerminal


def _enforce_live_auth_envelope(
    *,
    ticker: str,
    auth_envelope: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail-closed live grant checks. Returns validated envelope dict."""
    if auth_envelope is None:
        raise VerticalBindingAuthorityError(
            "auth_envelope_missing",
            "auth_envelope is required when provider_mode=live_futu_ro",
        )
    if type(auth_envelope) is not dict:
        raise VerticalBindingAuthorityError(
            "auth_envelope_invalid", "auth_envelope must be an object"
        )
    env = dict(auth_envelope)
    tickers = env.get("tickers") or []
    if type(tickers) is not list or ticker.upper() not in {
        str(t).upper() for t in tickers
    }:
        raise VerticalBindingAuthorityError(
            "auth_envelope_denied",
            "ticker_not_in_grant",
        )
    fields = env.get("fields") or []
    if type(fields) is not list:
        raise VerticalBindingAuthorityError(
            "auth_envelope_denied", "field_not_in_grant"
        )
    field_set = {str(f).lower() for f in fields}
    missing = sorted(_REQUIRED_LIVE_FIELDS - field_set)
    if missing:
        raise VerticalBindingAuthorityError(
            "auth_envelope_denied",
            f"field_not_in_grant:{','.join(missing)}",
        )
    max_calls = env.get("max_calls")
    if type(max_calls) is not int or isinstance(max_calls, bool) or max_calls < 1:
        raise VerticalBindingAuthorityError(
            "auth_envelope_budget_exceeded",
            "call_budget_exceeded",
        )
    try:
        start = _parse_iso(str(env.get("window_start") or ""))
        end = _parse_iso(str(env.get("window_end") or ""))
    except ValueError as exc:
        raise VerticalBindingAuthorityError(
            "auth_envelope_invalid", "auth_envelope window unparsable"
        ) from exc
    clock = now or _utc_now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    if not (start <= clock <= end):
        raise VerticalBindingAuthorityError(
            "auth_envelope_invalid",
            "auth_envelope_expired",
        )
    return env


class VerticalBindingAuthority:
    """Thread-safe vertical binding store (A options + B factor)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cv = Condition(self._lock)
        self._tasks: dict[tuple[str, str], VerticalTaskRecord] = {}
        self._attempts: dict[tuple[str, str], VerticalAttemptRecord] = {}
        self._runs: dict[tuple[str, str], VerticalRunRecord] = {}
        self._by_action: dict[tuple[str, str], str] = {}
        self._action_digest: dict[tuple[str, str], str] = {}
        # In-flight action keys owned by exactly one binder thread.
        self._inflight: set[tuple[str, str]] = set()
        # Process-local grant budget keyed by grant_digest.
        self._grant_remaining: dict[str, int] = {}
        self._ro_facade_factory: Callable[[], FutuReadOnlyOptionsFacade] | None = None

    def reset(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._attempts.clear()
            self._runs.clear()
            self._by_action.clear()
            self._action_digest.clear()
            self._inflight.clear()
            self._grant_remaining.clear()
            self._ro_facade_factory = None
            self._cv.notify_all()

    def set_ro_facade_factory(
        self, factory: Callable[[], FutuReadOnlyOptionsFacade] | None
    ) -> None:
        """Test/injection hook for live RO facade (never opens trade APIs)."""
        with self._lock:
            self._ro_facade_factory = factory

    def grant_remaining(self, grant_digest: str) -> int | None:
        """Test helper: remaining budget for a grant_digest, or None if unset."""
        with self._lock:
            if grant_digest not in self._grant_remaining:
                return None
            return self._grant_remaining[grant_digest]

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
        provider_mode: str = "hermetic_fixture",
        auth_envelope: dict[str, Any] | None = None,
        result_authority: ResultSurfaceAuthority | None = None,
        settings: Any | None = None,
        now: datetime | None = None,
    ) -> VerticalBindOutcome:
        """Bind NL options research goal → Task/Attempt/Run → typed result.

        Hermetic (default): fixture seed, always sample.
        Live RO: envelope-gated Futu RO fetch; real only with verifiable evidence.

        Race safety: sole in-flight owner per action key; waiters join and replay.
        Live provider I/O runs outside the lock after CAS reservation.
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
        mode = provider_mode if type(provider_mode) is str else ""
        if mode not in ("hermetic_fixture", "live_futu_ro"):
            raise VerticalBindingAuthorityError(
                "validation", "provider_mode must be hermetic_fixture|live_futu_ro"
            )

        key = (ws, act)
        rauth = result_authority or default_result_surface_authority()

        live_env: dict[str, Any] | None = None
        if mode == "live_futu_ro":
            live_env = _enforce_live_auth_envelope(
                ticker=tkr, auth_envelope=auth_envelope, now=now
            )

        grant_budget_key: str | None = None
        owned_reservation = False
        ro_factory: Callable[[], FutuReadOnlyOptionsFacade] | None = None

        with self._cv:
            while True:
                prior_digest = self._action_digest.get(key)
                if prior_digest is not None and prior_digest != action_digest:
                    raise VerticalBindingAuthorityError(
                        "conflict",
                        "client_action_id already bound to a different action_digest",
                    )
                prior_task_id = self._by_action.get(key)
                if prior_task_id is not None:
                    return self._replay_outcome(ws, prior_task_id, rauth)
                # Same digest already in-flight: wait for owner (no re-budget / pop).
                if key in self._inflight:
                    if not self._cv.wait(timeout=30.0):
                        raise VerticalBindingAuthorityError(
                            "unavailable",
                            "vertical_bind_inflight_timeout",
                        )
                    continue

                # Become sole owner of this action reservation.
                self._action_digest[key] = action_digest
                self._inflight.add(key)
                owned_reservation = True
                if mode == "live_futu_ro" and live_env is not None:
                    grant_budget_key = str(live_env.get("grant_digest") or "")
                    if not grant_budget_key:
                        self._release_reservation(
                            key, grant_budget_key=None, refund=False
                        )
                        owned_reservation = False
                        raise VerticalBindingAuthorityError(
                            "auth_envelope_invalid",
                            "grant_digest missing for budget key",
                        )
                    if grant_budget_key not in self._grant_remaining:
                        self._grant_remaining[grant_budget_key] = int(
                            live_env["max_calls"]
                        )
                    if self._grant_remaining[grant_budget_key] < 1:
                        self._release_reservation(
                            key, grant_budget_key=None, refund=False
                        )
                        owned_reservation = False
                        raise VerticalBindingAuthorityError(
                            "auth_envelope_budget_exceeded",
                            "call_budget_exceeded",
                        )
                    self._grant_remaining[grant_budget_key] -= 1
                ro_factory = self._ro_facade_factory
                break

        live_quote: VerticalRoQuote | None = None
        live_error_code: str | None = None
        if mode == "live_futu_ro":
            try:
                facade = self._resolve_ro_facade(ro_factory, settings)
                live_quote = facade.fetch_option_quote_row(
                    ticker=tkr,
                    expiry=exp,
                    strike=strike_n,
                    option_type="PUT",
                )
            except VerticalRoProviderError as exc:
                live_error_code = exc.code
                live_quote = None
            except Exception:
                live_error_code = "provider_error"
                live_quote = None

        with self._cv:
            try:
                prior_task_id = self._by_action.get(key)
                if prior_task_id is not None:
                    return self._replay_outcome(ws, prior_task_id, rauth)
                if self._action_digest.get(key) != action_digest:
                    raise VerticalBindingAuthorityError(
                        "conflict",
                        "client_action_id already bound to a different action_digest",
                    )

                task_id = _stable_id("task", action_digest, "task")
                attempt_id = _stable_id("attempt", action_digest, "attempt")
                run_id = _stable_id("run", action_digest, "run")
                result_id = _stable_id("result", action_digest, "result")
                ts = _dt_public(now)

                if mode == "hermetic_fixture":
                    sample_or_real = "sample"
                    source = "hermetic_vertical_a_binding"
                    run_mode = "hermetic_fixture"
                    if include_provider_evidence:
                        terminal: VerticalTerminal = "completed"
                        evidence: tuple[str, ...] = (
                            "hermetic_fixture_apr",
                            "hermetic_options_chain",
                        )
                        terminal_reason = "fixture_provider_evidence_present"
                        limitations: tuple[str, ...] = (
                            "hermetic_fixture",
                            "not_live_futu_quote",
                            "not_tradeable",
                            "zero_orders",
                        )
                        freshness = "fresh"
                        read_status = "available"
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
                        freshness = "unknown"
                        read_status = "degraded"
                else:
                    run_mode = "live_futu_ro"
                    source = "live_futu_ro_vertical_a_binding"
                    if live_quote is not None and live_quote.evidence:
                        sample_or_real = "real"
                        terminal = "completed"
                        evidence = tuple(live_quote.evidence)
                        terminal_reason = "live_futu_ro_provider_evidence_present"
                        limitations = (
                            "live_futu_ro",
                            "not_tradeable",
                            "zero_orders",
                        )
                        freshness = "fresh"
                        read_status = "available"
                        exp = live_quote.expiry or exp
                        strike_n = live_quote.strike
                        bid_n = live_quote.bid
                        ask_n = live_quote.ask
                        delta_n = live_quote.delta
                        iv_n = live_quote.iv
                        if live_quote.apr is not None:
                            apr_n = live_quote.apr
                    else:
                        sample_or_real = "sample"
                        terminal = "completed_degraded"
                        reason_token = live_error_code or "provider_evidence_missing"
                        terminal_reason = f"live_futu_ro_unverified:{reason_token}"
                        evidence = ()
                        limitations = (
                            "live_futu_ro_unverified",
                            "not_live_futu_quote",
                            "not_tradeable",
                            "zero_orders",
                            "provider_evidence_missing",
                        )
                        freshness = "unknown"
                        read_status = "degraded"

                lim_set = set(limitations)
                if sample_or_real == "real" and (
                    "hermetic_fixture" in lim_set or "not_live_futu_quote" in lim_set
                ):
                    sample_or_real = "sample"
                    terminal = "completed_degraded"
                    terminal_reason = "honesty_coercion"
                    limitations = tuple(
                        dict.fromkeys(
                            list(limitations)
                            + [
                                "honesty_coercion",
                                "not_live_futu_quote",
                                "not_tradeable",
                                "zero_orders",
                            ]
                        )
                    )
                    read_status = "degraded"

                try:
                    result = rauth.seed_result(
                        workspace_id=ws,
                        result_id=result_id,
                        kind="options_vertical_a",
                        display_title=f"{tkr} sell-put research ({terminal})",
                        status=terminal,
                        sample_or_real=sample_or_real,
                        freshness=freshness,
                        read_status=read_status,
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
                        source=source,
                        authority="vertical_binding_authority",
                    )
                except Exception:
                    if owned_reservation:
                        self._action_digest.pop(key, None)
                        if grant_budget_key is not None:
                            self._grant_remaining[grant_budget_key] = (
                                self._grant_remaining.get(grant_budget_key, 0) + 1
                            )
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
                    provider_mode=mode,
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
                    mode=run_mode,
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
            finally:
                if owned_reservation:
                    self._inflight.discard(key)
                    self._cv.notify_all()

    def bind_factor_vertical_b(
        self,
        *,
        workspace_id: str,
        client_action_id: str,
        action_digest: str,
        goal_note: str,
        paper_ref: str,
        paper_digest: str,
        factor_name: str,
        formula_sketch: str,
        universe_note: str,
        include_provider_evidence: bool = True,
        result_authority: ResultSurfaceAuthority | None = None,
        now: datetime | None = None,
    ) -> VerticalBindOutcome:
        """Bind hermetic factor research goal → Task/Attempt/Run → typed factor.

        M1 is hermetic-only. Never emits sample_or_real=real. Never touches
        StartResearch, ConfirmResearchPlan, Gates, backtest, Git, or brokers.
        Race safety: sole in-flight owner per action key; waiters join + replay.
        """
        ws = _validate_id(workspace_id, "workspace_id")
        act = _validate_id(client_action_id, "client_action_id")
        if type(action_digest) is not str or len(action_digest) != 64:
            raise VerticalBindingAuthorityError(
                "validation", "action_digest must be 64-hex"
            )
        goal = _bounded_text(goal_note, "goal_note", max_len=1000)
        pref = _bounded_text(paper_ref, "paper_ref", max_len=256)
        if type(paper_digest) is not str or len(paper_digest) != 64:
            raise VerticalBindingAuthorityError(
                "validation", "paper_digest must be 64-hex"
            )
        # lowercase hex only
        if any(ch not in "0123456789abcdef" for ch in paper_digest):
            raise VerticalBindingAuthorityError(
                "validation", "paper_digest must be lowercase 64-hex"
            )
        fname = _bounded_text(factor_name, "factor_name", max_len=64)
        sketch = _bounded_text(formula_sketch, "formula_sketch", max_len=1000)
        universe = _bounded_text(universe_note, "universe_note", max_len=256)
        if type(include_provider_evidence) is not bool:
            raise VerticalBindingAuthorityError(
                "validation", "include_provider_evidence must be a boolean"
            )

        key = (ws, act)
        rauth = result_authority or default_result_surface_authority()
        owned_reservation = False

        with self._cv:
            while True:
                prior_digest = self._action_digest.get(key)
                if prior_digest is not None and prior_digest != action_digest:
                    raise VerticalBindingAuthorityError(
                        "conflict",
                        "client_action_id already bound to a different action_digest",
                    )
                prior_task_id = self._by_action.get(key)
                if prior_task_id is not None:
                    return self._replay_outcome(ws, prior_task_id, rauth)
                if key in self._inflight:
                    if not self._cv.wait(timeout=30.0):
                        raise VerticalBindingAuthorityError(
                            "unavailable",
                            "vertical_bind_inflight_timeout",
                        )
                    continue
                self._action_digest[key] = action_digest
                self._inflight.add(key)
                owned_reservation = True
                break

        with self._cv:
            try:
                prior_task_id = self._by_action.get(key)
                if prior_task_id is not None:
                    return self._replay_outcome(ws, prior_task_id, rauth)
                if self._action_digest.get(key) != action_digest:
                    raise VerticalBindingAuthorityError(
                        "conflict",
                        "client_action_id already bound to a different action_digest",
                    )

                task_id = _stable_id("task", action_digest, "task")
                attempt_id = _stable_id("attempt", action_digest, "attempt")
                run_id = _stable_id("run", action_digest, "run")
                result_id = _stable_id("result", action_digest, "result")
                ts = _dt_public(now)

                sample_or_real = "sample"
                source = "hermetic_vertical_b_binding"
                run_mode = "hermetic_fixture"
                if include_provider_evidence:
                    terminal: VerticalTerminal = "completed"
                    evidence: tuple[str, ...] = (
                        "hermetic_factor_fixture",
                        "hermetic_paper_ref",
                    )
                    terminal_reason = "fixture_provider_evidence_present"
                    limitations: tuple[str, ...] = (
                        "hermetic_fixture",
                        "not_live_backtest",
                        "not_tradeable",
                        "zero_orders",
                        "plan_confirm_required",
                        "gate_cascade_locked",
                        "not_git_commit",
                    )
                    freshness = "fresh"
                    read_status = "available"
                    ic_mean: float | int | None = 0.0
                    sample_window: str | None = "hermetic_fixture_window"
                else:
                    terminal = "completed_degraded"
                    evidence = ()
                    terminal_reason = "provider_evidence_missing"
                    limitations = (
                        "hermetic_fixture",
                        "not_live_backtest",
                        "not_tradeable",
                        "zero_orders",
                        "plan_confirm_required",
                        "gate_cascade_locked",
                        "not_git_commit",
                        "unverified_without_provider_evidence",
                    )
                    freshness = "unknown"
                    read_status = "degraded"
                    ic_mean = None
                    sample_window = None

                # Honesty: never real on hermetic B path.
                lim_set = set(limitations)
                if sample_or_real == "real" and (
                    "hermetic_fixture" in lim_set or "not_live_backtest" in lim_set
                ):
                    sample_or_real = "sample"
                    terminal = "completed_degraded"
                    terminal_reason = "honesty_coercion"
                    limitations = tuple(
                        dict.fromkeys(
                            list(limitations)
                            + [
                                "honesty_coercion",
                                "not_live_backtest",
                                "not_tradeable",
                                "zero_orders",
                            ]
                        )
                    )
                    read_status = "degraded"
                    ic_mean = None
                    sample_window = None

                try:
                    result = rauth.seed_factor_vertical_b_sample(
                        workspace_id=ws,
                        result_id=result_id,
                        factor_name=fname,
                        paper_ref=pref,
                        paper_digest=paper_digest,
                        formula_sketch=sketch,
                        universe_note=universe,
                        display_title=f"{fname} factor research ({terminal})",
                        summary=goal,
                        status=terminal,
                        task_id=task_id,
                        attempt_id=attempt_id,
                        run_id=run_id,
                        provider_evidence=evidence,
                        limitations=limitations,
                        freshness=freshness,
                        read_status=read_status,
                        sample_or_real=sample_or_real,
                        ic_mean=ic_mean,
                        sample_window=sample_window,
                        source=source,
                        authority="vertical_binding_authority",
                    )
                except Exception:
                    if owned_reservation:
                        self._action_digest.pop(key, None)
                    raise

                task = VerticalTaskRecord(
                    workspace_id=ws,
                    task_id=task_id,
                    kind="factor_vertical_b_research",
                    status=terminal,
                    display_title=f"Research {fname} factor",
                    goal_note=goal,
                    ticker="",  # factor rows omit ticker in public dict
                    attempt_id=attempt_id,
                    run_id=run_id,
                    result_id=result_id,
                    client_action_id=act,
                    action_digest=action_digest,
                    occurred_at=ts,
                    terminal_reason=terminal_reason,
                    provider_evidence=evidence,
                    limitations=limitations,
                    provider_mode="hermetic_fixture",
                    vertical="factor_b",
                    factor_name=fname,
                    paper_ref=pref,
                    paper_digest=paper_digest,
                )
                attempt = VerticalAttemptRecord(
                    workspace_id=ws,
                    attempt_id=attempt_id,
                    task_id=task_id,
                    run_id=run_id,
                    status=terminal,
                    occurred_at=ts,
                    vertical="factor_b",
                )
                run = VerticalRunRecord(
                    workspace_id=ws,
                    run_id=run_id,
                    task_id=task_id,
                    attempt_id=attempt_id,
                    status=terminal,
                    occurred_at=ts,
                    mode=run_mode,
                    vertical="factor_b",
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
            finally:
                if owned_reservation:
                    self._inflight.discard(key)
                    self._cv.notify_all()

    def _release_reservation(
        self,
        key: tuple[str, str],
        *,
        grant_budget_key: str | None,
        refund: bool,
    ) -> None:
        """Caller must hold self._cv / self._lock."""
        self._inflight.discard(key)
        self._action_digest.pop(key, None)
        if refund and grant_budget_key is not None:
            self._grant_remaining[grant_budget_key] = (
                self._grant_remaining.get(grant_budget_key, 0) + 1
            )
        self._cv.notify_all()

    def _replay_outcome(
        self,
        workspace_id: str,
        task_id: str,
        rauth: ResultSurfaceAuthority,
    ) -> VerticalBindOutcome:
        task = self._tasks[(workspace_id, task_id)]
        attempt = self._attempts[(workspace_id, task.attempt_id)]
        run = self._runs[(workspace_id, task.run_id)]
        result = rauth.get(workspace_id, task.result_id or "")
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

    def _resolve_ro_facade(
        self,
        factory: Callable[[], FutuReadOnlyOptionsFacade] | None,
        settings: Any | None,
    ) -> FutuReadOnlyOptionsFacade:
        if factory is not None:
            return factory()
        from quant_system.hermes.vertical_ro_provider import build_futu_ro_facade

        if settings is None:
            raise VerticalRoProviderError(
                "provider_disabled", "settings required for live futu RO"
            )
        return build_futu_ro_facade(settings)

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
