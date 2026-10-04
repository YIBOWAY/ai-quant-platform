"""JSON-lines CLI for the deterministic Hermes connector worker."""

from __future__ import annotations

import json
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated

import typer

from quant_system.config.settings import load_settings
from quant_system.hermes.command_ledger import (
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
)
from quant_system.hermes.connector_liveness import (
    ConnectorLivenessAuthority,
    ConnectorLivenessError,
    ConnectorLivenessLease,
)
from quant_system.hermes.connector_worker import (
    CommandWakeupWaiter,
    DispatchGateDecision,
    HermesConnectorCycleResult,
    HermesConnectorWorker,
    PostgresCommandWakeupWaiter,
)
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID
from quant_system.hermes.intent_payload_port import (
    IntentPayloadPortError,
    intent_payload_input_resolver,
)
from quant_system.hermes.local_trust import (
    trust_mode_active,
    trust_runtime_digest,
)
from quant_system.hermes.managed_session_provisioner import (
    ManagedSessionProvisioner,
    ManagedSessionProvisionResult,
    SubprocessManagedSessionProvisionPort,
)
from quant_system.hermes.release_cli import release_app
from quant_system.hermes.release_runtime import (
    ReleaseRuntimeProbeError,
    current_release_decision,
    git_runtime_digest,
    platform_runtime_root,
)
from quant_system.hermes.run_lifecycle_port import (
    HermesRunPortError,
    build_subprocess_run_lifecycle_port,
)
from quant_system.hermes.session_registry import require_web_writable_session
from quant_system.hermes.vertical_a_cli import app as vertical_a_app
from quant_system.storage.database import DatabaseUnavailable, get_database


class ConnectorRuntimeUnavailable(RuntimeError):
    """Raised when the durable command authority cannot host the worker."""


@dataclass(frozen=True)
class ConnectorRuntimeCycle:
    cycle: HermesConnectorCycleResult
    session_provisioning: dict[str, object]
    connector_liveness: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        document = asdict(self.cycle)
        document["session_provisioning"] = dict(self.session_provisioning)
        document["connector_liveness"] = dict(self.connector_liveness)
        return document


