from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from quant_system.hermes import connector_cli
from quant_system.hermes.connector_worker import (
    DispatchGateDecision,
    HermesConnectorCycleResult,
)
from quant_system.hermes.managed_session_provisioner import (
    ManagedSessionProvisionResult,
)


class _Waiter:
    def __init__(self) -> None:
        self.closed = False

    def wait(self, _timeout_seconds: float) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


class _Worker:
    mode = "supervised_dispatch"

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def run_once(self) -> HermesConnectorCycleResult:
        self.events.append("worker")
        return HermesConnectorCycleResult(
            mode=self.mode,
            requeued_count=0,
            outcome_unknown_count=0,
            capability_read_status="not_configured",
        )


class _Provisioner:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def provision_next(self, *, worker_id: str) -> ManagedSessionProvisionResult:
        assert worker_id == "daemon-1"
        self.events.append("provision")
        return ManagedSessionProvisionResult(
            outcome="ready",
            platform_session_id="wm_ready",
            hermes_session_id="web_" + ("a" * 40),
        )


class _Lease:
    def __init__(self, *, fail_heartbeat: bool = False) -> None:
        self.record = SimpleNamespace(
            generation_token="11111111-1111-4111-8111-111111111111",
            mode="supervised_dispatch",
            status="active",
        )
        self.fail_heartbeat = fail_heartbeat
        self.heartbeat_called = threading.Event()
        self.stop_reasons: list[str] = []

    def heartbeat(self, *, now):
        del now
        self.heartbeat_called.set()
        if self.fail_heartbeat:
            raise RuntimeError("lease lost")
        return self.record

    def stop(self, *, reason: str):
        self.stop_reasons.append(reason)
        if not self.fail_heartbeat:
            self.record.status = "stopped"
        return self.record


def _ready_gate() -> DispatchGateDecision:
    return DispatchGateDecision(allow=True, reason="ready")


def test_runtime_provisions_before_claim_and_projects_bounded_status() -> None:
    events: list[str] = []
    waiter = _Waiter()
    runtime = connector_cli.ConnectorRuntime(
        worker=_Worker(events),  # type: ignore[arg-type]
        wakeup_waiter=waiter,
        stop_requested=lambda: False,
        worker_id="daemon-1",
        provisioner=_Provisioner(events),  # type: ignore[arg-type]
        network_gate=_ready_gate,
    )

    cycle = runtime.run_once()

    assert events == ["provision", "worker"]
    assert cycle.session_provisioning == {
        "outcome": "ready",
        "platform_session_id": "wm_ready",
        "hermes_session_id": "web_" + ("a" * 40),
        "error_code": None,
    }
    assert cycle.connector_liveness == {"status": "not_acquired"}
    runtime.close(reason="test_complete")
    assert waiter.closed is True


def test_runtime_release_gate_blocks_session_network_before_worker_cycle() -> None:
    events: list[str] = []
    runtime = connector_cli.ConnectorRuntime(
        worker=_Worker(events),  # type: ignore[arg-type]
        wakeup_waiter=_Waiter(),
        stop_requested=lambda: False,
        worker_id="daemon-1",
        provisioner=_Provisioner(events),  # type: ignore[arg-type]
        network_gate=lambda: DispatchGateDecision(
            allow=False,
            reason="release_gate_closed",
        ),
    )

    cycle = runtime.run_once()

    assert events == ["worker"]
    assert cycle.session_provisioning == {
        "outcome": "blocked",
        "error_code": "release_gate_closed",
    }
    runtime.close(reason="test_complete")


