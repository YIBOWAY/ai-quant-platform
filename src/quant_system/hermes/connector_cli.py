"""JSON-lines CLI for the deterministic Hermes connector worker."""

from __future__ import annotations

import json
import signal
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import typer

from quant_system.config.settings import load_settings
from quant_system.hermes.command_ledger import (
    HermesCommandConflict,
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesCommandNotFound,
    HermesCommandValidationError,
)
from quant_system.hermes.connector_worker import (
    CommandWakeupWaiter,
    HermesConnectorCycleResult,
    HermesConnectorWorker,
    PostgresCommandWakeupWaiter,
)
from quant_system.hermes.workflow_binding import (
    PreparedWorkflowCommand,
    ensure_bound_command,
    get_workflow_binding_by_saga,
    iter_workflow_binding_inventory,
    workflow_binding_to_dict,
)
from quant_system.storage.database import DatabaseUnavailable, get_database


class ConnectorRuntimeUnavailable(RuntimeError):
    """Raised when the durable command authority cannot host the worker."""


class WorkflowBindingInputError(ValueError):
    """Raised for a malformed metadata-only receipt without echoing its body."""


@dataclass(frozen=True)
class ConnectorRuntime:
    worker: HermesConnectorWorker
    wakeup_waiter: CommandWakeupWaiter
    stop_requested: Callable[[], bool]
    request_stop: Callable[[], None] = lambda: None


