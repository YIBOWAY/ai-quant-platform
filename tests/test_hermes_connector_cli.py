from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.hermes import connector_cli
from quant_system.hermes.connector_worker import HermesConnectorWorker

runner = CliRunner()


class _FakeLedger:
    def __init__(self) -> None:
        self.calls = 0
        self.claim_calls = 0
        self.limits: list[int] = []

    def reconcile_expired_leases(self, *, now, limit):
        self.calls += 1
        self.limits.append(limit)
        return SimpleNamespace(requeued=(), outcome_unknown=())

    # Supervised-dispatch surface (unused by reconcile-only fake cycles).
    def claim_next_command(self, *, worker_id, now, lease_duration):
        self.claim_calls += 1
        return None

    def mark_dispatch_started(self, **_kwargs):
        return None

    def mark_delivered(self, **_kwargs):
        return None

    def mark_dispatch_timeout(self, **_kwargs):
        return None

    def mark_dispatch_unavailable(self, **_kwargs):
        return None

    def mark_dispatch_rejected(self, **_kwargs):
        return None

    def heartbeat_lease(self, **_kwargs):
        return None


class _FakeWaiter:
    def __init__(self) -> None:
        self.waits: list[float] = []
        self.closed = False

    def wait(self, timeout_seconds: float) -> bool:
        self.waits.append(timeout_seconds)
        return False

    def close(self) -> None:
        self.closed = True


class _StopAfterFirstCycleLedger(_FakeLedger):
    def __init__(self, stop_event: threading.Event) -> None:
        super().__init__()
        self._stop_event = stop_event

    def reconcile_expired_leases(self, *, now, limit):
        result = super().reconcile_expired_leases(now=now, limit=limit)
        self._stop_event.set()
        return result


def test_connector_worker_once_outputs_one_provider_free_json_cycle(monkeypatch) -> None:
    ledger = _FakeLedger()
    waiter = _FakeWaiter()
    worker = HermesConnectorWorker(ledger=ledger)
    runtime = connector_cli.ConnectorRuntime(
        worker=worker,
        wakeup_waiter=waiter,
        stop_requested=lambda: False,
    )
    monkeypatch.setattr(
        connector_cli,
        "build_connector_runtime",
        lambda **_kwargs: runtime,
    )

    result = runner.invoke(app, ["hermes", "connector-worker", "--once"])

    assert result.exit_code == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "capability_read_status": "not_configured",
        "claimed_count": 0,
        "delivered_count": 0,
        "dispatch_unknown_count": 0,
        "hermes_mutation_count": 0,
        "last_command_id": None,
        "last_dispatch_outcome": None,
        "mode": "reconcile_only",
        "outcome_unknown_count": 0,
        "provider_call_count": 0,
        "recovered_count": 0,
        "rejected_count": 0,
        "requeued_count": 0,
        "terminal_count": 0,
        "session_provisioning": {"outcome": "not_configured"},
        "connector_liveness": {"status": "not_acquired"},
    }
    assert ledger.calls == 1
    assert waiter.waits == []
    assert waiter.closed is True


def test_connector_worker_loop_streams_json_and_scans_after_missed_notify(
    monkeypatch,
) -> None:
    ledger = _FakeLedger()
    waiter = _FakeWaiter()
    build_limits: list[int] = []

    def build_runtime(*, reconcile_limit: int = 100, **_kwargs):
        build_limits.append(reconcile_limit)
        return connector_cli.ConnectorRuntime(
            worker=HermesConnectorWorker(
                ledger=ledger,
                reconcile_limit=reconcile_limit,
            ),
            wakeup_waiter=waiter,
            stop_requested=lambda: False,
        )

    monkeypatch.setattr(connector_cli, "build_connector_runtime", build_runtime)

    result = runner.invoke(
        app,
        [
            "hermes",
            "connector-worker",
            "--poll-interval-seconds",
            "0.25",
            "--max-cycles",
            "2",
            "--reconcile-limit",
            "7",
        ],
    )

    assert result.exit_code == 0
    payloads = [json.loads(line) for line in result.stdout.strip().splitlines()]
    assert len(payloads) == 2
    assert all(payload["mode"] == "reconcile_only" for payload in payloads)
    assert all(payload["hermes_mutation_count"] == 0 for payload in payloads)
    assert all(payload["provider_call_count"] == 0 for payload in payloads)
    assert build_limits == [7]
    assert ledger.limits == [7, 7]
    assert waiter.waits == [0.25]
    assert waiter.closed is True