@dataclass
class ConnectorRuntime:
    worker: HermesConnectorWorker
    wakeup_waiter: CommandWakeupWaiter
    stop_requested: Callable[[], bool]
    request_stop: Callable[[], None] = lambda: None
    worker_id: str = "connector-worker-1"
    provisioner: ManagedSessionProvisioner | None = None
    network_gate: Callable[[], DispatchGateDecision] = lambda: DispatchGateDecision(
        allow=True,
        reason="ready",
    )
    compatibility_probe: Callable[[], object] | None = None
    compatibility_failure_limit: int = 3
    liveness_lease: ConnectorLivenessLease | None = None
    heartbeat_interval_seconds: float = 5.0
    _heartbeat_thread: threading.Thread | None = None
    _heartbeat_stop: threading.Event | None = None
    _liveness_state: str = "not_acquired"
    _compatibility_failures: int = 0
    _closed: bool = False

    def start_liveness_heartbeat(self) -> None:
        """Renew the daemon generation independently of slow Hermes calls."""

        if self.liveness_lease is None or self._heartbeat_thread is not None:
            return
        interval = float(self.heartbeat_interval_seconds)
        if not 0.005 <= interval <= 100:
            raise ValueError("heartbeat_interval_seconds must be in [0.005, 100]")
        stop = threading.Event()
        self._heartbeat_stop = stop
        self._liveness_state = "active"

        def _heartbeat() -> None:
            assert self.liveness_lease is not None
            while not stop.wait(interval):
                try:
                    self.liveness_lease.heartbeat(now=datetime.now(UTC))
                except Exception:  # noqa: BLE001 - lease loss is a closed runtime
                    self._liveness_state = "lease_lost"
                    self.request_stop()
                    return

        thread = threading.Thread(
            target=_heartbeat,
            name="agent-v02-connector-liveness-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread = thread
        thread.start()

    def liveness_projection(self) -> dict[str, object]:
        """Return bounded generation state; never include credentials or prompts."""

        lease = self.liveness_lease
        if lease is None:
            return {"status": "not_acquired"}
        record = lease.record
        return {
            "status": self._liveness_state,
            "mode": record.mode,
            "generation_token": record.generation_token,
        }

    def run_once(self) -> ConnectorRuntimeCycle:
        """Provision one due Session before any conversation-turn claim."""

        compatibility = self._compatibility_cycle_if_blocked()
        if compatibility is not None:
            return compatibility
        gate = DispatchGateDecision(allow=True, reason="ready")
        if self.worker.mode == "supervised_dispatch" or self.provisioner is not None:
            # First half of the two-stage dispatch gate: a known-closed
            # release/candidate cycle must never lease a durable command.
            # HermesConnectorWorker retains the fresh post-claim check.
            gate = self.network_gate()
        session_projection: dict[str, object] = {"outcome": "not_configured"}
        if self.provisioner is not None:
            if gate.allow:
                provisioned = self.provisioner.provision_next(
                    worker_id=self.worker_id,
                )
                session_projection = _provision_projection(provisioned)
            else:
                session_projection = {
                    "outcome": "blocked",
                    "error_code": _safe_runtime_code(gate.reason),
                }
        cycle = self.worker.run_once(dispatch_allowed=gate.allow)
        return ConnectorRuntimeCycle(
            cycle=cycle,
            session_provisioning=session_projection,
            connector_liveness=self.liveness_projection(),
        )

    def _compatibility_cycle_if_blocked(self) -> ConnectorRuntimeCycle | None:
        """Continuously verify HQA; never work through a failed real CLI probe."""

        probe = self.compatibility_probe
        if probe is None:
            return None
        try:
            probe()
        except Exception as exc:  # noqa: BLE001 - the boundary stays secret-free
            self._compatibility_failures += 1
            retryable = isinstance(exc, HermesRunPortError) and exc.retryable
            error_code = exc.code if isinstance(exc, HermesRunPortError) else "run_cli_unavailable"
            limit = self.compatibility_failure_limit if retryable else 1
            if self._compatibility_failures >= limit:
                self._liveness_state = "compatibility_lost"
                self.request_stop()
            cycle = HermesConnectorCycleResult(
                mode=self.worker.mode,
                requeued_count=0,
                outcome_unknown_count=0,
                capability_read_status=("unavailable" if retryable else "degraded"),
            )
            return ConnectorRuntimeCycle(
                cycle=cycle,
                session_provisioning={
                    "outcome": "blocked",
                    "error_code": _safe_runtime_code(error_code),
                },
                connector_liveness=self.liveness_projection(),
            )
        self._compatibility_failures = 0
        return None

    def iter_cycles(
        self,
        *,
        poll_interval_seconds: float,
        max_cycles: int | None,
    ) -> Iterator[ConnectorRuntimeCycle]:
        if not 0.05 <= poll_interval_seconds <= 3600:
            raise ValueError("poll_interval_seconds must be between 0.05 and 3600")
        if max_cycles is not None and (
            isinstance(max_cycles, bool) or not 1 <= max_cycles <= 1_000_000
        ):
            raise ValueError("max_cycles must be positive when provided")
        completed = 0
        while not self.stop_requested():
            yield self.run_once()
            completed += 1
            if max_cycles is not None and completed >= max_cycles:
                break
            if self.stop_requested():
                break
            self.wakeup_waiter.wait(poll_interval_seconds)

    def close(self, *, reason: str = "connector_runtime_closed") -> None:
        if self._closed:
            return
        self._closed = True
        heartbeat_stop = self._heartbeat_stop
        if heartbeat_stop is not None:
            heartbeat_stop.set()
        heartbeat_thread = self._heartbeat_thread
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=min(2.0, self.heartbeat_interval_seconds + 0.25))
        if self.liveness_lease is not None:
            try:
                stopped = self.liveness_lease.stop(reason=_safe_stop_reason(reason))
                self._liveness_state = (
                    "stopped" if stopped.status == "stopped" else "stop_unconfirmed"
                )
            except Exception:  # noqa: BLE001 - cleanup is already fail-closed
                self._liveness_state = "stop_unconfirmed"
        close = getattr(self.wakeup_waiter, "close", None)
        if callable(close):
            close()


