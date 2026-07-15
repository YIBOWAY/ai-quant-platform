"""JSON-lines CLI for the deterministic, reconcile-only Hermes connector."""

from __future__ import annotations

import json
import signal
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Annotated

import typer

from quant_system.config.settings import load_settings
from quant_system.hermes.command_ledger import (
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
)
from quant_system.hermes.connector_worker import (
    CommandWakeupWaiter,
    HermesConnectorCycleResult,
    HermesConnectorWorker,
    PostgresCommandWakeupWaiter,
)
from quant_system.storage.database import DatabaseUnavailable, get_database


class ConnectorRuntimeUnavailable(RuntimeError):
    """Raised when the durable command authority cannot host the worker."""


@dataclass(frozen=True)
class ConnectorRuntime:
    worker: HermesConnectorWorker
    wakeup_waiter: CommandWakeupWaiter
    stop_requested: Callable[[], bool]
    request_stop: Callable[[], None] = lambda: None


def build_connector_runtime(*, reconcile_limit: int = 100) -> ConnectorRuntime:
    """Build a provider-free worker from the configured PostgreSQL authority."""
    settings = load_settings()
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
    return ConnectorRuntime(
        worker=HermesConnectorWorker(
            ledger=HermesCommandLedger(settings),
            capability_probe=None,
            reconcile_limit=reconcile_limit,
        ),
        wakeup_waiter=waiter,
        stop_requested=stop_event.is_set,
        request_stop=stop_event.set,
    )


def _emit_cycle(result: HermesConnectorCycleResult) -> None:
    typer.echo(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))


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
) -> None:
    """Run the provider-free connector framework and stream JSON cycle facts."""
    if once and max_cycles is not None:
        raise typer.BadParameter("--max-cycles cannot be combined with --once")

    runtime: ConnectorRuntime | None = None
    try:
        runtime = build_connector_runtime(reconcile_limit=reconcile_limit)
        with _graceful_stop_signals(runtime):
            if once:
                _emit_cycle(runtime.worker.run_once())
                return
            for result in runtime.worker.iter_cycles(
                wakeup_waiter=runtime.wakeup_waiter,
                poll_interval_seconds=poll_interval_seconds,
                max_cycles=max_cycles,
                stop_requested=runtime.stop_requested,
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
                    "mode": "reconcile_only",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        raise typer.Exit(code=1) from None
    finally:
        if runtime is not None:
            close = getattr(runtime.wakeup_waiter, "close", None)
            if callable(close):
                close()


__all__ = [
    "ConnectorRuntime",
    "ConnectorRuntimeUnavailable",
    "build_connector_runtime",
    "hermes_app",
]