def test_liveness_heartbeat_loss_requests_cooperative_stop() -> None:
    events: list[str] = []
    stop = threading.Event()
    lease = _Lease(fail_heartbeat=True)
    runtime = connector_cli.ConnectorRuntime(
        worker=_Worker(events),  # type: ignore[arg-type]
        wakeup_waiter=_Waiter(),
        stop_requested=stop.is_set,
        request_stop=stop.set,
        worker_id="daemon-1",
        liveness_lease=lease,  # type: ignore[arg-type]
        heartbeat_interval_seconds=0.01,
    )
    runtime.start_liveness_heartbeat()

    assert lease.heartbeat_called.wait(timeout=1)
    deadline = time.monotonic() + 1
    while not stop.is_set() and time.monotonic() < deadline:
        time.sleep(0.005)

    assert stop.is_set() is True
    assert runtime.liveness_projection()["status"] == "lease_lost"
    runtime.close(reason="heartbeat_lost")
    assert runtime.liveness_projection()["status"] == "stop_unconfirmed"


def test_supervised_builder_wires_one_durable_port_and_fresh_gate(
    monkeypatch,
) -> None:
    events: list[str] = []
    settings = SimpleNamespace(
        agent_v02_release=SimpleNamespace(
            workspace_id="workspace-root",
            connector_heartbeat_max_age_seconds=30.0,
        )
    )
    waiter = _Waiter()
    ledger = SimpleNamespace(reconcile_expired_leases=lambda **_kwargs: None)
    run_port = SimpleNamespace(cli_settings=object())
    session_port = object()
    provisioner = _Provisioner(events)
    lease = _Lease()
    release_calls: list[str] = []

    monkeypatch.setattr(connector_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(connector_cli, "get_database", lambda _settings: object())
    monkeypatch.setattr(
        connector_cli,
        "PostgresCommandWakeupWaiter",
        lambda **_kwargs: waiter,
    )
    monkeypatch.setattr(connector_cli, "HermesCommandLedger", lambda _settings: ledger)
    monkeypatch.setattr(
        connector_cli,
        "intent_payload_input_resolver",
        lambda _settings: lambda _request: "resolved",
    )
    monkeypatch.setattr(
        connector_cli,
        "build_subprocess_run_lifecycle_port",
        lambda _settings, *, input_resolver: run_port,
    )
    monkeypatch.setattr(
        connector_cli,
        "SubprocessManagedSessionProvisionPort",
        lambda *, cli_settings: session_port if cli_settings is run_port.cli_settings else None,
    )
    monkeypatch.setattr(
        connector_cli,
        "ManagedSessionProvisioner",
        lambda _settings, *, port: provisioner if port is session_port else None,
    )
    monkeypatch.setattr(
        connector_cli,
        "ConnectorLivenessAuthority",
        lambda _settings: SimpleNamespace(acquire=lambda **_kwargs: lease),
    )
    monkeypatch.setattr(connector_cli, "platform_runtime_root", lambda: object())
    monkeypatch.setattr(
        connector_cli,
        "git_runtime_digest",
        lambda _root, *, logical_name: "a" * 64,
    )

    def current_decision(_settings):
        release_calls.append("decision")
        return SimpleNamespace(chat_write_ready=True, blockers=())

    monkeypatch.setattr(connector_cli, "current_release_decision", current_decision)
    resolved_platform_ids: list[str] = []

    def require_session(_settings, *, platform_session_id: str):
        resolved_platform_ids.append(platform_session_id)
        return SimpleNamespace(hermes_session_id="web_" + ("b" * 40))

    monkeypatch.setattr(
        connector_cli,
        "require_web_writable_session",
        require_session,
    )

    runtime = connector_cli.build_connector_runtime(
        mode="supervised_dispatch",
        worker_id="daemon-1",
    )

    assert runtime.worker._dispatch_adapter is run_port  # noqa: SLF001
    assert runtime.worker._run_lifecycle_port is run_port  # noqa: SLF001
    assert runtime.provisioner is provisioner
    first = runtime.network_gate()
    second = runtime.network_gate()
    assert first.allow is True
    assert second.allow is True
    assert release_calls == ["decision", "decision"]
    resolved = runtime.worker._managed_session_resolver(  # noqa: SLF001
        SimpleNamespace(platform_session_id="wm_exact")
    )
    assert resolved == "web_" + ("b" * 40)
    assert resolved_platform_ids == ["wm_exact"]
    runtime.close(reason="test_complete")
    assert lease.stop_reasons == ["test_complete"]
