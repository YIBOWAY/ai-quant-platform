"""Effective Agent v0.2 composer admission.

The browser write surface is admitted only when two independent runtime facts
agree:

* the durable release stamp and public cutover remain exactly bound to the
  clean Platform/HQA/Hermes runtimes, live schema, sealed evidence, constrained
  database role, and grounded Hermes capabilities; and
* one exact supervised connector generation still owns its PostgreSQL session
  lock and has a fresh heartbeat.

The research Task/Attempt binding is intentionally reported separately.  It is
required for the paper workflow, not for an ordinary Hermes conversation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Final

from quant_system.config.settings import Settings
from quant_system.hermes.candidate_admission_gate import (
    current_candidate_decision,
)
from quant_system.hermes.command_ledger import command_ledger_schema_version
from quant_system.hermes.connector_liveness import ConnectorLivenessAuthority
from quant_system.hermes.release_runtime import (
    current_release_decision,
    runtime_identity_observation,
)
from quant_system.hermes.run_control_outcome_authority import (
    run_control_outcome_runtime_security_ready,
)
from quant_system.hermes.session_registry import (
    hermes_runtime_security_ready,
    session_registry_schema_version,
)
from quant_system.hermes.workflow_binding import workflow_binding_schema_version

# Compatibility export for existing clients.  Capability blockers are no
# longer a frozen list: they come from the live durable release decision.
UPSTREAM_CHAT_WRITE_BLOCKERS: Final[tuple[str, ...]] = ()

_READINESS_CACHE_SECONDS = 1.0
_READINESS_CACHE_LIMIT = 16
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class _EffectiveAdmission:
    release_ready: bool
    candidate_ready: bool
    connector_ready: bool
    ready: bool
    admission_mode: str
    blockers: tuple[str, ...]
    final_release_blockers: tuple[str, ...]
    release_stamp_id: str | None
    public_cutover_id: str | None
    candidate_admission_id: str | None
    candidate_admission_digest: str | None
    release_event_cursor: int
    connector_reason: str
    connector_worker_id: str | None
    connector_mode: str | None
    connector_heartbeat_age_seconds: float | None


# Keep the settings object alongside its id so Python id reuse cannot return a
# prior process/config observation.  The cache is deliberately tiny and short.
_ADMISSION_CACHE: dict[
    int,
    tuple[Settings, float, _EffectiveAdmission],
] = {}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _observe_effective_admission(settings: Settings) -> _EffectiveAdmission:
    final_blockers: list[str] = []
    release = None
    try:
        release = current_release_decision(settings)
        final_blockers.extend(str(item) for item in release.blockers)
    except Exception:  # noqa: BLE001 - admission probes always fail closed
        final_blockers.append("effective_release_gate_unavailable")

    connector = None
    release_ready = bool(release is not None and release.ready)
    candidate = None
    if (
        not release_ready
        and settings.candidate_admission.enabled is True
    ):
        try:
            candidate = current_candidate_decision(
                settings,
                require_connector=True,
            )
        except Exception:  # noqa: BLE001 - candidate uncertainty closes writes
            candidate = None

    candidate_ready = bool(candidate is not None and candidate.ready)
    admission_mode = (
        "release"
        if release_ready
        else ("candidate" if candidate_ready else "closed")
    )
    blockers: list[str] = []
    if release_ready or candidate is None:
        if not release_ready:
            blockers.extend(final_blockers)
        try:
            platform_digest = runtime_identity_observation(
                settings
            ).platform_runtime_digest
            max_age = float(
                getattr(
                    settings.agent_v02_release,
                    "connector_heartbeat_max_age_seconds",
                    30.0,
                )
            )
            connector = ConnectorLivenessAuthority(settings).probe(
                workspace_id=settings.agent_v02_release.workspace_id,
                expected_runtime_digest=platform_digest,
                max_heartbeat_age_seconds=max_age,
            )
            if connector.ready is not True:
                blockers.append(str(connector.reason))
        except Exception:  # noqa: BLE001 - liveness uncertainty closes writes
            blockers.append("connector_liveness_unavailable")
    elif candidate is not None:
        blockers.extend(str(item) for item in candidate.blockers)
    else:
        blockers.extend(final_blockers)

    connector_ready = bool(
        (connector is not None and connector.ready)
        or (candidate is not None and candidate.connector_ready)
    )
    ordered = tuple(_dedupe(blockers))
    ready = (
        (release_ready or candidate_ready)
        and connector_ready
        and not ordered
    )
    return _EffectiveAdmission(
        release_ready=release_ready,
        candidate_ready=candidate_ready,
        connector_ready=connector_ready,
        ready=ready,
        admission_mode=admission_mode,
        blockers=ordered,
        final_release_blockers=tuple(_dedupe(final_blockers)),
        release_stamp_id=(
            str(release.release_stamp_id)
            if release is not None and release.release_stamp_id is not None
            else None
        ),
        public_cutover_id=(
            str(release.public_cutover_id)
            if release is not None and release.public_cutover_id is not None
            else None
        ),
        candidate_admission_id=(
            None
            if candidate is None
            else candidate.admission_id
        ),
        candidate_admission_digest=(
            None
            if candidate is None
            else candidate.admission_digest
        ),
        release_event_cursor=(
            int(release.event_cursor)
            if release is not None
            and isinstance(release.event_cursor, int)
            and not isinstance(release.event_cursor, bool)
            and release.event_cursor >= 0
            else 0
        ),
        connector_reason=(
            str(connector.reason)
            if connector is not None
            else (
                "ready"
                if candidate is not None and candidate.connector_ready
                else "connector_liveness_unavailable"
            )
        ),
        connector_worker_id=(
            str(connector.worker_id)
            if connector is not None and connector.worker_id is not None
            else (
                None
                if candidate is None
                else candidate.connector_worker_id
            )
        ),
        connector_mode=(
            str(connector.mode)
            if connector is not None and connector.mode is not None
            else (
                "supervised_dispatch"
                if candidate is not None and candidate.connector_ready
                else None
            )
        ),
        connector_heartbeat_age_seconds=(
            float(connector.heartbeat_age_seconds)
            if connector is not None
            and connector.heartbeat_age_seconds is not None
            else (
                None
                if candidate is None
                else candidate.connector_heartbeat_age_seconds
            )
        ),
    )


def _effective_admission(
    settings: Settings,
    *,
    fresh: bool,
) -> _EffectiveAdmission:
    if fresh:
        return _observe_effective_admission(settings)

    key = id(settings)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _ADMISSION_CACHE.get(key)
        if (
            cached is not None
            and cached[0] is settings
            and now - cached[1] <= _READINESS_CACHE_SECONDS
        ):
            return cached[2]

    observed = _observe_effective_admission(settings)
    with _CACHE_LOCK:
        if len(_ADMISSION_CACHE) >= _READINESS_CACHE_LIMIT:
            oldest = min(_ADMISSION_CACHE, key=lambda item: _ADMISSION_CACHE[item][1])
            _ADMISSION_CACHE.pop(oldest, None)
        _ADMISSION_CACHE[key] = (settings, now, observed)
    return observed


def _local_mutation_enabled(settings: Settings) -> bool:
    return bool(getattr(settings.local_mutation, "enabled", False))


def _authority_readiness_projection(
    settings: Settings,
    *,
    admission: _EffectiveAdmission,
) -> dict[str, object]:
    ledger_version = command_ledger_schema_version(settings)
    session_version = session_registry_schema_version(settings)
    binding_version = workflow_binding_schema_version(settings)
    ledger_ready = ledger_version is not None
    session_ready = session_version is not None
    binding_ready = binding_version is not None
    schema_ready = ledger_ready and session_ready
    research_schema_ready = schema_ready and binding_ready
    runtime_security_ready = hermes_runtime_security_ready(settings)
    run_control_outcome_ready = (
        run_control_outcome_runtime_security_ready(settings)
    )
    write_authority_ready = schema_ready and runtime_security_ready
    mutation_on = _local_mutation_enabled(settings)

    return {
        "command_ledger_schema_ready": ledger_ready,
        "command_ledger_schema_version": ledger_version,
        "session_registry_schema_ready": session_ready,
        "session_registry_schema_version": session_version,
        "workflow_binding_schema_ready": binding_ready,
        "workflow_binding_schema_version": binding_version,
        "schema_ready": schema_ready,
        "ready": write_authority_ready,
        "research_binding_schema_ready": research_schema_ready,
        "research_binding_ready": research_schema_ready and runtime_security_ready,
        "runtime_security_ready": runtime_security_ready,
        "run_control_outcome_ready": run_control_outcome_ready,
        "write_authority_ready": write_authority_ready,
        "dark_dispatch_schema_ready": schema_ready,
        "dark_dispatch_ready": admission.connector_ready,
        "connector_liveness_ready": admission.connector_ready,
        "connector_liveness_reason": admission.connector_reason,
        "connector_worker_id": admission.connector_worker_id,
        "connector_mode": admission.connector_mode,
        "connector_heartbeat_age_seconds": (
            admission.connector_heartbeat_age_seconds
        ),
        "release_authorized": admission.release_ready,
        "release_blockers": list(admission.blockers),
        "final_release_blockers": list(
            admission.final_release_blockers
        ),
        "release_stamp_id": admission.release_stamp_id,
        "public_cutover_id": admission.public_cutover_id,
        "admission_mode": admission.admission_mode,
        "candidate_admission_id": admission.candidate_admission_id,
        "candidate_admission_digest": (
            admission.candidate_admission_digest
        ),
        "candidate_chat_write_ready": admission.candidate_ready,
        "release_event_cursor": admission.release_event_cursor,
        "mutation_enabled": mutation_on,
        "local_chat_write_ready": admission.ready,
        "composer_write_ready": admission.ready,
        "public_write_authorized": admission.release_ready,
        "public_chat_write_ready": admission.release_ready,
        "chat_write_ready": admission.ready,
    }


def authority_readiness(
    settings: Settings,
    *,
    fresh: bool = False,
) -> dict[str, object]:
    """Return schema, research, release, and live connector facts.

    ``ready`` continues to mean that the ordinary workspace persistence
    authorities are present under the constrained runtime role.  Public chat
    additionally requires the durable release and connector observations.
    """

    admission = _effective_admission(settings, fresh=fresh)
    return _authority_readiness_projection(
        settings,
        admission=admission,
    )


def _platform_blockers(admission: _EffectiveAdmission) -> list[str]:
    return [
        blocker
        for blocker in admission.blockers
        if not blocker.startswith("hermes_")
    ]


def platform_delivery_blockers(
    settings: Settings,
    *,
    fresh: bool = False,
) -> list[str]:
    """Return live Platform/release blockers for the ordinary chat surface."""

    admission = _effective_admission(settings, fresh=fresh)
    return _platform_blockers(admission)


def chat_write_blockers(
    settings: Settings,
    *operational: str,
    fresh: bool = False,
) -> dict[str, list[str]]:
    """Return a compatibility envelope backed by current runtime facts."""

    admission = _effective_admission(settings, fresh=fresh)
    upstream = [
        blocker for blocker in admission.blockers if blocker.startswith("hermes_")
    ]
    platform = [
        blocker
        for blocker in admission.blockers
        if not blocker.startswith("hermes_")
    ]
    return {
        "upstream_blockers": upstream,
        "platform_delivery_blockers": platform,
        "blockers": _dedupe([*operational, *admission.blockers]),
    }


def composer_readiness_snapshot(
    settings: Settings,
    *,
    fresh: bool = False,
) -> dict[str, object]:
    """Composite readiness view for authorities, health, and workspace."""

    admission = _effective_admission(settings, fresh=fresh)
    authorities = _authority_readiness_projection(
        settings,
        admission=admission,
    )
    platform = _platform_blockers(admission)
    return {
        **authorities,
        "platform_delivery_blockers": platform,
        "platform_delivery_blocker_count": len(platform),
        "composer_open": bool(authorities["chat_write_ready"]),
    }


__all__ = [
    "UPSTREAM_CHAT_WRITE_BLOCKERS",
    "authority_readiness",
    "chat_write_blockers",
    "composer_readiness_snapshot",
    "platform_delivery_blockers",
]
