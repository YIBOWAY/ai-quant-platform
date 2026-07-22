"""Deterministic Hermes connector worker.

Modes
-----
``reconcile_only``
    Default / production-safe baseline. Repairs expired local leases and may
    issue the allowlisted capabilities GET. Never claims or dispatches.

``supervised_dispatch``
    V5 dark claim/dispatch path. Claims one binding-eligible queued command,
    marks dispatch_started inside a short transaction, calls the injected
    HermesDispatchPort **outside** any DB transaction, then records
    delivered / rejected / outcome_unknown. Empty queues produce zero Hermes
    and zero provider calls.
"""

from __future__ import annotations

import hashlib
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

import psycopg

from quant_system.hermes.command_ledger import (
    ExpiredLeaseReconciliation,
    HermesCommand,
    HermesCommandLeaseConflict,
    HermesCommandLedgerUnavailable,
    HermesCommandNotFound,
    HermesCommandStateConflict,
    HermesCommandVersionConflict,
)
from quant_system.hermes.dispatch_adapter import (
    HermesDispatchPort,
    HermesDispatchRequest,
    HermesDispatchResult,
    HermesRunObservation,
    RunLifecyclePort,
    evidence_digest_for,
)
from quant_system.hermes.session_registry import HermesSessionRegistryUnavailable
from quant_system.storage.database import DatabaseUnavailable

_UNAVAILABLE_RETRY_BASE_SECONDS = 5.0
_UNAVAILABLE_RETRY_MAX_SECONDS = 300.0


class CommandLeaseReconciler(Protocol):
    def reconcile_expired_leases(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> ExpiredLeaseReconciliation: ...


class CommandClaimLedger(CommandLeaseReconciler, Protocol):
    def list_commands_for_run_reconciliation(
        self,
        *,
        limit: int,
    ) -> tuple[HermesCommand, ...]: ...

    def mark_run_reconciliation_started(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
    ) -> HermesCommand: ...

    def claim_next_command(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> HermesCommand | None: ...

    def mark_dispatch_started(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
    ) -> HermesCommand: ...

    def heartbeat_lease(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        lease_duration: timedelta,
    ) -> HermesCommand: ...

    def mark_delivered(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
    ) -> HermesCommand: ...

    def mark_dispatch_timeout(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        error_code: str = "dispatch_timeout",
    ) -> HermesCommand: ...

    def mark_dispatch_unavailable(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        retry_at: datetime,
        error_code: str,
    ) -> HermesCommand: ...

    def mark_dispatch_rejected(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        lease_token: UUID,
        now: datetime,
        evidence_digest: str,
        error_code: str,
    ) -> HermesCommand: ...

    def reconcile_outcome_as_delivered(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
    ) -> HermesCommand: ...

    def mark_succeeded(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
    ) -> HermesCommand: ...

    def mark_failed(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
        error_code: str,
    ) -> HermesCommand: ...

    def mark_cancelled(
        self,
        *,
        command_id: UUID,
        expected_version: int,
        now: datetime,
        hermes_session_id: str,
        hermes_run_id: str,
        evidence_digest: str,
    ) -> HermesCommand: ...


class CommandWakeupWaiter(Protocol):
    def wait(self, timeout_seconds: float) -> bool: ...


class _PostgresListenerConnection(Protocol):
    def execute(self, statement: str) -> object: ...

    def notifies(self, *, timeout: float, stop_after: int): ...


class _PostgresListenerDatabase(Protocol):
    def connect(self) -> AbstractContextManager[_PostgresListenerConnection]: ...


class PostgresCommandWakeupWaiter:
    """Keep a dedicated PostgreSQL LISTEN connection for command wakeups."""

    _CHANNEL = "quant_system_hermes_commands"

    def __init__(
        self,
        *,
        database: _PostgresListenerDatabase,
        stop_requested: Callable[[], bool] | None = None,
    ) -> None:
        self._database = database
        self._stop_requested = stop_requested or (lambda: False)
        self._connection_context: AbstractContextManager[
            _PostgresListenerConnection
        ] | None = None
        self._connection: _PostgresListenerConnection | None = None

    def wait(self, timeout_seconds: float) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while not self._stop_requested():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                connection = self._ensure_connection()
                notification = next(
                    connection.notifies(
                        timeout=min(remaining, 0.5),
                        stop_after=1,
                    ),
                    None,
                )
            except (DatabaseUnavailable, OSError, psycopg.Error):
                self.close()
                self._cool_down_after_failure(deadline)
                return False
            if getattr(notification, "channel", None) == self._CHANNEL:
                return True
        return False

    def _cool_down_after_failure(self, deadline: float) -> None:
        """Avoid a hot reconnect loop while remaining responsive to shutdown."""
        while not self._stop_requested():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.1))

    def close(self) -> None:
        context = self._connection_context
        self._connection = None
        self._connection_context = None
        if context is not None:
            context.__exit__(None, None, None)

    def _ensure_connection(self) -> _PostgresListenerConnection:
        if self._connection is None:
            context = self._database.connect()
            connection = context.__enter__()
            try:
                connection.execute(f"LISTEN {self._CHANNEL}")
            except BaseException:
                context.__exit__(*sys.exc_info())
                raise
            self._connection_context = context
            self._connection = connection
        return self._connection