def build_connector_runtime(
    *,
    reconcile_limit: int = 100,
    mode: str = "reconcile_only",
    worker_id: str = "connector-worker-1",
    dispatch_adapter=None,
    run_lifecycle_port=None,
    managed_session_resolver=None,
) -> ConnectorRuntime:
    """Build a worker from the configured PostgreSQL authority.

    Default mode remains ``reconcile_only`` (no claim/dispatch). Pass
    ``mode="supervised_dispatch"`` to build the real loopback Hermes adapter
    from settings (or inject ``dispatch_adapter`` for tests).
    """
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
    worker_kwargs: dict = {
        "ledger": HermesCommandLedger(settings),
        "capability_probe": None,
        "reconcile_limit": reconcile_limit,
        "mode": mode,
        "worker_id": worker_id,
    }
    if mode == "supervised_dispatch":
        from quant_system.hermes.intent_payload_port import (
            IntentPayloadPortError,
            intent_payload_input_resolver,
        )
        from quant_system.hermes.run_lifecycle_port import (
            HermesRunPortError,
            build_subprocess_run_lifecycle_port,
        )
        from quant_system.hermes.session_registry import (
            require_web_writable_session,
        )

        if dispatch_adapter is None:
            try:
                input_resolver = intent_payload_input_resolver(settings)
                run_lifecycle_port = build_subprocess_run_lifecycle_port(
                    settings,
                    input_resolver=input_resolver,
                )
                dispatch_adapter = run_lifecycle_port
            except (HermesRunPortError, IntentPayloadPortError) as exc:
                raise ConnectorRuntimeUnavailable(
                    "Hermes durable Run port is misconfigured"
                ) from exc
        elif run_lifecycle_port is None and callable(
            getattr(dispatch_adapter, "observe", None)
        ):
            run_lifecycle_port = dispatch_adapter

        active_session_resolver = managed_session_resolver
        if active_session_resolver is None:
            def _resolve_managed_session(command):
                record = require_web_writable_session(
                    settings,
                    platform_session_id=command.platform_session_id,
                )
                if not record.hermes_session_id.startswith("web_"):
                    raise ConnectorRuntimeUnavailable(
                        "managed Hermes session identity is invalid"
                    )
                return record.hermes_session_id

            active_session_resolver = _resolve_managed_session

        worker_kwargs["dispatch_adapter"] = dispatch_adapter
        worker_kwargs["run_lifecycle_port"] = run_lifecycle_port
        worker_kwargs["managed_session_resolver"] = active_session_resolver
        worker_kwargs["capability_probe"] = dispatch_adapter.capabilities
    return ConnectorRuntime(
        worker=HermesConnectorWorker(**worker_kwargs),
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

workflow_binding_app = typer.Typer(
    help="Persist or inspect the exact metadata-only HQA workflow binding.",
    no_args_is_help=True,
)
hermes_app.add_typer(workflow_binding_app, name="workflow-binding")

_WORKFLOW_BINDING_STDIN_LIMIT = 16 * 1024
_PG_BIGINT_MAX = 9_223_372_036_854_775_807
_PG_INTEGER_MAX = 2_147_483_647
_PREPARED_STRING_FIELDS = frozenset(
    {
        "schema_version",
        "workflow_saga_id",
        "owner_user_id",
        "platform_session_id",
        "client_request_id",
        "command_kind",
        "canonical_request_digest",
        "payload_ref",
        "payload_digest",
        "payload_expires_at",
        "provider_policy_digest",
        "task_id",
        "attempt_id",
        "prepared_event_id",
        "prepared_event_digest",
        "plan_digest",
        "workflow_preparation_digest",
    }
)
_PREPARED_INTEGER_FIELDS = frozenset(
    {
        "task_version",
        "attempt_number",
        "plan_schema_version",
        "plan_version",
    }
)
_PREPARED_FIELDS = _PREPARED_STRING_FIELDS | _PREPARED_INTEGER_FIELDS


def _reject_json_constant(_value: str) -> object:
    raise WorkflowBindingInputError("non-finite JSON number")


def _bounded_json_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if len(digits) > 19:
        raise WorkflowBindingInputError("JSON integer exceeds the receipt bound")
    return int(value)


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise WorkflowBindingInputError("duplicate JSON field")
        result[key] = value
    return result


def _read_prepared_workflow_command() -> PreparedWorkflowCommand:
    stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw = stream.read(_WORKFLOW_BINDING_STDIN_LIMIT + 1)
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not raw or len(raw) > _WORKFLOW_BINDING_STDIN_LIMIT:
        raise WorkflowBindingInputError("empty or oversized receipt")
    try:
        text = raw.decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
            parse_int=_bounded_json_integer,
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise WorkflowBindingInputError("invalid receipt JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _PREPARED_FIELDS:
        raise WorkflowBindingInputError("receipt fields do not match the contract")
    if any(type(payload[field]) is not str for field in _PREPARED_STRING_FIELDS):
        raise WorkflowBindingInputError("receipt string field has the wrong type")
    if any(type(payload[field]) is not int for field in _PREPARED_INTEGER_FIELDS):
        raise WorkflowBindingInputError("receipt integer field has the wrong type")
    if not 1 <= int(payload["task_version"]) <= _PG_BIGINT_MAX:
        raise WorkflowBindingInputError("task_version is outside PostgreSQL bigint")
    if not 1 <= int(payload["attempt_number"]) <= _PG_INTEGER_MAX:
        raise WorkflowBindingInputError("attempt_number is outside PostgreSQL integer")
    if int(payload["plan_schema_version"]) != 1:
        raise WorkflowBindingInputError("plan_schema_version is unsupported")
    if not 1 <= int(payload["plan_version"]) <= _PG_BIGINT_MAX:
        raise WorkflowBindingInputError("plan_version is outside PostgreSQL bigint")

    owner_text = str(payload["owner_user_id"])
    timestamp_text = str(payload["payload_expires_at"])
    try:
        owner_user_id = UUID(owner_text)
        if str(owner_user_id) != owner_text:
            raise ValueError("owner UUID is not canonical")
        payload_expires_at = datetime.strptime(
            timestamp_text,
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=UTC)
        canonical_timestamp = payload_expires_at.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
        if canonical_timestamp != timestamp_text:
            raise ValueError("expiry timestamp is not canonical")
    except ValueError as exc:
        raise WorkflowBindingInputError("invalid UUID or timestamp") from exc

    return PreparedWorkflowCommand(
        schema_version=str(payload["schema_version"]),
        workflow_saga_id=str(payload["workflow_saga_id"]),
        owner_user_id=owner_user_id,
        platform_session_id=str(payload["platform_session_id"]),
        client_request_id=str(payload["client_request_id"]),
        command_kind=str(payload["command_kind"]),
        canonical_request_digest=str(payload["canonical_request_digest"]),
        payload_ref=str(payload["payload_ref"]),
        payload_digest=str(payload["payload_digest"]),
        payload_expires_at=payload_expires_at,
        provider_policy_digest=str(payload["provider_policy_digest"]),
        task_id=str(payload["task_id"]),
        task_version=int(payload["task_version"]),
        attempt_id=str(payload["attempt_id"]),
        attempt_number=int(payload["attempt_number"]),
        prepared_event_id=str(payload["prepared_event_id"]),
        prepared_event_digest=str(payload["prepared_event_digest"]),
        plan_schema_version=int(payload["plan_schema_version"]),
        plan_version=int(payload["plan_version"]),
        plan_digest=str(payload["plan_digest"]),
        workflow_preparation_digest=str(payload["workflow_preparation_digest"]),
    )


def _emit_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _workflow_binding_error(error_code: str, *, exit_code: int) -> None:
    _emit_json({"error_code": error_code})
    raise typer.Exit(code=exit_code)


@workflow_binding_app.command("ensure")
def workflow_binding_ensure_command() -> None:
    """Atomically persist one exact HQA receipt and queued platform command."""

    try:
        prepared = _read_prepared_workflow_command()
        result = ensure_bound_command(load_settings(), prepared)
    except (WorkflowBindingInputError, HermesCommandValidationError):
        _workflow_binding_error("workflow_binding_validation_failed", exit_code=2)
    except HermesCommandConflict:
        _workflow_binding_error("workflow_binding_conflict", exit_code=1)
    except (HermesCommandLedgerUnavailable, DatabaseUnavailable):
        _workflow_binding_error("workflow_binding_unavailable", exit_code=1)
    else:
        _emit_json(
            {
                "binding": workflow_binding_to_dict(result.binding),
                "command_id": str(result.command_id),
                "command_state": result.command_state,
                "command_version": result.command_version,
                "created": result.created,
            }
        )


@workflow_binding_app.command("show")
def workflow_binding_show_command(
    workflow_saga_id: Annotated[
        str,
        typer.Option(
            "--workflow-saga-id",
            help="Exact HQA saga identifier (hqs_<24 lowercase hex>).",
        ),
    ],
) -> None:
    """Read one immutable binding by its exact HQA saga identifier."""

    try:
        binding = get_workflow_binding_by_saga(load_settings(), workflow_saga_id)
    except HermesCommandValidationError:
        _workflow_binding_error("workflow_binding_validation_failed", exit_code=2)
    except HermesCommandNotFound:
        _workflow_binding_error("workflow_binding_not_found", exit_code=1)
    except (HermesCommandLedgerUnavailable, DatabaseUnavailable):
        _workflow_binding_error("workflow_binding_unavailable", exit_code=1)
    else:
        _emit_json({"binding": workflow_binding_to_dict(binding)})


@workflow_binding_app.command("inventory")
def workflow_binding_inventory_command() -> None:
    """Stream the complete immutable binding inventory as strict NDJSON."""

    try:
        for record in iter_workflow_binding_inventory(load_settings()):
            _emit_json(record)
    except Exception:  # noqa: BLE001 - CLI boundary must never leak DB or secret details
        typer.echo(
            json.dumps(
                {"error_code": "workflow_binding_inventory_unavailable"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            err=True,
        )
        raise typer.Exit(code=1) from None


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
        raise typer.BadParameter(
            "--mode must be reconcile_only or supervised_dispatch"
        )
    runtime: ConnectorRuntime | None = None
    try:
        runtime = build_connector_runtime(
            reconcile_limit=reconcile_limit,
            mode=mode,
            worker_id=worker_id,
        )
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
                    "mode": mode,
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
