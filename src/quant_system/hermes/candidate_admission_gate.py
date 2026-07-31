"""Effective local-only gate for the Agent v0.2 candidate window."""

from __future__ import annotations

from dataclasses import dataclass

from quant_system.config.settings import Settings
from quant_system.hermes.candidate_admission_authority import (
    CandidateAdmissionAuthority,
    CandidateAdmissionRecord,
    candidate_admission_runtime_security_is_ready,
)
from quant_system.hermes.candidate_evidence import (
    candidate_preflight_evidence_observation,
)
from quant_system.hermes.candidate_evidence_v3 import (
    candidate_evidence_runtime_security_is_ready,
)
from quant_system.hermes.connector_liveness import (
    ConnectorLivenessAuthority,
)
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID
from quant_system.hermes.paper_safety_authority import PaperSafetyAuthority
from quant_system.hermes.release_runtime import (
    current_release_decision,
    runtime_identity_observation,
)
from quant_system.storage.database import get_database, schema_fingerprint


@dataclass(frozen=True)
class CandidateAdmissionDecision:
    ready: bool
    dispatch_ready: bool
    connector_ready: bool
    admission_id: str | None
    admission_digest: str | None
    blockers: tuple[str, ...]
    record: CandidateAdmissionRecord | None
    connector_worker_id: str | None = None
    connector_generation_token: str | None = None
    connector_heartbeat_age_seconds: float | None = None


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def current_candidate_decision(
    settings: Settings,
    *,
    require_connector: bool,
) -> CandidateAdmissionDecision:
    """Evaluate exact candidate facts.

    ``dispatch_ready`` excludes connector liveness and is therefore usable by
    the connector before it acquires/advertises its own generation. ``ready``
    additionally requires the generation to be live and to have started no
    earlier than the candidate admission.
    """

    if settings.agent_v02_release.workspace_id != PLATFORM_WORKSPACE_ID:
        return CandidateAdmissionDecision(
            ready=False,
            dispatch_ready=False,
            connector_ready=False,
            admission_id=None,
            admission_digest=None,
            blockers=("release_workspace_profile_mismatch",),
            record=None,
        )
    if settings.paper_account.db_mode != "canonical":
        return CandidateAdmissionDecision(
            ready=False,
            dispatch_ready=False,
            connector_ready=False,
            admission_id=None,
            admission_digest=None,
            blockers=("canonical_paper_authority_required",),
            record=None,
        )

    blockers: list[str] = []
    if settings.candidate_admission.enabled is not True:
        blockers.append("candidate_setting_disabled")
    if settings.local_mutation.enabled is not True:
        blockers.append("local_mutation_disabled")
    if settings.local_mutation.composer_open is not True:
        blockers.append("local_composer_closed")
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
    if settings.hermes_gateway.enabled is not True:
        blockers.append("hermes_gateway_disabled")

    record = None
    try:
        authority = CandidateAdmissionAuthority(settings)
        record = authority.active(
            settings.agent_v02_release.workspace_id
        )
        if record is None:
            observed = authority.current(
                settings.agent_v02_release.workspace_id
            )
            if observed is not None and observed.status == "open":
                record = observed
    except Exception:  # noqa: BLE001 - every uncertain fact closes admission
        blockers.append("candidate_authority_unavailable")
    if record is None:
        blockers.append("candidate_admission_missing")
    else:
        try:
            paper_safety = PaperSafetyAuthority(settings).observe(
                settings.agent_v02_release.workspace_id,
                candidate_paper_authority_epoch=record.paper_authority_epoch,
            )
            blockers.extend(str(blocker) for blocker in paper_safety.blockers)
        except Exception:  # noqa: BLE001 - uncertain paper facts close admission
            blockers.append("canonical_paper_authority_unavailable")

    identities = None
    try:
        identities = runtime_identity_observation(settings)
    except Exception:  # noqa: BLE001
        blockers.append("candidate_runtime_identity_unavailable")
    if record is not None and identities is not None:
        if (
            identities.platform_runtime_digest
            != record.platform_runtime_digest
        ):
            blockers.append("candidate_platform_runtime_mismatch")
        if identities.hqa_runtime_digest != record.hqa_runtime_digest:
            blockers.append("candidate_hqa_runtime_mismatch")
        if (
            identities.hermes_runtime_digest
            != record.hermes_runtime_digest
        ):
            blockers.append("candidate_hermes_runtime_mismatch")

    try:
        fingerprint = schema_fingerprint(get_database(settings))
    except Exception:  # noqa: BLE001
        fingerprint = "<unavailable>"
    if record is not None and fingerprint != record.database_schema_fingerprint:
        blockers.append("candidate_database_schema_mismatch")

    preflight = None
    try:
        preflight = candidate_preflight_evidence_observation(
            settings.candidate_admission.preflight_evidence_file
        )
    except Exception:  # noqa: BLE001
        blockers.append("candidate_preflight_evidence_unavailable")
    if record is not None and preflight is not None:
        if preflight.digest != record.preflight_evidence_digest:
            blockers.append("candidate_preflight_evidence_mismatch")
        if (
            preflight.platform_runtime_digest
            != record.platform_runtime_digest
            or preflight.hqa_runtime_digest != record.hqa_runtime_digest
            or preflight.hermes_runtime_digest
            != record.hermes_runtime_digest
        ):
            blockers.append("candidate_preflight_runtime_mismatch")

    if not candidate_admission_runtime_security_is_ready(settings):
        blockers.append("candidate_runtime_security_unready")
    if not candidate_evidence_runtime_security_is_ready(settings):
        blockers.append("candidate_evidence_v3_security_unready")

    # Reuse the production capability verifier. Candidate admission expects the
    # release-stamp/evidence blockers, but no Hermes capability blocker.
    try:
        release_probe = current_release_decision(settings)
        blockers.extend(
            str(blocker)
            for blocker in release_probe.blockers
            if str(blocker).startswith("hermes_")
        )
    except Exception:  # noqa: BLE001
        blockers.append("hermes_capability_probe_unavailable")

    dispatch_blockers = _dedupe(blockers)
    dispatch_ready = record is not None and not dispatch_blockers

    connector_ready = False
    connector_worker_id = None
    connector_generation = None
    connector_age = None
    if require_connector and dispatch_ready and identities is not None:
        try:
            connector = ConnectorLivenessAuthority(settings).probe(
                workspace_id=settings.agent_v02_release.workspace_id,
                expected_runtime_digest=(
                    identities.platform_runtime_digest
                ),
                max_heartbeat_age_seconds=float(
                    settings.agent_v02_release
                    .connector_heartbeat_max_age_seconds
                ),
            )
            connector_ready = bool(connector.ready)
            connector_worker_id = connector.worker_id
            connector_generation = connector.generation_token
            connector_age = connector.heartbeat_age_seconds
            if connector.ready is not True:
                blockers.append(str(connector.reason))
            elif (
                record is not None
                and connector.started_at is not None
                and connector.started_at < record.opened_at
            ):
                connector_ready = False
                blockers.append("candidate_connector_predates_admission")
        except Exception:  # noqa: BLE001
            blockers.append("connector_liveness_unavailable")

    ordered = _dedupe(blockers)
    return CandidateAdmissionDecision(
        ready=bool(
            dispatch_ready
            and (connector_ready if require_connector else True)
            and not ordered
        ),
        dispatch_ready=dispatch_ready,
        connector_ready=connector_ready,
        admission_id=None if record is None else record.admission_id,
        admission_digest=(
            None if record is None else record.admission_digest
        ),
        blockers=ordered,
        record=record,
        connector_worker_id=connector_worker_id,
        connector_generation_token=connector_generation,
        connector_heartbeat_age_seconds=connector_age,
    )


__all__ = [
    "CandidateAdmissionDecision",
    "current_candidate_decision",
]