def build_connector_runtime(
    *,
    reconcile_limit: int = 100,
    mode: str = "reconcile_only",
    worker_id: str = "connector-worker-1",
    dispatch_adapter=None,
) -> ConnectorRuntime:
    """Build a worker from the configured PostgreSQL authority.

    Default mode remains ``reconcile_only`` (no claim/dispatch). Pass
    ``mode="supervised_dispatch"`` to build the HQA subprocess port for the
    real durable Hermes Run authority.  The legacy HTTP adapter is never a
    production fallback; ``dispatch_adapter`` remains an explicit test seam.
    """
    settings = load_settings()
    if (
        mode == "supervised_dispatch"
        and settings.agent_v02_release.workspace_id != PLATFORM_WORKSPACE_ID
    ):
        raise ConnectorRuntimeUnavailable(
            "supervised connector release workspace does not match the Web Chat profile"
        )
    database = get_database(settings)
    if database is None:
        raise ConnectorRuntimeUnavailable(
            "PostgreSQL command authority is disabled or unconfigured"
        )
    stop_event = threading.Event()
    waiter = PostgresCommandWakeupWaiter(
        database=database,
        stop_requested=stop_event.is_set,
    )
    worker_kwargs: dict = {
        "capability_probe": None,
        "reconcile_limit": reconcile_limit,
        "mode": mode,
        "worker_id": worker_id,
    }
    provisioner: ManagedSessionProvisioner | None = None
    liveness_lease: ConnectorLivenessLease | None = None
    compatibility_probe: Callable[[], object] | None = None
    heartbeat_interval = 5.0
    claim_release_only = False

    if mode == "supervised_dispatch":
        try:
            initial_release = current_release_decision(settings)
        except Exception:  # noqa: BLE001 - exact admission is required below
            initial_release = None
        if (
            initial_release is not None and initial_release.chat_write_ready is True
        ) or trust_mode_active(settings):
            claim_release_only = True
        else:
            raise ConnectorRuntimeUnavailable("supervised connector has no active local release")

    worker_kwargs["ledger"] = HermesCommandLedger(
        settings,
        claim_candidate_admission_id=None,
        claim_release_only=claim_release_only,
    )

    def _network_gate() -> DispatchGateDecision:
        if stop_event.is_set():
            return DispatchGateDecision(
                allow=False,
                reason="connector_liveness_lost",
                retryable=True,
            )
        if claim_release_only and (
            getattr(getattr(settings, "local_trust", None), "mode", False) is True
        ):
            # Local trust mode: the gate is still consulted every cycle so a
            # live-trading red-line flip closes dispatch immediately.
            if not trust_mode_active(settings):
                return DispatchGateDecision(
                    allow=False,
                    reason="trust_mode_red_line",
                    retryable=False,
                )
            if settings.local_mutation.composer_open is not True:
                return DispatchGateDecision(
                    allow=False,
                    reason="local_composer_closed",
                    retryable=False,
                )
            return DispatchGateDecision(allow=True, reason="trust_ready")
        try:
            decision = current_release_decision(settings)
        except Exception:  # noqa: BLE001 - a failed release probe closes dispatch
            return DispatchGateDecision(
                allow=False,
                reason="release_gate_unavailable",
                retryable=True,
            )
        if decision.chat_write_ready is not True:
            blocker = decision.blockers[0] if decision.blockers else "release_gate_closed"
            return DispatchGateDecision(
                allow=False,
                reason=_safe_runtime_code(blocker),
                retryable=_release_blocker_is_retryable(blocker),
            )
        return DispatchGateDecision(allow=True, reason="ready")

    if mode == "supervised_dispatch":
        try:
            if dispatch_adapter is None:
                input_resolver = intent_payload_input_resolver(settings)
                run_port = build_subprocess_run_lifecycle_port(
                    settings,
                    input_resolver=input_resolver,
                )
                # The real HQA subprocess must prove the shared six-operation
                # contract before this generation may advertise liveness.
                run_port.require_compatible_capabilities()
                compatibility_probe = run_port.require_compatible_capabilities
                worker_kwargs["capability_probe"] = run_port.capabilities
                dispatch_adapter = run_port
                worker_kwargs["run_lifecycle_port"] = run_port
                session_port = (
                    run_port if getattr(run_port, "protocol", None) == "official-http-v1"
                    else SubprocessManagedSessionProvisionPort(cli_settings=run_port.cli_settings)
                )
                provisioner = ManagedSessionProvisioner(
                    settings,
                    port=session_port,
                )
            if trust_mode_active(settings):
                # Trust mode: no clean-checkout requirement; advertise the
                # synthetic trust identity that composer readiness expects.
                runtime_digest = trust_runtime_digest(settings)
            else:
                runtime_digest = git_runtime_digest(
                    platform_runtime_root(),
                    logical_name="platform",
                )
            liveness_lease = ConnectorLivenessAuthority(settings).acquire(
                workspace_id=settings.agent_v02_release.workspace_id,
                worker_id=worker_id,
                mode=mode,
                runtime_digest=runtime_digest,
            )
            max_age = float(settings.agent_v02_release.connector_heartbeat_max_age_seconds)
            heartbeat_interval = max(0.25, min(5.0, max_age / 3.0))
        except (
            ConnectorLivenessError,
            HermesRunPortError,
            IntentPayloadPortError,
            ReleaseRuntimeProbeError,
            ValueError,
        ) as exc:
            if liveness_lease is not None:
                with suppress(Exception):
                    liveness_lease.stop(reason="connector_runtime_build_failed")
            raise ConnectorRuntimeUnavailable(
                "supervised connector prerequisites are unavailable"
            ) from exc
        worker_kwargs["dispatch_adapter"] = dispatch_adapter
        worker_kwargs["dispatch_gate"] = lambda _command: _network_gate()
        worker_kwargs["managed_session_resolver"] = lambda command: (
            require_web_writable_session(
                settings,
                platform_session_id=command.platform_session_id,
            ).hermes_session_id
        )
    try:
        runtime = ConnectorRuntime(
            worker=HermesConnectorWorker(**worker_kwargs),
            wakeup_waiter=waiter,
            stop_requested=stop_event.is_set,
            request_stop=stop_event.set,
            worker_id=worker_id,
            provisioner=provisioner,
            network_gate=_network_gate,
            compatibility_probe=compatibility_probe,
            liveness_lease=liveness_lease,
            heartbeat_interval_seconds=heartbeat_interval,
        )
        runtime.start_liveness_heartbeat()
        return runtime
    except BaseException:
        if liveness_lease is not None:
            with suppress(Exception):
                liveness_lease.stop(reason="connector_runtime_build_failed")
        raise