@dataclass(frozen=True)
class HermesConnectorCycleResult:
    mode: str
    requeued_count: int
    outcome_unknown_count: int
    capability_read_status: str
    hermes_mutation_count: int = 0
    provider_call_count: int = 0
    claimed_count: int = 0
    delivered_count: int = 0
    rejected_count: int = 0
    dispatch_unknown_count: int = 0
    recovered_count: int = 0
    terminal_count: int = 0
    last_command_id: str | None = None
    last_dispatch_outcome: str | None = None


@dataclass(frozen=True)
class DispatchGateDecision:
    """Pre-network gate evaluated after claim, before mark_dispatch_started."""

    allow: bool
    reason: str = "ok"


class HermesConnectorWorker:
    """Run one deterministic local cycle (reconcile and optionally claim/dispatch)."""

    def __init__(
        self,
        *,
        ledger: CommandLeaseReconciler,
        capability_probe: Callable[[], Mapping[str, object]] | None = None,
        now: Callable[[], datetime] | None = None,
        reconcile_limit: int = 100,
        mode: str = "reconcile_only",
        worker_id: str = "connector-worker-1",
        lease_duration: timedelta = timedelta(seconds=30),
        dispatch_adapter: HermesDispatchPort | None = None,
        run_lifecycle_port: RunLifecyclePort | None = None,
        dispatch_gate: Callable[[HermesCommand], DispatchGateDecision] | None = None,
        managed_session_resolver: Callable[[HermesCommand], str | None] | None = None,
        claims_per_cycle: int = 1,
    ) -> None:
        if isinstance(reconcile_limit, bool) or not 1 <= reconcile_limit <= 1000:
            raise ValueError("reconcile_limit must be between 1 and 1000")
        if mode not in {"reconcile_only", "supervised_dispatch"}:
            raise ValueError("mode must be reconcile_only or supervised_dispatch")
        if mode == "supervised_dispatch" and dispatch_adapter is None:
            raise ValueError("supervised_dispatch requires a dispatch_adapter")
        if isinstance(claims_per_cycle, bool) or not 1 <= claims_per_cycle <= 100:
            raise ValueError("claims_per_cycle must be between 1 and 100")
        lease_seconds = lease_duration.total_seconds()
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_duration must be between 1 and 300 seconds")
        self._ledger = ledger
        self._capability_probe = capability_probe
        self._now = now or (lambda: datetime.now(UTC))
        self._reconcile_limit = reconcile_limit
        self._mode = mode
        self._worker_id = worker_id
        self._lease_duration = lease_duration
        self._dispatch_adapter = dispatch_adapter
        self._run_lifecycle_port = run_lifecycle_port
        self._dispatch_gate = dispatch_gate or (
            lambda _cmd: DispatchGateDecision(allow=True)
        )
        self._managed_session_resolver = managed_session_resolver or (lambda _cmd: None)
        self._claims_per_cycle = claims_per_cycle

    @property
    def mode(self) -> str:
        return self._mode

    def run_once(self) -> HermesConnectorCycleResult:
        """Reconcile local facts; optionally claim/dispatch one or more commands."""
        recovered = self._ledger.reconcile_expired_leases(
            now=self._now(),
            limit=self._reconcile_limit,
        )
        claimed = 0
        delivered = 0
        rejected = 0
        dispatch_unknown = 0
        hermes_mutations = 0
        provider_calls = 0
        last_command_id: str | None = None
        last_outcome: str | None = None
        recovered_count = 0
        terminal_count = 0

        if self._mode == "supervised_dispatch":
            claim_ledger = self._as_claim_ledger()
            if self._run_lifecycle_port is not None:
                recovered_count, terminal_count = self._reconcile_active_runs(
                    claim_ledger
                )
            for _ in range(self._claims_per_cycle):
                outcome = self._claim_and_dispatch(claim_ledger)
                if outcome is None:
                    break
                claimed += 1
                last_command_id = str(outcome["command_id"])
                last_outcome = str(outcome["dispatch_outcome"])
                hermes_mutations += int(outcome["hermes_mutation_count"])
                provider_calls += int(outcome["provider_call_count"])
                if outcome["dispatch_outcome"] == "delivered":
                    delivered += 1
                elif outcome["dispatch_outcome"] == "rejected":
                    rejected += 1
                elif outcome["dispatch_outcome"] in {
                    "outcome_unknown",
                    "timeout",
                    "transport_error",
                }:
                    dispatch_unknown += 1

        return HermesConnectorCycleResult(
            mode=self._mode,
            requeued_count=len(recovered.requeued),
            outcome_unknown_count=len(recovered.outcome_unknown),
            capability_read_status=self._probe_capabilities(),
            hermes_mutation_count=hermes_mutations,
            provider_call_count=provider_calls,
            claimed_count=claimed,
            delivered_count=delivered,
            rejected_count=rejected,
            dispatch_unknown_count=dispatch_unknown,
            recovered_count=recovered_count,
            terminal_count=terminal_count,
            last_command_id=last_command_id,
            last_dispatch_outcome=last_outcome,
        )

    def run_loop(
        self,
        *,
        wakeup_waiter: CommandWakeupWaiter,
        poll_interval_seconds: float = 30.0,
        max_cycles: int | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> tuple[HermesConnectorCycleResult, ...]:
        """Collect explicitly bounded cycles; daemons must use ``iter_cycles``."""
        if max_cycles is None:
            raise ValueError(
                "run_loop max_cycles is required; use iter_cycles for streaming"
            )
        return tuple(
            self.iter_cycles(
                wakeup_waiter=wakeup_waiter,
                poll_interval_seconds=poll_interval_seconds,
                max_cycles=max_cycles,
                stop_requested=stop_requested,
            )
        )

    def iter_cycles(
        self,
        *,
        wakeup_waiter: CommandWakeupWaiter,
        poll_interval_seconds: float = 30.0,
        max_cycles: int | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> Iterator[HermesConnectorCycleResult]:
        """Stream notification-driven cycles with periodic-scan recovery."""
        if not 0.05 <= poll_interval_seconds <= 3600:
            raise ValueError("poll_interval_seconds must be between 0.05 and 3600")
        if max_cycles is not None and (
            isinstance(max_cycles, bool) or not 1 <= max_cycles <= 1_000_000
        ):
            raise ValueError("max_cycles must be positive when provided")
        should_stop = stop_requested or (lambda: False)
        completed = 0
        while not should_stop():
            yield self.run_once()
            completed += 1
            if max_cycles is not None and completed >= max_cycles:
                break
            if should_stop():
                break
            # False means timeout/missed notification; the next loop still scans.
            wakeup_waiter.wait(poll_interval_seconds)

    def _as_claim_ledger(self) -> CommandClaimLedger:
        ledger = self._ledger
        required = (
            "claim_next_command",
            "heartbeat_lease",
            "mark_dispatch_started",
            "mark_delivered",
            "mark_dispatch_timeout",
            "mark_dispatch_unavailable",
            "mark_dispatch_rejected",
        )
        if self._run_lifecycle_port is not None:
            required += (
                "list_commands_for_run_reconciliation",
                "mark_run_reconciliation_started",
                "reconcile_outcome_as_delivered",
                "mark_succeeded",
                "mark_failed",
                "mark_cancelled",
            )
        missing = [name for name in required if not callable(getattr(ledger, name, None))]
        if missing:
            raise TypeError(
                "supervised_dispatch ledger is missing: " + ", ".join(missing)
            )
        return ledger  # type: ignore[return-value]

    def _reconcile_active_runs(
        self,
        ledger: CommandClaimLedger,
    ) -> tuple[int, int]:
        """Recover unknown ACKs, then fold replay-backed terminal Run facts."""

        port = self._run_lifecycle_port
        if port is None:
            return 0, 0
        try:
            commands = ledger.list_commands_for_run_reconciliation(
                limit=self._reconcile_limit
            )
        except Exception:  # noqa: BLE001 - a read outage must not start new recovery I/O
            return 0, 0

        recovered_count = 0
        terminal_count = 0
        for command in commands:
            try:
                # Persist the scheduling decision before any upstream I/O. The
                # version CAS admits one concurrent reconciler, while the
                # updated_at touch moves this command behind older active Runs.
                # A crash/restart therefore cannot reset the fairness cursor.
                current = ledger.mark_run_reconciliation_started(
                    command_id=command.command_id,
                    expected_version=command.version,
                    now=self._now(),
                )
            except (
                HermesCommandLedgerUnavailable,
                HermesCommandNotFound,
                HermesCommandStateConflict,
                HermesCommandVersionConflict,
            ):
                continue
            if current.state == "outcome_unknown" and (
                not current.hermes_session_id or not current.hermes_run_id
            ):
                current = self._recover_unknown_outcome(ledger, current, port)
                if current.state == "delivered":
                    recovered_count += 1
            if (
                current.state not in {"delivered", "outcome_unknown"}
                or not current.hermes_session_id
                or not current.hermes_run_id
            ):
                continue
            try:
                observation = port.observe(
                    hermes_session_id=current.hermes_session_id,
                    hermes_run_id=current.hermes_run_id,
                    # Until a durable platform cursor is introduced, replay from
                    # zero and let command-version CAS deduplicate the fold.
                    after_cursor=0,
                )
            except Exception:  # noqa: BLE001 - observation failure is nonterminal
                continue
            if self._record_terminal_observation(ledger, current, observation):
                terminal_count += 1
        return recovered_count, terminal_count

    def _recover_unknown_outcome(
        self,
        ledger: CommandClaimLedger,
        command: HermesCommand,
        port: RunLifecyclePort,
    ) -> HermesCommand:
        """Use the original identity/body digest; never create a blind retry."""

        try:
            request = self._dispatch_request(command)
            result = port.submit_or_recover(request)
        except Exception:  # noqa: BLE001 - preserve durable outcome_unknown
            return command
        if (
            not result.is_success
            or not result.hermes_session_id
            or not result.hermes_run_id
            or result.hermes_session_id != request.hermes_session_id
        ):
            return command
        evidence = result.evidence_digest or evidence_digest_for(
            hermes_session_id=result.hermes_session_id,
            hermes_run_id=result.hermes_run_id,
            outcome="recovered",
        )
        try:
            return ledger.reconcile_outcome_as_delivered(
                command_id=command.command_id,
                expected_version=command.version,
                now=self._now(),
                hermes_session_id=result.hermes_session_id,
                hermes_run_id=result.hermes_run_id,
                evidence_digest=evidence,
            )
        except (
            HermesCommandLedgerUnavailable,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            return command

    def _record_terminal_observation(
        self,
        ledger: CommandClaimLedger,
        command: HermesCommand,
        observation: HermesRunObservation,
    ) -> bool:
        if (
            not observation.is_terminal
            or not observation.replay_complete
            or not observation.evidence_digest
            or observation.hermes_session_id != command.hermes_session_id
            or observation.hermes_run_id != command.hermes_run_id
        ):
            return False
        common = {
            "command_id": command.command_id,
            "expected_version": command.version,
            "now": self._now(),
            "hermes_session_id": observation.hermes_session_id,
            "hermes_run_id": observation.hermes_run_id,
            "evidence_digest": observation.evidence_digest,
        }
        try:
            if observation.status == "succeeded":
                ledger.mark_succeeded(**common)
            elif observation.status == "failed":
                ledger.mark_failed(
                    **common,
                    error_code=_safe_error_code(
                        observation.error_code or "hermes_run_failed"
                    ),
                )
            else:
                ledger.mark_cancelled(**common)
        except (
            HermesCommandLedgerUnavailable,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            return False
        return True

    def _dispatch_request(self, command: HermesCommand) -> HermesDispatchRequest:
        return HermesDispatchRequest(
            command_id=str(command.command_id),
            kind=command.kind,
            client_request_id=command.client_request_id,
            platform_session_id=command.platform_session_id,
            canonical_request_digest=command.canonical_request_digest,
            payload_ref=command.payload_ref,
            provider_policy_digest=command.provider_policy_digest,
            hermes_session_id=self._managed_session_resolver(command),
        )

    def _claim_and_dispatch(self, ledger: CommandClaimLedger) -> dict[str, object] | None:
        now = self._now()
        claimed = ledger.claim_next_command(
            worker_id=self._worker_id,
            now=now,
            lease_duration=self._lease_duration,
        )
        if claimed is None:
            return None
        if claimed.lease_token is None:
            return {
                "command_id": str(claimed.command_id),
                "dispatch_outcome": "outcome_unknown",
                "hermes_mutation_count": 0,
                "provider_call_count": 0,
            }

        gate = self._dispatch_gate(claimed)
        if not gate.allow:
            # Gate failure after claim but before network: definitive reject,
            # never call Hermes.
            try:
                started = ledger.mark_dispatch_started(
                    command_id=claimed.command_id,
                    expected_version=claimed.version,
                    lease_token=claimed.lease_token,
                    now=self._now(),
                )
                evidence = _sha256(gate.reason)
                ledger.mark_dispatch_rejected(
                    command_id=started.command_id,
                    expected_version=started.version,
                    lease_token=claimed.lease_token,
                    now=self._now(),
                    evidence_digest=evidence,
                    error_code=_safe_error_code(gate.reason),
                )
            except (
                HermesCommandLedgerUnavailable,
                HermesCommandLeaseConflict,
                HermesCommandNotFound,
                HermesCommandStateConflict,
                HermesCommandVersionConflict,
            ):
                pass
            return {
                "command_id": str(claimed.command_id),
                "dispatch_outcome": "rejected",
                "hermes_mutation_count": 0,
                "provider_call_count": 0,
            }

        # Crash matrix: PG claim commit done. Next durable step is
        # mark_dispatch_started — still no network.
        try:
            started = ledger.mark_dispatch_started(
                command_id=claimed.command_id,
                expected_version=claimed.version,
                lease_token=claimed.lease_token,
                now=self._now(),
            )
        except (
            HermesCommandLedgerUnavailable,
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            return {
                "command_id": str(claimed.command_id),
                "dispatch_outcome": "outcome_unknown",
                "hermes_mutation_count": 0,
                "provider_call_count": 0,
            }

        # Crash matrix: dispatch_started committed; network is outside TX.
        assert self._dispatch_adapter is not None
        try:
            request = self._dispatch_request(started)
        except HermesSessionRegistryUnavailable:
            return self._record_dispatch_result(
                ledger=ledger,
                started=started,
                lease_token=claimed.lease_token,
                result=HermesDispatchResult(
                    kind="unavailable",
                    error_code="managed_session_registry_unavailable",
                    network_attempted=False,
                ),
            )
        except Exception:  # noqa: BLE001 - registry errors stay secret-free
            try:
                ledger.mark_dispatch_rejected(
                    command_id=started.command_id,
                    expected_version=started.version,
                    lease_token=claimed.lease_token,
                    now=self._now(),
                    evidence_digest=_sha256("managed_session_resolution_failed"),
                    error_code="managed_session_resolution_failed",
                )
            except (
                HermesCommandLedgerUnavailable,
                HermesCommandLeaseConflict,
                HermesCommandNotFound,
                HermesCommandStateConflict,
                HermesCommandVersionConflict,
            ):
                return {
                    "command_id": str(started.command_id),
                    "dispatch_outcome": "outcome_unknown",
                    "hermes_mutation_count": 0,
                    "provider_call_count": 0,
                }
            return {
                "command_id": str(started.command_id),
                "dispatch_outcome": "rejected",
                "hermes_mutation_count": 0,
                "provider_call_count": 0,
            }
        # Extend once immediately, then periodically while the external call is
        # in flight. The latest version returned by heartbeat CAS is the only
        # version allowed to record the response.
        try:
            started = ledger.heartbeat_lease(
                command_id=started.command_id,
                expected_version=started.version,
                lease_token=claimed.lease_token,
                now=self._now(),
                lease_duration=self._lease_duration,
            )
        except (
            HermesCommandLedgerUnavailable,
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            return {
                "command_id": str(started.command_id),
                "dispatch_outcome": "outcome_unknown",
                "hermes_mutation_count": 0,
                "provider_call_count": 0,
            }

        result, started = self._submit_with_lease_heartbeat(
            ledger=ledger,
            started=started,
            lease_token=claimed.lease_token,
            request=request,
        )

        return self._record_dispatch_result(
            ledger=ledger,
            started=started,
            lease_token=claimed.lease_token,
            result=result,
        )

    def _submit_with_lease_heartbeat(
        self,
        *,
        ledger: CommandClaimLedger,
        started: HermesCommand,
        lease_token: UUID,
        request: HermesDispatchRequest,
    ) -> tuple[HermesDispatchResult, HermesCommand]:
        """Submit outside PostgreSQL transactions while renewing lease fencing."""

        current = [started]
        lock = threading.Lock()
        stop = threading.Event()
        interval = max(0.05, min(10.0, self._lease_duration.total_seconds() / 3.0))

        def _heartbeat() -> None:
            while not stop.wait(interval):
                try:
                    with lock:
                        row = current[0]
                        current[0] = ledger.heartbeat_lease(
                            command_id=row.command_id,
                            expected_version=row.version,
                            lease_token=lease_token,
                            now=self._now(),
                            lease_duration=self._lease_duration,
                        )
                except Exception:  # noqa: BLE001 - response CAS will fence loss
                    return

        thread = threading.Thread(
            target=_heartbeat,
            name=f"hermes-lease-heartbeat-{started.command_id}",
            daemon=True,
        )
        thread.start()
        assert self._dispatch_adapter is not None
        try:
            result = self._dispatch_adapter.submit_or_recover(request)
        except Exception:  # noqa: BLE001 - unexpected adapter failure is unknown
            result = HermesDispatchResult(
                kind="transport_error",
                error_code="hermes_adapter_exception",
            )
        finally:
            stop.set()
            thread.join(timeout=min(1.0, interval + 0.1))
        with lock:
            latest = current[0]
        return result, latest

    def _record_dispatch_result(
        self,
        *,
        ledger: CommandClaimLedger,
        started: HermesCommand,
        lease_token: UUID,
        result: HermesDispatchResult,
    ) -> dict[str, object]:
        command_id = str(started.command_id)
        hermes_mutations = int(result.network_attempted)
        provider_calls = int(result.provider_call_count)

        try:
            if result.is_success:
                if not result.hermes_session_id or not result.hermes_run_id:
                    ledger.mark_dispatch_timeout(
                        command_id=started.command_id,
                        expected_version=started.version,
                        lease_token=lease_token,
                        now=self._now(),
                        error_code="missing_hermes_ids",
                    )
                    return {
                        "command_id": command_id,
                        "dispatch_outcome": "outcome_unknown",
                        "hermes_mutation_count": hermes_mutations,
                        "provider_call_count": provider_calls,
                    }
                # Crash matrix: Hermes accepted; PG exact Run binding next.
                ledger.mark_delivered(
                    command_id=started.command_id,
                    expected_version=started.version,
                    lease_token=lease_token,
                    now=self._now(),
                    hermes_session_id=result.hermes_session_id,
                    hermes_run_id=result.hermes_run_id,
                )
                return {
                    "command_id": command_id,
                    "dispatch_outcome": "delivered",
                    "hermes_mutation_count": hermes_mutations,
                    "provider_call_count": provider_calls,
                }

            if result.kind == "rejected":
                evidence = result.evidence_digest or _sha256(
                    result.error_code or "upstream_rejected"
                )
                ledger.mark_dispatch_rejected(
                    command_id=started.command_id,
                    expected_version=started.version,
                    lease_token=lease_token,
                    now=self._now(),
                    evidence_digest=evidence,
                    error_code=_safe_error_code(
                        result.error_code or "upstream_rejected"
                    ),
                )
                return {
                    "command_id": command_id,
                    "dispatch_outcome": "rejected",
                    "hermes_mutation_count": hermes_mutations,
                    "provider_call_count": provider_calls,
                }

            if not result.network_attempted:
                # The Run mutation seam was definitively not reached. Release
                # the lease back to a delayed queue instead of fabricating an
                # ``outcome_unknown`` fact that would require Run recovery.
                recorded_at = self._now()
                ledger.mark_dispatch_unavailable(
                    command_id=started.command_id,
                    expected_version=started.version,
                    lease_token=lease_token,
                    now=recorded_at,
                    retry_at=recorded_at + _unavailable_retry_delay(started),
                    error_code=_safe_error_code(
                        result.error_code or "dispatch_unavailable"
                    ),
                )
                return {
                    "command_id": command_id,
                    "dispatch_outcome": "unavailable",
                    "hermes_mutation_count": 0,
                    "provider_call_count": provider_calls,
                }

            # Once the Run mutation seam may have been reached, timeout /
            # transport failure is durably unknown and must never blind-retry.
            # Never blind-retry; recovery must use submit-or-recover identity.
            ledger.mark_dispatch_timeout(
                command_id=started.command_id,
                expected_version=started.version,
                lease_token=lease_token,
                now=self._now(),
                error_code=_safe_error_code(result.error_code or "dispatch_timeout"),
            )
            return {
                "command_id": command_id,
                "dispatch_outcome": "outcome_unknown",
                "hermes_mutation_count": hermes_mutations,
                "provider_call_count": provider_calls,
            }
        except (
            HermesCommandLedgerUnavailable,
            HermesCommandLeaseConflict,
            HermesCommandNotFound,
            HermesCommandStateConflict,
            HermesCommandVersionConflict,
        ):
            # Lease lost mid-record: another reconciler owns recovery.
            return {
                "command_id": command_id,
                "dispatch_outcome": "outcome_unknown",
                "hermes_mutation_count": hermes_mutations,
                "provider_call_count": provider_calls,
            }

    def _probe_capabilities(self) -> str:
        if self._capability_probe is None:
            return "not_configured"
        try:
            payload = self._capability_probe()
        except Exception:  # noqa: BLE001 - read probe failure is a status
            return "unavailable"
        features = payload.get("features") if isinstance(payload, Mapping) else None
        if not isinstance(features, Mapping):
            return "degraded"
        return "available" if features.get("session_resources") is True else "degraded"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unavailable_retry_delay(command: HermesCommand) -> timedelta:
    """Bounded exponential retry with deterministic per-command jitter."""

    attempt = max(1, int(command.attempt_count))
    exponent = min(attempt - 1, 16)
    base = _UNAVAILABLE_RETRY_BASE_SECONDS * (2**exponent)
    jitter_seed = hashlib.sha256(
        f"{command.command_id}:{attempt}".encode("ascii")
    ).digest()
    jitter = 0.9 + (int.from_bytes(jitter_seed[:2], "big") / 65_535) * 0.2
    seconds = min(_UNAVAILABLE_RETRY_MAX_SECONDS, base * jitter)
    return timedelta(seconds=seconds)


def _safe_error_code(raw: str) -> str:
    """Coerce arbitrary gate/adapter codes into the ledger error_code grammar."""
    cleaned = re.sub(r"[^a-z0-9_.-]+", "_", raw.strip().lower())
    if not cleaned or not cleaned[0].isalpha():
        cleaned = f"e_{cleaned}" if cleaned else "dispatch_error"
    return cleaned[:64]


__all__ = [
    "DispatchGateDecision",
    "HermesConnectorCycleResult",
    "HermesConnectorWorker",
    "PostgresCommandWakeupWaiter",
]
