"""Deterministic Hermes connector worker framework.

The delivered mode is intentionally reconcile-only: it repairs local expired
leases and may issue the existing allowlisted capabilities GET.  It has no run,
prompt, approval, stop, or provider mutation adapter.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import psycopg

from quant_system.hermes.command_ledger import ExpiredLeaseReconciliation
from quant_system.storage.database import DatabaseUnavailable


class CommandLeaseReconciler(Protocol):
    def reconcile_expired_leases(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> ExpiredLeaseReconciliation: ...


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


class HermesConnectorWorker:
    """Run one deterministic local-reconciliation cycle."""

    def __init__(
        self,
        *,
        ledger: CommandLeaseReconciler,
        capability_probe: Callable[[], Mapping[str, object]] | None = None,
        now: Callable[[], datetime] | None = None,
        reconcile_limit: int = 100,
    ) -> None:
        if isinstance(reconcile_limit, bool) or not 1 <= reconcile_limit <= 1000:
            raise ValueError("reconcile_limit must be between 1 and 1000")
        self._ledger = ledger
        self._capability_probe = capability_probe
        self._now = now or (lambda: datetime.now(UTC))
        self._reconcile_limit = reconcile_limit

    def run_once(self) -> HermesConnectorCycleResult:
        """Reconcile local facts and optionally probe GET-only capabilities."""
        recovered = self._ledger.reconcile_expired_leases(
            now=self._now(),
            limit=self._reconcile_limit,
        )
        return HermesConnectorCycleResult(
            mode="reconcile_only",
            requeued_count=len(recovered.requeued),
            outcome_unknown_count=len(recovered.outcome_unknown),
            capability_read_status=self._probe_capabilities(),
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

    def _probe_capabilities(self) -> str:
        if self._capability_probe is None:
            return "not_configured"
        try:
            payload = self._capability_probe()
        except Exception:  # noqa: BLE001 - read probe failure is a status, not worker failure
            return "unavailable"
        features = payload.get("features") if isinstance(payload, Mapping) else None
        if not isinstance(features, Mapping):
            return "degraded"
        return "available" if features.get("session_resources") is True else "degraded"


__all__ = [
    "HermesConnectorCycleResult",
    "HermesConnectorWorker",
    "PostgresCommandWakeupWaiter",
]