def _safe_runtime_code(value: object) -> str:
    text = value if type(value) is str else "runtime_gate_closed"
    if not text or len(text) > 200 or any(not (char.isalnum() or char in "._:-") for char in text):
        return "runtime_gate_closed"
    return text


def _release_blocker_is_retryable(value: object) -> bool:
    """Preserve queued intent unless the release close/drift fact is definitive."""

    blocker = _safe_runtime_code(value)
    permanent = {
        "active_release_stamp_invalid",
        "active_release_stamp_missing",
        "database_schema_fingerprint_mismatch",
        "hermes_gateway_disabled",
        "local_composer_closed",
        "local_mutation_disabled",
        "open_public_cutover_missing",
        "public_cutover_release_binding_mismatch",
        "release_evidence_digest_mismatch",
        "release_gate_closed",
    }
    if blocker in permanent:
        return False
    if blocker.endswith("_runtime_identity_mismatch"):
        return False
    if blocker.startswith("hermes_feature_") and blocker.endswith("_unready"):
        return False
    if blocker.startswith("hermes_durable_") and (
        blocker.endswith("_unready") or blocker == "hermes_durable_contract_unavailable"
    ):
        return False
    return blocker not in {
        "hermes_managed_session_fork_mode_unready",
        "hermes_managed_session_history_authority_unready",
    }


