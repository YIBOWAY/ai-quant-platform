from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from types import SimpleNamespace

import psycopg
import pytest

from quant_system.hermes.command_ledger import ExpiredLeaseReconciliation
from quant_system.hermes.connector_worker import (
    HermesConnectorWorker,
    PostgresCommandWakeupWaiter,
)


class _FakeLedger:
    def __init__(self) -> None:
        self.calls: list[tuple[datetime, int]] = []

    def reconcile_expired_leases(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> ExpiredLeaseReconciliation:
        self.calls.append((now, limit))
        return ExpiredLeaseReconciliation(requeued=(), outcome_unknown=())


class _ReadOnlyProbe:
    def __init__(self) -> None:
        self.calls = 0

    def capabilities(self) -> dict[str, object]:
        self.calls += 1
        return {
            "model": "hermes-agent",
            "features": {"session_resources": True, "run_submission": True},
        }


class _MissedWakeups:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def wait(self, timeout_seconds: float) -> bool:
        self.timeouts.append(timeout_seconds)
        return False


class _ListenerConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.waits: list[tuple[float, int]] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def notifies(self, *, timeout: float, stop_after: int):
        self.waits.append((timeout, stop_after))
        yield SimpleNamespace(channel="quant_system_hermes_commands")


class _ListenerDatabase:
    def __init__(self) -> None:
        self.connection = _ListenerConnection()
        self.exits = 0

    @contextmanager
    def connect(self):
        try:
            yield self.connection
        finally:
            self.exits += 1


class _RecoveringListenerDatabase:
    def __init__(self) -> None:
        self.connections = [_BrokenListenerConnection(), _ListenerConnection()]
        self.connect_count = 0
        self.exits = 0

    @contextmanager
    def connect(self):
        connection = self.connections[self.connect_count]
        self.connect_count += 1
        try:
            yield connection
        finally:
            self.exits += 1


class _AlwaysBrokenListenerDatabase:
    def __init__(self) -> None:
        self.connect_count = 0
        self.exits = 0

    @contextmanager
    def connect(self):
        self.connect_count += 1
        try:
            yield _BrokenListenerConnection()
        finally:
            self.exits += 1


class _BrokenListenerConnection(_ListenerConnection):
    def notifies(self, *, timeout: float, stop_after: int):
        self.waits.append((timeout, stop_after))
        raise psycopg.OperationalError("listener connection lost")
        yield  # pragma: no cover - make this a generator like psycopg's API


class _TimingOutListenerConnection(_ListenerConnection):
    def notifies(self, *, timeout: float, stop_after: int):
        self.waits.append((timeout, stop_after))
        return
        yield  # pragma: no cover - make this a generator like psycopg's API


def test_reconcile_only_cycle_probes_reads_but_never_claims_or_dispatches() -> None:
    now = datetime(2026, 7, 15, 11, 0, tzinfo=UTC)
    ledger = _FakeLedger()
    probe = _ReadOnlyProbe()
    worker = HermesConnectorWorker(
        ledger=ledger,
        capability_probe=probe.capabilities,
        now=lambda: now,
        reconcile_limit=25,
    )

    result = worker.run_once()

    assert result.mode == "reconcile_only"
    assert result.requeued_count == 0
    assert result.outcome_unknown_count == 0
    assert result.capability_read_status == "available"
    assert result.hermes_mutation_count == 0
    assert result.provider_call_count == 0
    assert ledger.calls == [(now, 25)]
    assert probe.calls == 1


def test_postgres_waiter_listens_for_the_durable_outbox_wakeup() -> None:
    database = _ListenerDatabase()
    waiter = PostgresCommandWakeupWaiter(database=database)

    assert waiter.wait(0.25) is True
    waiter.close()

    assert database.connection.statements == ["LISTEN quant_system_hermes_commands"]
    assert database.connection.waits[0][0] == pytest.approx(0.25, abs=0.01)
    assert database.connection.waits[0][1] == 1
    assert database.exits == 1


def test_postgres_waiter_recovers_after_a_listener_connection_failure() -> None:
    database = _RecoveringListenerDatabase()
    waiter = PostgresCommandWakeupWaiter(database=database)

    assert waiter.wait(0.25) is False
    assert waiter.wait(0.25) is True
    waiter.close()

    assert database.connect_count == 2
    assert database.exits == 2


def test_persistent_listener_failure_respects_poll_interval_instead_of_hot_looping() -> None:
    database = _AlwaysBrokenListenerDatabase()
    waiter = PostgresCommandWakeupWaiter(database=database)
    ledger = _FakeLedger()
    worker = HermesConnectorWorker(ledger=ledger)

    started = perf_counter()
    results = worker.run_loop(
        wakeup_waiter=waiter,
        poll_interval_seconds=0.05,
        max_cycles=3,
    )
    elapsed = perf_counter() - started
    waiter.close()

    assert len(results) == 3
    assert len(ledger.calls) == 3
    assert database.connect_count == 2
    assert database.exits == 2
    assert elapsed >= 0.09


def test_postgres_waiter_checks_stop_signal_during_a_long_poll() -> None:
    database = _ListenerDatabase()
    database.connection = _TimingOutListenerConnection()
    stop_checks = iter((False, True))
    waiter = PostgresCommandWakeupWaiter(
        database=database,
        stop_requested=lambda: next(stop_checks),
    )

    assert waiter.wait(30.0) is False
    waiter.close()

    assert database.connection.waits == [(0.5, 1)]


def test_loop_keeps_periodic_reconcile_when_database_notification_is_missed() -> None:
    now = datetime(2026, 7, 15, 11, 10, tzinfo=UTC)
    ledger = _FakeLedger()
    wakeups = _MissedWakeups()
    worker = HermesConnectorWorker(
        ledger=ledger,
        now=lambda: now,
        reconcile_limit=10,
    )

    results = worker.run_loop(
        wakeup_waiter=wakeups,
        poll_interval_seconds=0.25,
        max_cycles=2,
    )

    assert len(results) == 2
    assert ledger.calls == [(now, 10), (now, 10)]
    assert wakeups.timeouts == [0.25]


def test_run_loop_rejects_unbounded_tuple_collection() -> None:
    worker = HermesConnectorWorker(ledger=_FakeLedger())

    with pytest.raises(ValueError, match="max_cycles.*iter_cycles"):
        worker.run_loop(
            wakeup_waiter=_MissedWakeups(),
            max_cycles=None,
            stop_requested=lambda: True,
        )


def test_cycle_iterator_stops_cleanly_before_another_wait_or_cycle() -> None:
    now = datetime(2026, 7, 15, 11, 20, tzinfo=UTC)
    ledger = _FakeLedger()
    wakeups = _MissedWakeups()
    stop = False
    worker = HermesConnectorWorker(ledger=ledger, now=lambda: now)
    cycles = worker.iter_cycles(
        wakeup_waiter=wakeups,
        poll_interval_seconds=30.0,
        stop_requested=lambda: stop,
    )

    first = next(cycles)
    stop = True

    assert first.mode == "reconcile_only"
    with pytest.raises(StopIteration):
        next(cycles)
    assert len(ledger.calls) == 1
    assert wakeups.timeouts == []
