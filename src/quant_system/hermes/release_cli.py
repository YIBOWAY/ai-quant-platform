"""Operator-only CLI for the durable Agent v0.2 release authority."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Protocol

import typer

from quant_system.config.settings import Settings, load_settings
from quant_system.hermes.effective_release_gate import (
    EffectiveReleaseDecision,
    RuntimeIdentityObservation,
)
from quant_system.hermes.release_authority import (
    RELEASE_ROUTE,
    ClosePublicCutoverRequest,
    CloseReleaseStampRequest,
    CreatePublicCutoverRequest,
    CreateReleaseStampRequest,
    PublicCutoverRecord,
    ReleaseAuthority,
    ReleaseAuthorityConflict,
    ReleaseAuthorityError,
    ReleaseAuthorityNotFound,
    ReleaseAuthorityReceipt,
    ReleaseStampRecord,
    canonical_release_action_digest,
)
from quant_system.hermes.release_runtime import (
    current_release_decision,
    file_sha256,
    runtime_identity_observation,
)
from quant_system.storage.database import get_database, schema_fingerprint

_CLI_CONTRACT = "agent-v0.2-release-cli/v1"


class ReleaseAuthorityPort(Protocol):
    """Release authority surface used by the operator CLI."""

    def active_release_stamp(
        self,
        workspace_id: str,
    ) -> ReleaseStampRecord | None: ...

    def open_public_cutover(
        self,
        workspace_id: str,
    ) -> PublicCutoverRecord | None: ...

    def current_event_cursor(self, workspace_id: str) -> int: ...

    def create_release_stamp(
        self,
        request: CreateReleaseStampRequest,
    ) -> ReleaseAuthorityReceipt: ...

    def create_public_cutover(
        self,
        request: CreatePublicCutoverRequest,
    ) -> ReleaseAuthorityReceipt: ...

    def close_public_cutover(
        self,
        request: ClosePublicCutoverRequest,
    ) -> ReleaseAuthorityReceipt: ...

    def close_release_stamp(
        self,
        request: CloseReleaseStampRequest,
    ) -> ReleaseAuthorityReceipt: ...


@dataclass(frozen=True)
class ReleaseCliRuntime:
    """Trusted local observations and durable authority used by one command."""

    settings: Settings
    authority: ReleaseAuthorityPort
    runtime_identity_probe: Callable[[], RuntimeIdentityObservation]
    schema_fingerprint_probe: Callable[[], str]
    evidence_digest_probe: Callable[[], str]
    status_probe: Callable[[], EffectiveReleaseDecision]


def build_release_cli_runtime() -> ReleaseCliRuntime:
    """Bind CLI operations to configured clean runtimes and the live database."""

    settings = load_settings()
    database = get_database(settings)
    if database is None:
        raise RuntimeError("durable release authority requires PostgreSQL")
    return ReleaseCliRuntime(
        settings=settings,
        authority=ReleaseAuthority(settings, database=database),
        runtime_identity_probe=lambda: runtime_identity_observation(settings),
        schema_fingerprint_probe=lambda: schema_fingerprint(database),
        evidence_digest_probe=lambda: file_sha256(settings.agent_v02_release.evidence_file),
        status_probe=lambda: current_release_decision(settings),
    )


def _emit_json(payload: dict[str, object]) -> None:
    typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _run_cli(operation: str, callback: Callable[[], None]) -> None:
    try:
        callback()
    except typer.Exit:
        raise
    except ReleaseAuthorityError as exc:
        _emit_json(
            {
                "contract": _CLI_CONTRACT,
                "error_code": exc.code,
                "operation": operation,
            }
        )
        raise typer.Exit(code=1) from None
    except Exception:  # noqa: BLE001 - never leak DB/path/credential details
        _emit_json(
            {
                "contract": _CLI_CONTRACT,
                "error_code": "release_cli_unavailable",
                "operation": operation,
            }
        )
        raise typer.Exit(code=1) from None


def _workspace_id(runtime: ReleaseCliRuntime) -> str:
    return runtime.settings.agent_v02_release.workspace_id


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _stamp_dict(stamp: ReleaseStampRecord | None) -> dict[str, object] | None:
    if stamp is None:
        return None
    return {
        "closed_at": _timestamp(stamp.closed_at),
        "database_schema_fingerprint": stamp.database_schema_fingerprint,
        "evidence_digest": stamp.evidence_digest,
        "hermes_runtime_digest": stamp.hermes_runtime_digest,
        "hqa_runtime_digest": stamp.hqa_runtime_digest,
        "opened_at": _timestamp(stamp.opened_at),
        "platform_runtime_digest": stamp.platform_runtime_digest,
        "release_digest": stamp.release_digest,
        "route": stamp.route,
        "stamp_id": stamp.stamp_id,
        "status": stamp.status,
        "workspace_id": stamp.workspace_id,
    }


def _cutover_dict(
    cutover: PublicCutoverRecord | None,
) -> dict[str, object] | None:
    if cutover is None:
        return None
    return {
        "closed_at": _timestamp(cutover.closed_at),
        "cutover_digest": cutover.cutover_digest,
        "cutover_id": cutover.cutover_id,
        "opened_at": _timestamp(cutover.opened_at),
        "release_digest": cutover.release_digest,
        "route": cutover.route,
        "stamp_id": cutover.stamp_id,
        "status": cutover.status,
        "workspace_id": cutover.workspace_id,
    }


def _receipt_dict(receipt: ReleaseAuthorityReceipt) -> dict[str, object]:
    return {
        "action_digest": receipt.action_digest,
        "client_action_id": receipt.client_action_id,
        "event_cursor": receipt.event_cursor,
        "idempotent_replay": receipt.idempotent_replay,
        "occurred_at": _timestamp(receipt.occurred_at),
        "operation": receipt.operation,
        "resource_digest": receipt.resource_digest,
        "resource_id": receipt.resource_id,
        "status": receipt.status,
        "workspace_id": receipt.workspace_id,
    }


def _require_preflight(
    decision: EffectiveReleaseDecision,
    *,
    allowed_blockers: frozenset[str],
) -> None:
    if set(decision.blockers) - allowed_blockers:
        _emit_json(
            {
                "blockers": list(decision.blockers),
                "contract": _CLI_CONTRACT,
                "error_code": "release_preflight_failed",
            }
        )
        raise typer.Exit(code=1)


def _emit_write_result(
    receipt: ReleaseAuthorityReceipt,
    runtime: ReleaseCliRuntime,
    *,
    allowed_post_blockers: frozenset[str] | None = None,
) -> None:
    try:
        decision = runtime.status_probe()
    except Exception:  # noqa: BLE001 - receipt must survive an observation outage
        _emit_json(
            {
                "contract": _CLI_CONTRACT,
                "error_code": "release_post_write_status_unavailable",
                "receipt": _receipt_dict(receipt),
            }
        )
        raise typer.Exit(code=1) from None
    if allowed_post_blockers is not None and set(decision.blockers) - allowed_post_blockers:
        _emit_json(
            {
                "contract": _CLI_CONTRACT,
                "decision": decision.to_public_dict(),
                "error_code": "release_post_write_gate_closed",
                "receipt": _receipt_dict(receipt),
            }
        )
        raise typer.Exit(code=1)
    _emit_json(
        {
            "contract": _CLI_CONTRACT,
            "decision": decision.to_public_dict(),
            "receipt": _receipt_dict(receipt),
        }
    )


release_app = typer.Typer(
    help="Inspect or operate the durable Agent v0.2 release authority.",
    no_args_is_help=True,
)


@release_app.command("inspect")
def inspect_command() -> None:
    """Inspect the durable release stamp, cutover, and effective gate."""

    _run_cli("inspect", _inspect)


def _inspect() -> None:
    runtime = build_release_cli_runtime()
    workspace_id = _workspace_id(runtime)
    _emit_json(
        {
            "active_release_stamp": _stamp_dict(
                runtime.authority.active_release_stamp(workspace_id)
            ),
            "contract": _CLI_CONTRACT,
            "decision": runtime.status_probe().to_public_dict(),
            "event_cursor": runtime.authority.current_event_cursor(workspace_id),
            "open_public_cutover": _cutover_dict(
                runtime.authority.open_public_cutover(workspace_id)
            ),
        }
    )


@release_app.command("identities")
def identities_command() -> None:
    """Observe release-bound runtime, database, and evidence identities."""

    _run_cli("identities", _identities)


def _identities() -> None:
    runtime = build_release_cli_runtime()
    identities = runtime.runtime_identity_probe()
    _emit_json(
        {
            "contract": _CLI_CONTRACT,
            "database_schema_fingerprint": runtime.schema_fingerprint_probe(),
            "evidence_digest": runtime.evidence_digest_probe(),
            "runtime": {
                "hermes": identities.hermes_runtime_digest,
                "hqa": identities.hqa_runtime_digest,
                "platform": identities.platform_runtime_digest,
            },
            "workspace_id": _workspace_id(runtime),
        }
    )


@release_app.command("status")
def status_command() -> None:
    """Evaluate the current effective release gate."""

    _run_cli("status", _status)


def _status() -> None:
    runtime = build_release_cli_runtime()
    _emit_json(
        {
            "contract": _CLI_CONTRACT,
            "decision": runtime.status_probe().to_public_dict(),
        }
    )


@release_app.command("open-stamp")
def open_stamp_command(
    note: Annotated[
        str,
        typer.Option(
            "--note",
            help="Nonempty operator note bound into the release action.",
        ),
    ],
    client_action_id: Annotated[
        str,
        typer.Option(
            "--client-action-id",
            help="Stable idempotency key for this exact operator action.",
        ),
    ],
) -> None:
    """Open a runtime- and evidence-bound durable release stamp."""

    _run_cli(
        "open-stamp",
        lambda: _open_stamp(
            note=note,
            client_action_id=client_action_id,
        ),
    )


def _open_stamp(*, note: str, client_action_id: str) -> None:
    runtime = build_release_cli_runtime()
    _require_preflight(
        runtime.status_probe(),
        allowed_blockers=frozenset(
            {
                "active_release_stamp_missing",
                "open_public_cutover_missing",
            }
        ),
    )
    identities = runtime.runtime_identity_probe()
    workspace_id = _workspace_id(runtime)
    evidence_digest = runtime.evidence_digest_probe()
    payload = {
        "workspace_id": workspace_id,
        "route": RELEASE_ROUTE,
        "platform_runtime_digest": identities.platform_runtime_digest,
        "hqa_runtime_digest": identities.hqa_runtime_digest,
        "hermes_runtime_digest": identities.hermes_runtime_digest,
        "evidence_digest": evidence_digest,
        "note": note,
    }
    receipt = runtime.authority.create_release_stamp(
        CreateReleaseStampRequest(
            workspace_id=workspace_id,
            route=RELEASE_ROUTE,
            platform_runtime_digest=identities.platform_runtime_digest,
            hqa_runtime_digest=identities.hqa_runtime_digest,
            hermes_runtime_digest=identities.hermes_runtime_digest,
            evidence_digest=evidence_digest,
            note=note,
            client_action_id=client_action_id,
            action_digest=canonical_release_action_digest(
                "release.open",
                payload,
            ),
        )
    )
    _emit_write_result(
        receipt,
        runtime,
        allowed_post_blockers=frozenset({"open_public_cutover_missing"}),
    )


@release_app.command("open-cutover")
def open_cutover_command(
    note: Annotated[
        str,
        typer.Option(
            "--note",
            help="Nonempty operator note bound into the cutover action.",
        ),
    ],
    client_action_id: Annotated[
        str,
        typer.Option(
            "--client-action-id",
            help="Stable idempotency key for this exact operator action.",
        ),
    ],
) -> None:
    """Open the /hermes public cutover for the active release stamp."""

    _run_cli(
        "open-cutover",
        lambda: _open_cutover(
            note=note,
            client_action_id=client_action_id,
        ),
    )


def _open_cutover(*, note: str, client_action_id: str) -> None:
    runtime = build_release_cli_runtime()
    workspace_id = _workspace_id(runtime)
    decision = runtime.status_probe()
    _require_preflight(
        decision,
        allowed_blockers=frozenset({"open_public_cutover_missing"}),
    )
    stamp = runtime.authority.active_release_stamp(workspace_id)
    if (
        stamp is None
        or stamp.status != "active"
        or stamp.route != RELEASE_ROUTE
        or stamp.workspace_id != workspace_id
        or stamp.stamp_id != decision.release_stamp_id
        or stamp.release_digest != decision.release_digest
    ):
        _emit_json(
            {
                "blockers": ["active_release_stamp_observation_mismatch"],
                "contract": _CLI_CONTRACT,
                "error_code": "release_preflight_failed",
            }
        )
        raise typer.Exit(code=1)
    payload = {
        "workspace_id": workspace_id,
        "stamp_id": stamp.stamp_id,
        "expected_release_digest": stamp.release_digest,
        "route": RELEASE_ROUTE,
        "note": note,
    }
    receipt = runtime.authority.create_public_cutover(
        CreatePublicCutoverRequest(
            workspace_id=workspace_id,
            stamp_id=stamp.stamp_id,
            expected_release_digest=stamp.release_digest,
            route=RELEASE_ROUTE,
            note=note,
            client_action_id=client_action_id,
            action_digest=canonical_release_action_digest(
                "public_cutover.open",
                payload,
            ),
        )
    )
    _emit_write_result(receipt, runtime, allowed_post_blockers=frozenset())


@release_app.command("close-cutover")
def close_cutover_command(
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="Nonempty operator rollback reason bound into the action.",
        ),
    ],
    client_action_id: Annotated[
        str,
        typer.Option(
            "--client-action-id",
            help="Stable idempotency key for this exact operator action.",
        ),
    ],
) -> None:
    """Close the current public cutover without consulting the effective gate."""

    _run_cli(
        "close-cutover",
        lambda: _close_cutover(
            reason=reason,
            client_action_id=client_action_id,
        ),
    )


def _close_cutover(*, reason: str, client_action_id: str) -> None:
    runtime = build_release_cli_runtime()
    workspace_id = _workspace_id(runtime)
    cutover = runtime.authority.open_public_cutover(workspace_id)
    if cutover is None:
        raise ReleaseAuthorityNotFound("no open public cutover")
    if (
        cutover.status != "open"
        or cutover.route != RELEASE_ROUTE
        or cutover.workspace_id != workspace_id
    ):
        raise ReleaseAuthorityConflict("public cutover observation mismatch")
    payload = {
        "workspace_id": workspace_id,
        "cutover_id": cutover.cutover_id,
        "expected_cutover_digest": cutover.cutover_digest,
        "reason": reason,
    }
    receipt = runtime.authority.close_public_cutover(
        ClosePublicCutoverRequest(
            workspace_id=workspace_id,
            cutover_id=cutover.cutover_id,
            expected_cutover_digest=cutover.cutover_digest,
            reason=reason,
            client_action_id=client_action_id,
            action_digest=canonical_release_action_digest(
                "public_cutover.close",
                payload,
            ),
        )
    )
    _emit_write_result(receipt, runtime)


@release_app.command("close-stamp")
def close_stamp_command(
    reason: Annotated[
        str,
        typer.Option(
            "--reason",
            help="Nonempty operator rollback reason bound into the action.",
        ),
    ],
    client_action_id: Annotated[
        str,
        typer.Option(
            "--client-action-id",
            help="Stable idempotency key for this exact operator action.",
        ),
    ],
) -> None:
    """Close the active release stamp after its public cutover is closed."""

    _run_cli(
        "close-stamp",
        lambda: _close_stamp(
            reason=reason,
            client_action_id=client_action_id,
        ),
    )


def _close_stamp(*, reason: str, client_action_id: str) -> None:
    runtime = build_release_cli_runtime()
    workspace_id = _workspace_id(runtime)
    stamp = runtime.authority.active_release_stamp(workspace_id)
    if stamp is None:
        raise ReleaseAuthorityNotFound("no active release stamp")
    if (
        stamp.status != "active"
        or stamp.route != RELEASE_ROUTE
        or stamp.workspace_id != workspace_id
    ):
        raise ReleaseAuthorityConflict("release stamp observation mismatch")
    payload = {
        "workspace_id": workspace_id,
        "stamp_id": stamp.stamp_id,
        "expected_release_digest": stamp.release_digest,
        "reason": reason,
    }
    receipt = runtime.authority.close_release_stamp(
        CloseReleaseStampRequest(
            workspace_id=workspace_id,
            stamp_id=stamp.stamp_id,
            expected_release_digest=stamp.release_digest,
            reason=reason,
            client_action_id=client_action_id,
            action_digest=canonical_release_action_digest(
                "release.close",
                payload,
            ),
        )
    )
    _emit_write_result(receipt, runtime)


__all__ = [
    "ReleaseCliRuntime",
    "build_release_cli_runtime",
    "release_app",
]