def _safe_stop_reason(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "connector_runtime_closed"
    return normalized[:500]


def _provision_projection(
    result: ManagedSessionProvisionResult,
) -> dict[str, object]:
    """Project only bounded identifiers/status, never the CLI request body."""

    return {
        "outcome": result.outcome,
        "platform_session_id": result.platform_session_id,
        "hermes_session_id": result.hermes_session_id,
        "error_code": (
            _safe_runtime_code(result.error_code) if result.error_code is not None else None
        ),
    }


def _emit_cycle(result: ConnectorRuntimeCycle) -> None:
    typer.echo(
        json.dumps(
            result.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
    )


@contextmanager
def _graceful_stop_signals(runtime: ConnectorRuntime) -> Iterator[None]:
    """Translate process termination into the worker's cooperative stop flag."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous: dict[signal.Signals, signal.Handlers] = {}

    def request_stop(_signum: int, _frame: object) -> None:
        runtime.request_stop()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


hermes_app = typer.Typer(
    help="Operate the deterministic Hermes command connector.",
    no_args_is_help=True,
)

hermes_app.add_typer(release_app, name="release")
hermes_app.add_typer(vertical_a_app, name="vertical-a")


@hermes_app.command("connector-worker")
def connector_worker_command(
    once: Annotated[
        bool,
        typer.Option("--once", help="Run one local reconciliation cycle and exit."),
    ] = False,
    poll_interval_seconds: Annotated[
        float,
        typer.Option(
            "--poll-interval-seconds",
            min=0.05,
            max=3600.0,
            help="Periodic database scan interval used when notifications are absent.",
        ),
    ] = 30.0,
    max_cycles: Annotated[
        int | None,
        typer.Option(
            "--max-cycles",
            min=1,
            max=1_000_000,
            help="Stop a loop after this many cycles; omitted means run until signalled.",
        ),
    ] = None,
    reconcile_limit: Annotated[
        int,
        typer.Option(
            "--reconcile-limit",
            min=1,
            max=1000,
            help="Maximum expired local leases reconciled in one cycle.",
        ),
    ] = 100,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help=(
                "Worker mode: reconcile_only (default, no claim) or "
                "supervised_dispatch (claim + real Hermes adapter)."
            ),
        ),
    ] = "reconcile_only",
    worker_id: Annotated[
        str,
        typer.Option(
            "--worker-id",
            help="Stable worker identity written into lease rows.",
        ),
    ] = "connector-worker-1",
) -> None:
    """Run the connector framework and stream JSON cycle facts."""
    if once and max_cycles is not None:
        raise typer.BadParameter("--max-cycles cannot be combined with --once")
    if mode not in {"reconcile_only", "supervised_dispatch"}:
        raise typer.BadParameter("--mode must be reconcile_only or supervised_dispatch")

    runtime: ConnectorRuntime | None = None
    try:
        runtime = build_connector_runtime(
            reconcile_limit=reconcile_limit,
            mode=mode,
            worker_id=worker_id,
        )
        with _graceful_stop_signals(runtime):
            if once:
                _emit_cycle(runtime.run_once())
                return
            for result in runtime.iter_cycles(
                poll_interval_seconds=poll_interval_seconds,
                max_cycles=max_cycles,
            ):
                _emit_cycle(result)
    except (
        ConnectorRuntimeUnavailable,
        DatabaseUnavailable,
        HermesCommandLedgerUnavailable,
    ):
        typer.echo(
            json.dumps(
                {
                    "error_code": "connector_runtime_unavailable",
                    "mode": mode,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise typer.Exit(code=1) from None
    finally:
        if runtime is not None:
            runtime.close(reason="connector_process_exit")


__all__ = [
    "ConnectorRuntime",
    "ConnectorRuntimeCycle",
    "ConnectorRuntimeUnavailable",
    "build_connector_runtime",
    "hermes_app",
]
