"""V5 supervised claim/dispatch worker — hermetic unit + crash matrix."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.command_ledger import (
    ExpiredLeaseReconciliation,
    HermesCommand,
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
)
from quant_system.hermes.connector_worker import (
    DispatchGateDecision,
    HermesConnectorWorker,
)
from quant_system.hermes.dispatch_adapter import (
    FakeHermesDispatchAdapter,
    HermesDispatchRequest,
    HermesDispatchResult,
    HermesRunObservation,
)
from quant_system.hermes.session_registry import HermesSessionRegistryUnavailable
from quant_system.hermes.workflow_binding import (
    PreparedWorkflowCommand,
    ensure_bound_command,
    workflow_preparation_digest,
)
from quant_system.storage import database as db


def _cmd(
    *,
    state: str = "queued",
    version: int = 1,
    lease_token: UUID | None = None,
    client_request_id: str = "req-v5-001",
    platform_session_id: str = "platform-session-v5",
    attempt_count: int = 0,
) -> HermesCommand:
    token = lease_token if lease_token is not None else uuid4()
    return HermesCommand(
        command_id=uuid4(),
        owner_user_id=UUID("00000000-0000-0000-0000-000000000001"),
        platform_session_id=platform_session_id,
        client_request_id=client_request_id,
        kind="research_chat",
        intent_schema_version=1,
        canonical_request_digest="a" * 64,
        payload_ref="platform-payload://sha256/" + ("b" * 64),
        provider_policy_digest="c" * 64,
        state=state,  # type: ignore[arg-type]
        version=version,
        attempt_count=attempt_count,
        next_attempt_at=None,
        lease_owner="worker-v5" if state == "leased" else None,
        lease_token=token if state == "leased" else None,
        lease_until=datetime(2026, 7, 21, 12, 0, tzinfo=UTC) if state == "leased" else None,
        dispatch_started_at=None,
        hermes_session_id=None,
        hermes_run_id=None,
        last_error_code=None,
        created_at=datetime(2026, 7, 21, 11, 0, tzinfo=UTC),
        updated_at=datetime(2026, 7, 21, 11, 0, tzinfo=UTC),
    )


@dataclass
class _ScriptedLedger:
    """In-memory claim/dispatch ledger for crash-matrix unit tests."""

    queue: list[HermesCommand]
    reconcile_calls: int = 0
    claim_calls: int = 0
    started: list[UUID] = None  # type: ignore[assignment]
    delivered: list[tuple[UUID, str, str]] = None  # type: ignore[assignment]
    rejected: list[tuple[UUID, str]] = None  # type: ignore[assignment]
    timed_out: list[tuple[UUID, str]] = None  # type: ignore[assignment]
    succeeded: list[UUID] = None  # type: ignore[assignment]
    reconciliation_started: list[UUID] = None  # type: ignore[assignment]
    heartbeat_calls: int = 0
    fail_on: str | None = None  # crash injection point name

    def __post_init__(self) -> None:
        self.started = []
        self.delivered = []
        self.rejected = []
        self.timed_out = []
        self.succeeded = []
        self.reconciliation_started = []
        self._by_id: dict[UUID, HermesCommand] = {c.command_id: c for c in self.queue}

    def reconcile_expired_leases(self, *, now, limit):
        self.reconcile_calls += 1
        return ExpiredLeaseReconciliation(requeued=(), outcome_unknown=())

    def list_commands_for_run_reconciliation(self, *, limit):
        eligible = sorted(
            (
                command
                for command in self._by_id.values()
                if command.state in {"delivered", "outcome_unknown"}
            ),
            key=lambda command: (command.updated_at, command.command_id),
        )
        return tuple(eligible[:limit])

    def mark_run_reconciliation_started(
        self,
        *,
        command_id,
        expected_version,
        now,
    ):
        cmd = self._by_id[command_id]
        assert cmd.version == expected_version
        assert cmd.state in {"delivered", "outcome_unknown"}
        started = replace(
            cmd,
            version=cmd.version + 1,
            updated_at=now,
        )
        self._by_id[command_id] = started
        self.reconciliation_started.append(command_id)
        return started

    def reconcile_outcome_as_delivered(
        self,
        *,
        command_id,
        expected_version,
        now,
        hermes_session_id,
        hermes_run_id,
        evidence_digest,
    ):
        cmd = self._by_id[command_id]
        assert cmd.version == expected_version
        delivered = replace(
            cmd,
            state="delivered",  # type: ignore[arg-type]
            version=cmd.version + 1,
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            last_error_code=None,
        )
        self._by_id[command_id] = delivered
        return delivered

    def mark_succeeded(
        self,
        *,
        command_id,
        expected_version,
        now,
        hermes_session_id,
        hermes_run_id,
        evidence_digest,
    ):
        cmd = self._by_id[command_id]
        assert cmd.version == expected_version
        assert cmd.hermes_session_id == hermes_session_id
        assert cmd.hermes_run_id == hermes_run_id
        terminal = replace(
            cmd,
            state="succeeded",  # type: ignore[arg-type]
            version=cmd.version + 1,
        )
        self._by_id[command_id] = terminal
        self.succeeded.append(command_id)
        return terminal

    def mark_failed(self, **kwargs):
        cmd = self._by_id[kwargs["command_id"]]
        terminal = replace(
            cmd,
            state="failed",  # type: ignore[arg-type]
            version=cmd.version + 1,
            last_error_code=kwargs["error_code"],
        )
        self._by_id[cmd.command_id] = terminal
        return terminal

    def mark_cancelled(self, **kwargs):
        cmd = self._by_id[kwargs["command_id"]]
        terminal = replace(
            cmd,
            state="cancelled",  # type: ignore[arg-type]
            version=cmd.version + 1,
        )
        self._by_id[cmd.command_id] = terminal
        return terminal

    def claim_next_command(self, *, worker_id, now, lease_duration):
        self.claim_calls += 1
        if self.fail_on == "before_claim":
            return None
        for cmd in list(self.queue):
            if cmd.state != "queued":
                continue
            if cmd.next_attempt_at is not None and cmd.next_attempt_at > now:
                continue
            self.queue.remove(cmd)
            leased = replace(
                cmd,
                state="leased",  # type: ignore[arg-type]
                version=cmd.version + 1,
                lease_owner=worker_id,
                lease_token=uuid4(),
                lease_until=now + lease_duration,
            )
            self._by_id[leased.command_id] = leased
            if self.fail_on == "after_claim_before_dispatch_started":
                # Simulate worker crash: claim committed, nothing else.
                return leased
            return leased
        return None

    def mark_dispatch_started(self, *, command_id, expected_version, lease_token, now):
        if self.fail_on == "after_claim_before_dispatch_started":
            # Worker never reaches here in the crash scenario; if called, raise.
            raise AssertionError("should not mark_dispatch_started after crash")
        cmd = self._by_id[command_id]
        assert cmd.version == expected_version
        assert cmd.lease_token == lease_token
        started = replace(
            cmd,
            version=cmd.version + 1,
            attempt_count=cmd.attempt_count + 1,
            dispatch_started_at=now,
        )
        self._by_id[command_id] = started
        self.started.append(command_id)
        if self.fail_on == "after_dispatch_started_before_hermes":
            return started
        return started

    def heartbeat_lease(
        self,
        *,
        command_id,
        expected_version,
        lease_token,
        now,
        lease_duration,
    ):
        cmd = self._by_id[command_id]
        assert cmd.version == expected_version
        assert cmd.lease_token == lease_token
        heartbeat = replace(
            cmd,
            version=cmd.version + 1,
            lease_until=now + lease_duration,
        )
        self._by_id[command_id] = heartbeat
        self.heartbeat_calls += 1
        return heartbeat

    def mark_delivered(
        self,
        *,
        command_id,
        expected_version,
        lease_token,
        now,
        hermes_session_id,
        hermes_run_id,
    ):
        if self.fail_on == "after_hermes_before_pg_link":
            # Crash: Hermes accepted but PG never records delivery.
            raise HermesCommandLedgerUnavailable("simulated database outage")
        cmd = self._by_id[command_id]
        assert cmd.version == expected_version
        delivered = replace(
            cmd,
            state="delivered",  # type: ignore[arg-type]
            version=cmd.version + 1,
            lease_owner=None,
            lease_token=None,
            lease_until=None,
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
        )
        self._by_id[command_id] = delivered
        self.delivered.append((command_id, hermes_session_id, hermes_run_id))
        return delivered

    def mark_dispatch_timeout(
        self, *, command_id, expected_version, lease_token, now, error_code="dispatch_timeout"
    ):
        cmd = self._by_id[command_id]
        unknown = replace(
            cmd,
            state="outcome_unknown",  # type: ignore[arg-type]
            version=cmd.version + 1,
            lease_owner=None,
            lease_token=None,
            lease_until=None,
            last_error_code=error_code,
        )
        self._by_id[command_id] = unknown
        self.timed_out.append((command_id, error_code))
        return unknown

    def mark_dispatch_unavailable(
        self,
        *,
        command_id,
        expected_version,
        lease_token,
        now,
        retry_at,
        error_code,
    ):
        cmd = self._by_id[command_id]
        assert cmd.version == expected_version
        assert cmd.lease_token == lease_token
        queued = replace(
            cmd,
            state="queued",  # type: ignore[arg-type]
            version=cmd.version + 1,
            next_attempt_at=retry_at,
            lease_owner=None,
            lease_token=None,
            lease_until=None,
            dispatch_started_at=None,
            last_error_code=error_code,
        )
        self._by_id[command_id] = queued
        self.queue.append(queued)
        return queued

    def mark_dispatch_rejected(
        self, *, command_id, expected_version, lease_token, now, evidence_digest, error_code
    ):
        cmd = self._by_id[command_id]
        failed = replace(
            cmd,
            state="failed",  # type: ignore[arg-type]
            version=cmd.version + 1,
            lease_owner=None,
            lease_token=None,
            lease_until=None,
            last_error_code=error_code,
        )
        self._by_id[command_id] = failed
        self.rejected.append((command_id, error_code))
        return failed


def test_supervised_requires_dispatch_adapter() -> None:
    with pytest.raises(ValueError, match="dispatch_adapter"):
        HermesConnectorWorker(
            ledger=_ScriptedLedger(queue=[]),
            mode="supervised_dispatch",
        )


def test_empty_queue_zero_hermes_and_provider_calls() -> None:
    ledger = _ScriptedLedger(queue=[])
    adapter = FakeHermesDispatchAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    result = worker.run_once()
    assert result.mode == "supervised_dispatch"
    assert result.claimed_count == 0
    assert result.hermes_mutation_count == 0
    assert result.provider_call_count == 0
    assert adapter.submit_calls == 0
    assert ledger.claim_calls == 1
    assert ledger.reconcile_calls == 1


def test_happy_path_claim_dispatch_delivered() -> None:
    cmd = _cmd()
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        worker_id="worker-v5",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    result = worker.run_once()
    assert result.claimed_count == 1
    assert result.delivered_count == 1
    assert result.hermes_mutation_count == 1
    assert result.provider_call_count == 0  # fake default: no provider burn
    assert result.last_dispatch_outcome == "delivered"
    assert adapter.submit_calls == 1
    assert len(ledger.delivered) == 1
    session_id, run_id = ledger.delivered[0][1], ledger.delivered[0][2]
    assert session_id.startswith("sess_")
    assert run_id.startswith("run_")
    assert ledger._by_id[cmd.command_id].state == "delivered"


def test_worker_resolves_and_reuses_managed_hermes_session() -> None:
    cmd = _cmd()
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    resolved: list[str] = []

    def resolve_managed_session(command: HermesCommand) -> str:
        resolved.append(command.platform_session_id)
        return "web_managed_deadbeef"

    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        managed_session_resolver=resolve_managed_session,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.delivered_count == 1
    assert resolved == ["platform-session-v5"]
    assert ledger.delivered[0][1] == "web_managed_deadbeef"


def test_accepted_is_nonterminal_until_durable_observer_reports_success() -> None:
    cmd = _cmd(client_request_id="req-v6-observe")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        run_lifecycle_port=adapter,
        managed_session_resolver=lambda _command: "web_managed_observe",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    accepted = worker.run_once()
    delivered = ledger._by_id[cmd.command_id]
    assert accepted.delivered_count == 1
    assert delivered.state == "delivered"
    assert delivered.hermes_run_id is not None

    adapter.set_run_observation(
        HermesRunObservation(
            status="succeeded",
            hermes_session_id="web_managed_observe",
            hermes_run_id=delivered.hermes_run_id,
            evidence_digest="f" * 64,
            next_cursor=3,
            replay_complete=True,
        )
    )
    observed = worker.run_once()

    assert observed.terminal_count == 1
    assert ledger._by_id[cmd.command_id].state == "succeeded"


def test_terminal_observation_always_replays_from_zero() -> None:
    class CursorRecordingAdapter(FakeHermesDispatchAdapter):
        observed_cursors: list[int]

        def __init__(self) -> None:
            super().__init__()
            self.observed_cursors = []

        def observe(self, *, hermes_session_id, hermes_run_id, after_cursor=0):
            self.observed_cursors.append(after_cursor)
            return super().observe(
                hermes_session_id=hermes_session_id,
                hermes_run_id=hermes_run_id,
                after_cursor=after_cursor,
            )

    cmd = _cmd(client_request_id="req-v6-full-replay")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = CursorRecordingAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        run_lifecycle_port=adapter,
        managed_session_resolver=lambda _command: "web_managed_full_replay",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    worker.run_once()
    worker.run_once()

    assert adapter.observed_cursors == [0]


def test_nonterminal_reconciliation_rotates_active_runs_across_cycles() -> None:
    class RunRecordingAdapter(FakeHermesDispatchAdapter):
        observed_runs: list[str]

        def __init__(self) -> None:
            super().__init__()
            self.observed_runs = []

        def observe(self, *, hermes_session_id, hermes_run_id, after_cursor=0):
            self.observed_runs.append(hermes_run_id)
            return super().observe(
                hermes_session_id=hermes_session_id,
                hermes_run_id=hermes_run_id,
                after_cursor=after_cursor,
            )

    active = [
        replace(
            _cmd(client_request_id=f"req-v6-fair-{index}"),
            state="delivered",  # type: ignore[arg-type]
            version=4,
            hermes_session_id="web_managed_fair",
            hermes_run_id=f"run_fair_{index}",
        )
        for index in range(3)
    ]
    ledger = _ScriptedLedger(queue=active)
    adapter = RunRecordingAdapter()
    ticks = iter(
        datetime(2026, 7, 21, 12, 0, index, tzinfo=UTC)
        for index in range(30)
    )
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        run_lifecycle_port=adapter,
        reconcile_limit=1,
        now=lambda: next(ticks),
    )

    worker.run_once()
    worker.run_once()
    worker.run_once()

    assert len(set(adapter.observed_runs)) == 3
    assert set(ledger.reconciliation_started) == {
        command.command_id for command in active
    }


def test_closed_fresh_gate_blocks_active_run_network_reconciliation() -> None:
    class RecordingAdapter(FakeHermesDispatchAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.observe_calls = 0

        def observe(self, *, hermes_session_id, hermes_run_id, after_cursor=0):
            self.observe_calls += 1
            return super().observe(
                hermes_session_id=hermes_session_id,
                hermes_run_id=hermes_run_id,
                after_cursor=after_cursor,
            )

    command = _cmd(client_request_id="req-v6-gated-reconcile")
    ledger = _ScriptedLedger(queue=[command])
    adapter = RecordingAdapter()
    gate_open = True
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        run_lifecycle_port=adapter,
        dispatch_gate=lambda _command: DispatchGateDecision(
            allow=gate_open,
            reason="ready" if gate_open else "release_gate_closed",
        ),
        managed_session_resolver=lambda _command: "web_managed_gate_reconcile",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    assert worker.run_once().delivered_count == 1
    gate_open = False
    assert worker.run_once().terminal_count == 0

    assert adapter.submit_calls == 1
    assert adapter.observe_calls == 0
    assert ledger.reconciliation_started == []


def test_worker_recovers_accept_drop_ack_with_same_identity_and_session() -> None:
    cmd = _cmd(client_request_id="req-v6-ack-loss")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter(force_provider_calls=True)
    adapter.next_fault = "accept_drop_ack"
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        run_lifecycle_port=adapter,
        managed_session_resolver=lambda _command: "web_managed_ack_loss",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    first = worker.run_once()
    assert first.dispatch_unknown_count == 1
    assert ledger._by_id[cmd.command_id].state == "outcome_unknown"

    second = worker.run_once()
    recovered = ledger._by_id[cmd.command_id]

    assert second.recovered_count == 1
    assert recovered.state == "delivered"
    assert recovered.hermes_session_id == "web_managed_ack_loss"
    assert recovered.hermes_run_id is not None
    assert adapter.submit_calls == 2
    assert adapter.provider_calls == 1


def test_same_client_request_id_in_two_sessions_uses_distinct_upstream_keys() -> None:
    """Ledger idempotency is session-scoped; upstream keys must not collide."""

    first = _cmd(
        client_request_id="same-browser-action",
        platform_session_id="wm_session_one",
    )
    second = _cmd(
        client_request_id="same-browser-action",
        platform_session_id="wm_session_two",
    )
    adapter = FakeHermesDispatchAdapter()

    first_result = adapter.submit_or_recover(
        HermesDispatchRequest(
            command_id=str(first.command_id),
            kind=first.kind,
            client_request_id=first.client_request_id,
            platform_session_id=first.platform_session_id,
            canonical_request_digest=first.canonical_request_digest,
            payload_ref=first.payload_ref,
            hermes_session_id="web_session_one",
        )
    )
    second_result = adapter.submit_or_recover(
        HermesDispatchRequest(
            command_id=str(second.command_id),
            kind=second.kind,
            client_request_id=second.client_request_id,
            platform_session_id=second.platform_session_id,
            canonical_request_digest=second.canonical_request_digest,
            payload_ref=second.payload_ref,
            hermes_session_id="web_session_two",
        )
    )

    assert first_result.kind == "accepted"
    assert second_result.kind == "accepted"
    assert first_result.hermes_run_id != second_result.hermes_run_id


def test_worker_heartbeats_lease_before_external_dispatch() -> None:
    cmd = _cmd(client_request_id="req-v6-heartbeat")
    ledger = _ScriptedLedger(queue=[cmd])
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=FakeHermesDispatchAdapter(),
        managed_session_resolver=lambda _command: "web_managed_heartbeat",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.delivered_count == 1
    assert ledger.heartbeat_calls >= 1


def test_managed_session_resolution_failure_never_calls_hermes() -> None:
    cmd = _cmd(client_request_id="req-v6-session-fail")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()

    def fail_resolution(_command: HermesCommand) -> str:
        raise RuntimeError("registry unavailable with secret detail")

    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        managed_session_resolver=fail_resolution,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.rejected_count == 1
    assert adapter.submit_calls == 0
    assert ledger._by_id[cmd.command_id].last_error_code == "managed_session_resolution_failed"


def test_temporary_managed_session_registry_outage_requeues_without_hermes() -> None:
    cmd = _cmd(client_request_id="req-v6-session-temporary")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()

    def unavailable(_command: HermesCommand) -> str:
        raise HermesSessionRegistryUnavailable("secret database detail")

    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        managed_session_resolver=unavailable,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    command = ledger._by_id[cmd.command_id]
    assert result.last_dispatch_outcome == "unavailable"
    assert result.hermes_mutation_count == 0
    assert adapter.submit_calls == 0
    assert command.state == "queued"
    assert command.last_error_code == "managed_session_registry_unavailable"


def test_pre_network_payload_failure_reports_zero_hermes_mutations() -> None:
    class PreNetworkFailureAdapter(FakeHermesDispatchAdapter):
        def submit_or_recover(self, request):  # type: ignore[no-untyped-def]
            self.submit_calls += 1
            return HermesDispatchResult(
                kind="rejected",
                error_code="payload_resolve_failed",
                network_attempted=False,
            )

    ledger = _ScriptedLedger(queue=[_cmd(client_request_id="req-v6-pre-network")])
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=PreNetworkFailureAdapter(),
        managed_session_resolver=lambda _command: "web_managed_pre_network",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    assert result.rejected_count == 1
    assert result.hermes_mutation_count == 0


def test_pre_network_unavailable_is_requeued_not_outcome_unknown() -> None:
    cmd = _cmd(client_request_id="req-v6-unavailable-before-network")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    adapter.next_fault = "unavailable"
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        managed_session_resolver=lambda _command: "web_managed_unavailable",
        claims_per_cycle=5,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    command = ledger._by_id[cmd.command_id]
    assert result.last_dispatch_outcome == "unavailable"
    assert result.dispatch_unknown_count == 0
    assert result.hermes_mutation_count == 0
    assert adapter.submit_calls == 1
    assert command.state == "queued"
    assert command.dispatch_started_at is None
    assert command.next_attempt_at is not None
    assert command.last_error_code == "durable_unavailable"


def test_pre_network_unavailable_retry_is_bounded_exponential() -> None:
    now = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)

    def dispatch_delay(*, previous_attempts: int, request_id: str) -> float:
        command = _cmd(
            client_request_id=request_id,
            attempt_count=previous_attempts,
        )
        ledger = _ScriptedLedger(queue=[command])
        adapter = FakeHermesDispatchAdapter(next_fault="unavailable")
        worker = HermesConnectorWorker(
            ledger=ledger,
            mode="supervised_dispatch",
            dispatch_adapter=adapter,
            managed_session_resolver=lambda _command: "web_managed_backoff",
            now=lambda: now,
        )
        worker.run_once()
        retry_at = ledger._by_id[command.command_id].next_attempt_at
        assert retry_at is not None
        return (retry_at - now).total_seconds()

    first_delay = dispatch_delay(previous_attempts=0, request_id="retry-first")
    later_delay = dispatch_delay(previous_attempts=8, request_id="retry-later")

    assert 4.5 <= first_delay <= 5.5
    assert first_delay < later_delay <= 300


def test_gate_rejects_without_hermes_call() -> None:
    cmd = _cmd()
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        dispatch_gate=lambda _c: DispatchGateDecision(allow=False, reason="kill_switch"),
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    result = worker.run_once()
    assert result.claimed_count == 1
    assert result.rejected_count == 1
    assert adapter.submit_calls == 0
    assert ledger.rejected[0][1] == "kill_switch"


def test_retryable_release_probe_failure_requeues_without_hermes_call() -> None:
    cmd = _cmd(client_request_id="req-release-probe-temporary")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        dispatch_gate=lambda _c: DispatchGateDecision(
            allow=False,
            reason="release_gate_unavailable",
            retryable=True,
        ),
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    command = ledger._by_id[cmd.command_id]
    assert result.claimed_count == 1
    assert result.rejected_count == 0
    assert result.last_dispatch_outcome == "unavailable"
    assert result.hermes_mutation_count == 0
    assert result.provider_call_count == 0
    assert adapter.submit_calls == 0
    assert command.state == "queued"
    assert command.dispatch_started_at is None
    assert command.last_error_code == "release_gate_unavailable"
    assert command.next_attempt_at is not None


def test_release_probe_exception_requeues_without_hermes_call() -> None:
    cmd = _cmd(client_request_id="req-release-probe-exception")
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()

    def unavailable_gate(_command):
        raise RuntimeError("database password and Hermes key")

    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        dispatch_gate=unavailable_gate,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )

    result = worker.run_once()

    command = ledger._by_id[cmd.command_id]
    assert result.last_dispatch_outcome == "unavailable"
    assert adapter.submit_calls == 0
    assert command.state == "queued"
    assert command.last_error_code == "dispatch_gate_unavailable"
    assert "password" not in repr(result)


def test_timeout_becomes_outcome_unknown_no_blind_retry_in_same_cycle() -> None:
    cmd = _cmd()
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    adapter.next_fault = "timeout"
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        claims_per_cycle=5,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    result = worker.run_once()
    assert result.claimed_count == 1  # only one queued command
    assert result.dispatch_unknown_count == 1
    assert result.delivered_count == 0
    assert ledger._by_id[cmd.command_id].state == "outcome_unknown"
    # outcome_unknown is not re-claimable from this ledger queue
    assert adapter.submit_calls == 1


def test_rejected_upstream_is_terminal_failed() -> None:
    cmd = _cmd()
    ledger = _ScriptedLedger(queue=[cmd])
    adapter = FakeHermesDispatchAdapter()
    adapter.next_fault = "rejected"
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    result = worker.run_once()
    assert result.rejected_count == 1
    assert ledger._by_id[cmd.command_id].state == "failed"
    assert ledger._by_id[cmd.command_id].last_error_code == "upstream_rejected"


def test_accept_drop_ack_then_recover_same_run() -> None:
    """Crash matrix: Hermes accepted, ack lost → timeout; recover by identity."""
    adapter = FakeHermesDispatchAdapter()
    req = HermesDispatchRequest(
        command_id=str(uuid4()),
        kind="research_chat",
        client_request_id="req-recover-1",
        platform_session_id="ps-1",
        canonical_request_digest="d" * 64,
        payload_ref="platform-payload://sha256/" + ("e" * 64),
    )
    adapter.next_fault = "accept_drop_ack"
    first = adapter.submit_or_recover(req)
    assert first.kind == "timeout"
    # Server-side Run exists; recover without creating a second Run.
    second = adapter.submit_or_recover(req)
    assert second.kind == "recovered"
    assert second.hermes_run_id is not None
    assert second.hermes_run_id.startswith("run_")
    # Third call still same identity
    third = adapter.submit_or_recover(req)
    assert third.hermes_run_id == second.hermes_run_id
    assert adapter.submit_calls == 3


def test_crash_after_claim_before_dispatch_started_leaves_leased() -> None:
    """Crash matrix point: PG claim commit 后 / Hermes submit 前 (no dispatch_started)."""
    cmd = _cmd()
    ledger = _ScriptedLedger(queue=[cmd], fail_on="after_claim_before_dispatch_started")
    adapter = FakeHermesDispatchAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    # Manually simulate: claim only, then "crash" before mark_dispatch_started.
    claimed = ledger.claim_next_command(
        worker_id="worker-v5",
        now=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    assert claimed.state == "leased"
    assert adapter.submit_calls == 0
    assert ledger.started == []
    # Worker cycle after crash with empty queue does nothing to Hermes.
    result = worker.run_once()
    assert result.hermes_mutation_count == 0
    assert adapter.submit_calls == 0


def test_crash_after_hermes_before_pg_link_records_unknown_via_exception_path() -> None:
    """Crash matrix: Hermes 已接受但回包/PG link 前失败 → outcome_unknown."""
    cmd = _cmd()
    ledger = _ScriptedLedger(queue=[cmd], fail_on="after_hermes_before_pg_link")
    adapter = FakeHermesDispatchAdapter()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=adapter,
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    result = worker.run_once()

    assert result.dispatch_unknown_count == 1
    assert adapter.submit_calls == 1
    assert ledger._by_id[cmd.command_id].state == "leased"


def test_idempotent_recover_after_delivered_does_not_create_second_run() -> None:
    adapter = FakeHermesDispatchAdapter()
    req = HermesDispatchRequest(
        command_id=str(uuid4()),
        kind="research_chat",
        client_request_id="req-once",
        platform_session_id="ps",
        canonical_request_digest="f" * 64,
        payload_ref="platform-payload://sha256/" + ("1" * 64),
    )
    a = adapter.submit_or_recover(req)
    b = adapter.submit_or_recover(req)
    assert a.kind == "accepted"
    assert b.kind == "recovered"
    assert a.hermes_run_id == b.hermes_run_id


def test_reconcile_only_still_default_and_ignores_queue() -> None:
    ledger = _ScriptedLedger(queue=[_cmd()])
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="reconcile_only",
        now=lambda: datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
    )
    result = worker.run_once()
    assert result.mode == "reconcile_only"
    assert result.claimed_count == 0
    assert ledger.claim_calls == 0
    assert ledger.reconcile_calls == 1


# ---------------------------------------------------------------------------
# PostgreSQL integration crash matrix (requires QS_TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


def _pg_settings() -> Settings:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=url,
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )


def _reset_ledger(database: db.Database) -> None:
    with database.connect() as conn, conn.transaction():
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_workflow_bindings DISABLE TRIGGER USER"
        )
        conn.execute("ALTER TABLE quant_system.hermes_command_events DISABLE TRIGGER USER")
        conn.execute("ALTER TABLE quant_system.hermes_run_links DISABLE TRIGGER USER")
        conn.execute(
            """
            TRUNCATE TABLE
                quant_system.hermes_command_workflow_bindings,
                quant_system.hermes_run_links,
                quant_system.hermes_outbox,
                quant_system.hermes_command_events,
                quant_system.hermes_commands
            RESTART IDENTITY
            """
        )
        for trigger_name in (
            "trg_hermes_workflow_binding_validate",
            "trg_hermes_workflow_binding_append_only",
            "trg_hermes_workflow_binding_append_only_truncate",
        ):
            conn.execute(
                "ALTER TABLE quant_system.hermes_command_workflow_bindings "
                f"ENABLE ALWAYS TRIGGER {trigger_name}"
            )
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_events "
            "ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_command_events "
            "ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only_truncate"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links "
            "ENABLE ALWAYS TRIGGER trg_hermes_run_links_append_only"
        )
        conn.execute(
            "ALTER TABLE quant_system.hermes_run_links "
            "ENABLE ALWAYS TRIGGER trg_hermes_run_links_append_only_truncate"
        )


def _bound_command(
    *,
    settings: Settings,
    ledger: HermesCommandLedger,
    platform_session_id: str,
    client_request_id: str,
    digest_char: str = "7",
):
    seed = hashlib.sha256(f"{platform_session_id}\0{client_request_id}".encode()).hexdigest()
    payload_digest = hashlib.sha256(f"payload:{seed}".encode()).hexdigest()
    draft = PreparedWorkflowCommand(
        schema_version="1.0",
        workflow_saga_id=f"hqs_{seed[:24]}",
        owner_user_id=UUID("00000000-0000-0000-0000-000000000001"),
        platform_session_id=platform_session_id,
        client_request_id=client_request_id,
        command_kind="research_chat",
        canonical_request_digest=digest_char * 64,
        payload_ref=f"hqa-payload:sha256:{payload_digest}",
        payload_digest=payload_digest,
        payload_expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        provider_policy_digest=hashlib.sha256(f"provider:{seed}".encode()).hexdigest(),
        task_id=f"hqt_{seed[:24]}",
        task_version=1,
        attempt_id=f"hqa_{seed[:24]}",
        attempt_number=1,
        prepared_event_id=f"hqe_{seed[:24]}",
        prepared_event_digest=hashlib.sha256(f"event:{seed}".encode()).hexdigest(),
        plan_schema_version=1,
        plan_version=1,
        plan_digest=hashlib.sha256(f"plan:{seed}".encode()).hexdigest(),
        workflow_preparation_digest="0" * 64,
    )
    prepared = replace(
        draft,
        workflow_preparation_digest=workflow_preparation_digest(draft),
    )
    result = ensure_bound_command(settings, prepared)
    return ledger.get_command(result.command_id)


def test_pg_supervised_happy_path_delivers_and_links_run() -> None:
    settings = _pg_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_ledger(database)
    ledger = HermesCommandLedger(settings)
    adapter = FakeHermesDispatchAdapter()
    now = datetime(2026, 7, 21, 15, 0, tzinfo=UTC)

    try:
        created = _bound_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-v5-happy",
            client_request_id="req-v5-pg-happy-001",
        )
        worker = HermesConnectorWorker(
            ledger=ledger,
            mode="supervised_dispatch",
            dispatch_adapter=adapter,
            worker_id="worker-v5-pg",
            now=lambda: now,
        )
        result = worker.run_once()
        assert result.mode == "supervised_dispatch"
        assert result.claimed_count == 1
        assert result.delivered_count == 1
        assert result.hermes_mutation_count == 1
        assert result.provider_call_count == 0
        assert result.last_dispatch_outcome == "delivered"
        assert adapter.submit_calls == 1

        final = ledger.get_command(created.command_id)
        assert final.state == "delivered"
        assert final.hermes_session_id is not None
        assert final.hermes_run_id is not None
        assert final.hermes_session_id.startswith("sess_")
        assert final.hermes_run_id.startswith("run_")
        assert final.lease_token is None
        assert final.dispatch_started_at is not None

        # Delivery binds Hermes IDs on the command row; hermes_run_links is a
        # separate exact resource-link primitive (not auto-written by mark_delivered).
        with database.connect() as conn:
            delivered_event = conn.execute(
                """
                SELECT event_type, to_state, hermes_session_id, hermes_run_id
                FROM quant_system.hermes_command_events
                WHERE command_id = %s AND event_type = 'command_delivered'
                ORDER BY command_version DESC
                LIMIT 1
                """,
                (created.command_id,),
            ).fetchone()
        assert delivered_event is not None
        assert delivered_event[0] == "command_delivered"
        assert delivered_event[1] == "delivered"
        assert delivered_event[2] == final.hermes_session_id
        assert delivered_event[3] == final.hermes_run_id

        # Empty second cycle: zero Hermes / zero provider.
        result2 = worker.run_once()
        assert result2.claimed_count == 0
        assert adapter.submit_calls == 1
    finally:
        _reset_ledger(database)
        db.reset_database_cache()


def test_pg_timeout_is_outcome_unknown_and_not_reclaimed() -> None:
    settings = _pg_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_ledger(database)
    ledger = HermesCommandLedger(settings)
    adapter = FakeHermesDispatchAdapter()
    adapter.next_fault = "timeout"
    now = datetime(2026, 7, 21, 15, 10, tzinfo=UTC)

    try:
        created = _bound_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-v5-timeout",
            client_request_id="req-v5-pg-timeout-001",
            digest_char="8",
        )
        worker = HermesConnectorWorker(
            ledger=ledger,
            mode="supervised_dispatch",
            dispatch_adapter=adapter,
            worker_id="worker-v5-timeout",
            now=lambda: now,
            claims_per_cycle=5,
        )
        result = worker.run_once()
        assert result.claimed_count == 1
        assert result.dispatch_unknown_count == 1
        assert result.delivered_count == 0

        final = ledger.get_command(created.command_id)
        assert final.state == "outcome_unknown"
        assert final.last_error_code == "hermes_response_timeout"

        # Same cycle / next cycle cannot reclaim outcome_unknown.
        result2 = worker.run_once()
        assert result2.claimed_count == 0
        assert adapter.submit_calls == 1
    finally:
        _reset_ledger(database)
        db.reset_database_cache()


def test_pg_gate_reject_never_calls_hermes() -> None:
    settings = _pg_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_ledger(database)
    ledger = HermesCommandLedger(settings)
    adapter = FakeHermesDispatchAdapter()
    now = datetime(2026, 7, 21, 15, 20, tzinfo=UTC)

    try:
        created = _bound_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-v5-gate",
            client_request_id="req-v5-pg-gate-001",
            digest_char="9",
        )
        worker = HermesConnectorWorker(
            ledger=ledger,
            mode="supervised_dispatch",
            dispatch_adapter=adapter,
            dispatch_gate=lambda _c: DispatchGateDecision(
                allow=False, reason="paper_only_gate"
            ),
            worker_id="worker-v5-gate",
            now=lambda: now,
        )
        result = worker.run_once()
        assert result.claimed_count == 1
        assert result.rejected_count == 1
        assert adapter.submit_calls == 0
        final = ledger.get_command(created.command_id)
        assert final.state == "failed"
        assert final.last_error_code == "paper_only_gate"
    finally:
        _reset_ledger(database)
        db.reset_database_cache()


def test_pg_accept_drop_ack_then_recover_same_run_identity() -> None:
    """Crash matrix: Hermes accepted / ack lost → timeout; recover by key."""
    settings = _pg_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_ledger(database)
    ledger = HermesCommandLedger(settings)
    adapter = FakeHermesDispatchAdapter()
    now = datetime(2026, 7, 21, 15, 30, tzinfo=UTC)

    try:
        # First command: accept_drop_ack → outcome_unknown, Run lives in adapter.
        created = _bound_command(
            settings=settings,
            ledger=ledger,
            platform_session_id="platform-session-v5-recover",
            client_request_id="req-v5-pg-recover-001",
            digest_char="a",
        )
        adapter.next_fault = "accept_drop_ack"
        worker = HermesConnectorWorker(
            ledger=ledger,
            mode="supervised_dispatch",
            dispatch_adapter=adapter,
            worker_id="worker-v5-recover",
            now=lambda: now,
        )
        first = worker.run_once()
        assert first.dispatch_unknown_count == 1
        unknown = ledger.get_command(created.command_id)
        assert unknown.state == "outcome_unknown"
        assert adapter.submit_calls == 1

        # Recover identity via adapter without a second Run (unit-level proof).
        # Worker does not auto-reclaim outcome_unknown — recovery is explicit.
        req = HermesDispatchRequest(
            command_id=str(created.command_id),
            kind=created.kind,
            client_request_id=created.client_request_id,
            platform_session_id=created.platform_session_id,
            canonical_request_digest=created.canonical_request_digest,
            payload_ref=created.payload_ref,
            provider_policy_digest=created.provider_policy_digest,
        )
        recovered = adapter.submit_or_recover(req)
        assert recovered.kind == "recovered"
        assert recovered.hermes_run_id is not None
        assert recovered.hermes_run_id.startswith("run_")
        # Same key again still same Run
        again = adapter.submit_or_recover(req)
        assert again.hermes_run_id == recovered.hermes_run_id
        assert adapter.submit_calls == 3
    finally:
        _reset_ledger(database)
        db.reset_database_cache()


def test_pg_empty_queue_zero_provider_and_hermes() -> None:
    settings = _pg_settings()
    db.reset_database_cache()
    database = db.get_database(settings)
    assert database is not None
    db.run_migrations(database)
    _reset_ledger(database)
    ledger = HermesCommandLedger(settings)
    adapter = FakeHermesDispatchAdapter()

    try:
        worker = HermesConnectorWorker(
            ledger=ledger,
            mode="supervised_dispatch",
            dispatch_adapter=adapter,
            worker_id="worker-v5-empty",
            now=lambda: datetime(2026, 7, 21, 16, 0, tzinfo=UTC),
        )
        result = worker.run_once()
        assert result.claimed_count == 0
        assert result.hermes_mutation_count == 0
        assert result.provider_call_count == 0
        assert adapter.submit_calls == 0
    finally:
        _reset_ledger(database)
        db.reset_database_cache()
