"""Operator CLI for the private Agent v0.2 candidate admission."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import typer

from quant_system.config.settings import Settings, load_settings
from quant_system.hermes.candidate_admission_authority import (
    CANDIDATE_ROUTE,
    AcceptCandidateAdmissionRequest,
    CandidateAdmissionAuthority,
    CandidateAdmissionError,
    CandidateAdmissionRecord,
    OpenCandidateAdmissionRequest,
    RevokeCandidateAdmissionRequest,
    canonical_candidate_action_digest,
)
from quant_system.hermes.candidate_evidence import (
    CandidatePreflightEvidenceObservation,
    candidate_preflight_evidence_observation,
)
from quant_system.hermes.candidate_evidence_v3 import (
    CandidateEvidenceReferences,
    CandidateEvidenceV3Authority,
    CandidateEvidenceV3Error,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.effective_release_gate import (
    ReleaseEvidenceObservation,
    RuntimeIdentityObservation,
)
from quant_system.hermes.release_runtime import (
    file_sha256,
    release_evidence_observation,
    runtime_identity_observation,
)
from quant_system.hermes.zero_order_observation import (
    CanonicalZeroOrderSnapshot,
    capture_canonical_zero_order_snapshot,
)
from quant_system.storage.database import (
    Database,
    get_database,
    schema_fingerprint,
)

_CLI_CONTRACT = "agent-v0.2-candidate-cli/v1"


@dataclass(frozen=True)
class CandidateCliRuntime:
    settings: Settings
    database: Database
    authority: CandidateAdmissionAuthority
    evidence_authority: CandidateEvidenceV3Authority
    runtime_identity_probe: Callable[[], RuntimeIdentityObservation]
    preflight_probe: Callable[[], CandidatePreflightEvidenceObservation]
    final_evidence_probe: Callable[[], ReleaseEvidenceObservation]
    schema_fingerprint_probe: Callable[[], str]
    order_snapshot_probe: Callable[[], CanonicalZeroOrderSnapshot]


def build_candidate_cli_runtime() -> CandidateCliRuntime:
    settings = load_settings()
    database = get_database(settings)
    if database is None:
        raise RuntimeError("candidate admission requires PostgreSQL")

    def _order_snapshot() -> CanonicalZeroOrderSnapshot:
        with database.connect() as conn:
            return capture_canonical_zero_order_snapshot(
                conn,
                owner_user_id=ROOT_USER_ID,
            )

    return CandidateCliRuntime(
        settings=settings,
        database=database,
        authority=CandidateAdmissionAuthority(
            settings,
            database=database,
        ),
        evidence_authority=CandidateEvidenceV3Authority(
            settings,
            database=database,
        ),
        runtime_identity_probe=lambda: runtime_identity_observation(settings),
        preflight_probe=lambda: candidate_preflight_evidence_observation(
            settings.candidate_admission.preflight_evidence_file
        ),
        final_evidence_probe=lambda: release_evidence_observation(
            settings.candidate_admission.final_evidence_file
        ),
        schema_fingerprint_probe=lambda: schema_fingerprint(database),
        order_snapshot_probe=_order_snapshot,
    )


def _emit(payload: dict[str, object]) -> None:
    typer.echo(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _run(operation: str, callback: Callable[[], None]) -> None:
    try:
        callback()
    except typer.Exit:
        raise
    except CandidateAdmissionError as exc:
        _emit(
            {
                "contract": _CLI_CONTRACT,
                "error_code": exc.code,
                "message": exc.message,
                "operation": operation,
            }
        )
        raise typer.Exit(code=1) from None
    except CandidateEvidenceV3Error as exc:
        _emit(
            {
                "contract": _CLI_CONTRACT,
                "error_code": exc.code,
                "message": exc.message,
                "operation": operation,
            }
        )
        raise typer.Exit(code=1) from None
    except Exception as exc:  # noqa: BLE001 - operator CLI fails closed
        _emit(
            {
                "contract": _CLI_CONTRACT,
                "error_code": "candidate_cli_unavailable",
                "message": str(exc)[:500] or exc.__class__.__name__,
                "operation": operation,
            }
        )
        raise typer.Exit(code=1) from None


def _record(record: CandidateAdmissionRecord | None) -> object:
    return None if record is None else record.to_public_dict()


def _require_safety(settings: Settings) -> None:
    blockers: list[str] = []
    if settings.safety.kill_switch is not True:
        blockers.append("kill_switch_off")
    if settings.safety.live_trading_enabled is not False:
        blockers.append("live_trading_enabled")
    if settings.safety.paper_trading is not True:
        blockers.append("paper_trading_off")
    if settings.safety.dry_run is not True:
        blockers.append("dry_run_off")
    if settings.safety.no_live_trade_without_manual_approval is not True:
        blockers.append("manual_live_approval_guard_off")
    if settings.paper_account.auto_process_pending_orders_enabled is not False:
        blockers.append("paper_pending_order_processor_enabled")
    if settings.database.auto_migrate is not False:
        blockers.append("database_auto_migrate_enabled")
    if settings.local_mutation.enabled is not True:
        blockers.append("local_mutation_disabled")
    if settings.local_mutation.composer_open is not True:
        blockers.append("local_composer_closed")
    if blockers:
        raise RuntimeError(
            "candidate safety preflight failed: " + ",".join(blockers)
        )


def _runtime_matches_preflight(
    runtime: RuntimeIdentityObservation,
    preflight: CandidatePreflightEvidenceObservation,
) -> bool:
    return (
        runtime.platform_runtime_digest
        == preflight.platform_runtime_digest
        and runtime.hqa_runtime_digest == preflight.hqa_runtime_digest
        and runtime.hermes_runtime_digest
        == preflight.hermes_runtime_digest
    )


candidate_app = typer.Typer(
    help=(
        "Inspect or operate the private, short-lived Agent v0.2 candidate "
        "admission. This never opens public release."
    ),
    no_args_is_help=True,
)


@candidate_app.command("status")
def status_command() -> None:
    """Inspect the current candidate fact without changing it."""

    def _status() -> None:
        runtime = build_candidate_cli_runtime()
        workspace = runtime.settings.agent_v02_release.workspace_id
        _emit(
            {
                "candidate_enabled": (
                    runtime.settings.candidate_admission.enabled
                ),
                "contract": _CLI_CONTRACT,
                "current": _record(
                    runtime.authority.current(
                        workspace,
                        include_expired_open=True,
                    )
                ),
                "public_chat_write_ready": False,
                "public_write_authorized": False,
                "release_authorized": False,
                "route": CANDIDATE_ROUTE,
                "workspace_id": workspace,
            }
        )

    _run("status", _status)


@candidate_app.command("open")
def open_command(
    note: Annotated[
        str,
        typer.Option(
            "--note",
            help="Operator reason for the bounded local candidate window.",
        ),
    ],
    client_action_id: Annotated[
        str,
        typer.Option(
            "--client-action-id",
            help="Stable idempotency key for this exact open action.",
        ),
    ],
) -> None:
    """Open one test-bound, local-only candidate window."""

    def _open() -> None:
        runtime = build_candidate_cli_runtime()
        _require_safety(runtime.settings)
        identities = runtime.runtime_identity_probe()
        preflight = runtime.preflight_probe()
        if not _runtime_matches_preflight(identities, preflight):
            raise RuntimeError(
                "candidate preflight runtime binding does not match "
                "the clean current runtimes"
            )
        fingerprint = runtime.schema_fingerprint_probe()
        if len(fingerprint) != 64:
            raise RuntimeError("database schema fingerprint is unavailable")
        order_snapshot = runtime.order_snapshot_probe()
        workspace = runtime.settings.agent_v02_release.workspace_id
        payload = {
            "baseline_order_snapshot_digest": (
                order_snapshot.snapshot_digest
            ),
            "database_schema_fingerprint": fingerprint,
            "hermes_runtime_digest": identities.hermes_runtime_digest,
            "hqa_runtime_digest": identities.hqa_runtime_digest,
            "note": note.strip(),
            "platform_runtime_digest": identities.platform_runtime_digest,
            "preflight_evidence_digest": preflight.digest,
            "route": CANDIDATE_ROUTE,
            "ttl_seconds": (
                runtime.settings.candidate_admission.ttl_seconds
            ),
            "workspace_id": workspace,
        }
        receipt = runtime.authority.open(
            OpenCandidateAdmissionRequest(
                workspace_id=workspace,
                route=CANDIDATE_ROUTE,
                platform_runtime_digest=identities.platform_runtime_digest,
                hqa_runtime_digest=identities.hqa_runtime_digest,
                hermes_runtime_digest=identities.hermes_runtime_digest,
                database_schema_fingerprint=fingerprint,
                preflight_evidence_digest=preflight.digest,
                baseline_order_snapshot_digest=(
                    order_snapshot.snapshot_digest
                ),
                ttl_seconds=(
                    runtime.settings.candidate_admission.ttl_seconds
                ),
                note=note,
                client_action_id=client_action_id,
                action_digest=canonical_candidate_action_digest(
                    "candidate.open", payload
                ),
            )
        )
        _emit(
            {
                "contract": _CLI_CONTRACT,
                **receipt.to_storage_dict(),
                "local_candidate_chat_write_ready": False,
                "note": (
                    "start the exact-runtime candidate connector before "
                    "the composer can open"
                ),
                "public_chat_write_ready": False,
                "public_write_authorized": False,
                "release_authorized": False,
            }
        )

    _run("open", _open)


@candidate_app.command("accept")
def accept_command(
    admission_id: Annotated[str, typer.Option("--admission-id")],
    expected_admission_digest: Annotated[
        str,
        typer.Option("--expected-admission-digest"),
    ],
    evidence_set_id: Annotated[str, typer.Option("--evidence-set-id")],
    evidence_set_digest: Annotated[
        str,
        typer.Option("--evidence-set-digest"),
    ],
    final_order_snapshot_digest: Annotated[
        str,
        typer.Option("--final-order-snapshot-digest"),
    ],
    note: Annotated[str, typer.Option("--note")],
    client_action_id: Annotated[
        str,
        typer.Option("--client-action-id"),
    ],
) -> None:
    """Bind the sealed final evidence and close the candidate as accepted."""

    def _accept() -> None:
        runtime = build_candidate_cli_runtime()
        _require_safety(runtime.settings)
        workspace = runtime.settings.agent_v02_release.workspace_id
        current = runtime.authority.active(workspace)
        if (
            current is None
            or current.admission_id != admission_id
            or current.admission_digest != expected_admission_digest
        ):
            raise RuntimeError("exact candidate admission is not active")
        identities = runtime.runtime_identity_probe()
        if (
            identities.platform_runtime_digest
            != current.platform_runtime_digest
            or identities.hqa_runtime_digest != current.hqa_runtime_digest
            or identities.hermes_runtime_digest
            != current.hermes_runtime_digest
        ):
            raise RuntimeError("candidate runtime identity drifted")
        if (
            runtime.schema_fingerprint_probe()
            != current.database_schema_fingerprint
        ):
            raise RuntimeError("candidate database schema drifted")
        final_evidence = runtime.final_evidence_probe()
        if (
            final_evidence.platform_runtime_digest
            != current.platform_runtime_digest
            or final_evidence.hqa_runtime_digest
            != current.hqa_runtime_digest
            or final_evidence.hermes_runtime_digest
            != current.hermes_runtime_digest
        ):
            raise RuntimeError("final evidence runtime binding drifted")
        if (
            final_evidence.contract
            != "agent-v0.2-release-evidence/v4"
            or final_evidence.candidate_admission_id != admission_id
            or final_evidence.candidate_admission_digest
            != expected_admission_digest
            or final_evidence.evidence_set_id != evidence_set_id
            or final_evidence.evidence_set_digest
            != evidence_set_digest
            or final_evidence.final_order_snapshot_digest
            != final_order_snapshot_digest
        ):
            raise RuntimeError(
                "final evidence does not bind the exact verified candidate "
                "evidence set"
            )
        final_digest = file_sha256(
            runtime.settings.candidate_admission.final_evidence_file
        )
        payload = {
            "admission_id": admission_id,
            "expected_admission_digest": expected_admission_digest,
            "evidence_set_digest": evidence_set_digest,
            "evidence_set_id": evidence_set_id,
            "final_evidence_digest": final_digest,
            "final_order_snapshot_digest": (
                final_order_snapshot_digest
            ),
            "note": note.strip(),
            "workspace_id": workspace,
        }
        receipt = runtime.authority.accept(
            AcceptCandidateAdmissionRequest(
                workspace_id=workspace,
                admission_id=admission_id,
                expected_admission_digest=expected_admission_digest,
                final_evidence_digest=final_digest,
                evidence_set_id=evidence_set_id,
                evidence_set_digest=evidence_set_digest,
                final_order_snapshot_digest=(
                    final_order_snapshot_digest
                ),
                note=note,
                client_action_id=client_action_id,
                action_digest=canonical_candidate_action_digest(
                    "candidate.accept", payload
                ),
            )
        )
        _emit(
            {
                "contract": _CLI_CONTRACT,
                **receipt.to_storage_dict(),
                "public_chat_write_ready": False,
                "public_write_authorized": False,
                "release_authorized": False,
            }
        )

    _run("accept", _accept)


@candidate_app.command("capture-restart")
def capture_restart_command(
    admission_id: Annotated[str, typer.Option("--admission-id")],
    expected_admission_digest: Annotated[
        str,
        typer.Option("--expected-admission-digest"),
    ],
    phase: Annotated[
        str,
        typer.Option(
            "--phase",
            help="Exact restart observation phase: before or after.",
        ),
    ],
    platform_session_id: Annotated[
        str,
        typer.Option("--platform-session-id"),
    ],
) -> None:
    """Capture one live Hermes transcript/runtime observation."""

    def _capture() -> None:
        runtime = build_candidate_cli_runtime()
        _require_safety(runtime.settings)
        if phase not in {"before", "after"}:
            raise RuntimeError("phase must be before or after")
        observation = runtime.evidence_authority.capture_restart(
            admission_id=admission_id,
            admission_digest=expected_admission_digest,
            phase=phase,  # type: ignore[arg-type]
            platform_session_id=platform_session_id,
        )
        _emit(
            {
                "contract": _CLI_CONTRACT,
                "operation": "capture-restart",
                **observation.to_public_dict(),
                "public_chat_write_ready": False,
                "public_write_authorized": False,
                "release_authorized": False,
            }
        )

    _run("capture-restart", _capture)


@candidate_app.command("verify-evidence")
def verify_evidence_command(
    admission_id: Annotated[str, typer.Option("--admission-id")],
    expected_admission_digest: Annotated[
        str,
        typer.Option("--expected-admission-digest"),
    ],
    web_platform_session_id: Annotated[
        str,
        typer.Option("--web-platform-session-id"),
    ],
    web_command_id: Annotated[
        list[str],
        typer.Option(
            "--web-command-id",
            help="Repeat for each exact multi-turn command (minimum two).",
        ),
    ],
    fork_source_platform_session_id: Annotated[
        str,
        typer.Option("--fork-source-platform-session-id"),
    ],
    fork_child_platform_session_id: Annotated[
        str,
        typer.Option("--fork-child-platform-session-id"),
    ],
    options_request_id: Annotated[
        str,
        typer.Option("--options-request-id"),
    ],
    paper_gate3_id: Annotated[
        str,
        typer.Option("--paper-gate3-id"),
    ],
    approval_command_id: Annotated[
        str,
        typer.Option("--approval-command-id"),
    ],
    stop_source_command_id: Annotated[
        str,
        typer.Option(
            "--stop-source-command-id",
            help="Exact conversation command whose Hermes Run was stopped.",
        ),
    ],
    stop_command_id: Annotated[
        str,
        typer.Option("--stop-command-id"),
    ],
    reviewed_commit: Annotated[
        str,
        typer.Option("--reviewed-commit"),
    ],
) -> None:
    """Freeze five canonical flows plus exact approval/stop evidence."""

    def _verify() -> None:
        runtime = build_candidate_cli_runtime()
        _require_safety(runtime.settings)
        evidence = runtime.evidence_authority.verify_and_store(
            CandidateEvidenceReferences(
                admission_id=admission_id,
                admission_digest=expected_admission_digest,
                web_platform_session_id=web_platform_session_id,
                web_command_ids=tuple(web_command_id),
                fork_source_platform_session_id=(
                    fork_source_platform_session_id
                ),
                fork_child_platform_session_id=(
                    fork_child_platform_session_id
                ),
                options_request_id=options_request_id,
                paper_gate3_id=paper_gate3_id,
                reviewed_commit=reviewed_commit,
                approval_command_id=approval_command_id,
                stop_source_command_id=stop_source_command_id,
                stop_command_id=stop_command_id,
            )
        )
        _emit(
            {
                "contract": _CLI_CONTRACT,
                "operation": "verify-evidence",
                **evidence.to_public_dict(),
                "public_chat_write_ready": False,
                "public_write_authorized": False,
                "release_authorized": False,
            }
        )

    _run("verify-evidence", _verify)


@candidate_app.command("revoke")
def revoke_command(
    admission_id: Annotated[str, typer.Option("--admission-id")],
    expected_admission_digest: Annotated[
        str,
        typer.Option("--expected-admission-digest"),
    ],
    reason: Annotated[str, typer.Option("--reason")],
    client_action_id: Annotated[
        str,
        typer.Option("--client-action-id"),
    ],
) -> None:
    """Close an unsafe or abandoned candidate immediately."""

    def _revoke() -> None:
        runtime = build_candidate_cli_runtime()
        workspace = runtime.settings.agent_v02_release.workspace_id
        payload = {
            "admission_id": admission_id,
            "expected_admission_digest": expected_admission_digest,
            "reason": reason.strip(),
            "workspace_id": workspace,
        }
        receipt = runtime.authority.revoke(
            RevokeCandidateAdmissionRequest(
                workspace_id=workspace,
                admission_id=admission_id,
                expected_admission_digest=expected_admission_digest,
                reason=reason,
                client_action_id=client_action_id,
                action_digest=canonical_candidate_action_digest(
                    "candidate.revoke", payload
                ),
            )
        )
        _emit({"contract": _CLI_CONTRACT, **receipt.to_storage_dict()})

    _run("revoke", _revoke)


__all__ = [
    "CandidateCliRuntime",
    "build_candidate_cli_runtime",
    "candidate_app",
]


if __name__ == "__main__":
    candidate_app()