def test_connector_worker_loop_honors_cooperative_stop_before_waiting(
    monkeypatch,
) -> None:
    stop_event = threading.Event()
    ledger = _StopAfterFirstCycleLedger(stop_event)
    waiter = _FakeWaiter()
    runtime = connector_cli.ConnectorRuntime(
        worker=HermesConnectorWorker(ledger=ledger),
        wakeup_waiter=waiter,
        stop_requested=stop_event.is_set,
        request_stop=stop_event.set,
    )
    monkeypatch.setattr(
        connector_cli,
        "build_connector_runtime",
        lambda **_kwargs: runtime,
    )

    result = runner.invoke(app, ["hermes", "connector-worker"])

    assert result.exit_code == 0
    assert len(result.stdout.strip().splitlines()) == 1
    assert ledger.calls == 1
    assert waiter.waits == []
    assert waiter.closed is True


def test_connector_worker_reports_fail_closed_runtime_error_as_json(monkeypatch) -> None:
    def unavailable(**_kwargs):
        raise connector_cli.ConnectorRuntimeUnavailable("database URL omitted")

    monkeypatch.setattr(connector_cli, "build_connector_runtime", unavailable)

    result = runner.invoke(app, ["hermes", "connector-worker", "--once"])

    assert result.exit_code == 1
    assert json.loads(result.stdout) == {
        "error_code": "connector_runtime_unavailable",
        "mode": "reconcile_only",
    }
    assert "database URL omitted" not in result.stdout


def test_connector_worker_supervised_mode_is_forwarded(monkeypatch) -> None:
    captured: dict[str, object] = {}
    ledger = _FakeLedger()
    waiter = _FakeWaiter()

    def build_runtime(**kwargs):
        captured.update(kwargs)
        return connector_cli.ConnectorRuntime(
            worker=HermesConnectorWorker(
                ledger=ledger,
                mode="supervised_dispatch",
                dispatch_adapter=object(),  # type: ignore[arg-type]
            ),
            wakeup_waiter=waiter,
            stop_requested=lambda: False,
        )

    monkeypatch.setattr(connector_cli, "build_connector_runtime", build_runtime)

    result = runner.invoke(
        app,
        [
            "hermes",
            "connector-worker",
            "--once",
            "--mode",
            "supervised_dispatch",
            "--worker-id",
            "smoke-worker-1",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert captured["mode"] == "supervised_dispatch"
    assert captured["worker_id"] == "smoke-worker-1"
    payload = json.loads(result.stdout.strip().splitlines()[0])
    assert payload["mode"] == "supervised_dispatch"


def test_closed_network_gate_reconciles_without_claiming_a_queued_command() -> None:
    """A closed release/candidate gate must be checked before claim.

    The worker retains its per-command gate as the second half of the
    claim-to-network race defence, but a known-closed cycle must not lease and
    then reject a durable command merely because public release is not open.
    """

    ledger = _FakeLedger()
    worker = HermesConnectorWorker(
        ledger=ledger,
        mode="supervised_dispatch",
        dispatch_adapter=object(),  # type: ignore[arg-type]
    )
    runtime = connector_cli.ConnectorRuntime(
        worker=worker,
        wakeup_waiter=_FakeWaiter(),
        stop_requested=lambda: False,
        network_gate=lambda: connector_cli.DispatchGateDecision(
            allow=False,
            reason="active_release_stamp_missing",
            retryable=False,
        ),
    )

    result = runtime.run_once()

    assert result.cycle.mode == "supervised_dispatch"
    assert result.cycle.claimed_count == 0
    assert result.cycle.rejected_count == 0
    assert result.cycle.hermes_mutation_count == 0
    assert result.cycle.provider_call_count == 0
    assert result.session_provisioning == {"outcome": "not_configured"}
    assert ledger.calls == 1
    assert ledger.claim_calls == 0


def test_connector_worker_rejects_invalid_mode() -> None:
    result = runner.invoke(
        app,
        ["hermes", "connector-worker", "--once", "--mode", "not-a-mode"],
    )
    assert result.exit_code != 0


def test_connector_worker_rejects_prompt_bearing_fixed_input_option() -> None:
    result = runner.invoke(
        app,
        [
            "hermes",
            "connector-worker",
            "--once",
            "--mode",
            "supervised_dispatch",
            "--fixed-input",
            "hello",
        ],
    )
    assert result.exit_code != 0
    assert "No such option" in result.output
