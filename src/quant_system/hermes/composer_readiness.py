"""Composer / chat_write readiness surface.

Public composer stays fail-closed by default. This module is the single source
of truth for:

- permanent cutover / security blockers (cleared only by explicit local settings)
- dynamic schema/authority blockers derived from PostgreSQL readiness
- ``chat_write_ready`` / ``composer_write_ready`` / ``mutation_enabled`` flags

Local single-user installs may open mutation via ``QS_LOCAL_MUTATION_ENABLED``
and the composer surface via ``QS_LOCAL_MUTATION_COMPOSER_OPEN``. Trading safety
(kill_switch / paper / dry_run) is independent and stays under SafetySettings.
"""

from __future__ import annotations

from typing import Final

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import command_ledger_schema_version
from quant_system.hermes.session_registry import session_registry_schema_version
from quant_system.hermes.workflow_binding import workflow_binding_schema_version

# Upstream Hermes capability gaps (necessary but not sufficient for chat write).
# Live 0.18.x without durable still lists these; local ephemeral dispatch does
# not clear them for product admission, only for the settings-gated local path.
UPSTREAM_CHAT_WRITE_BLOCKERS: Final[tuple[str, ...]] = (
    "run_submission_not_idempotent",
    "request_recovery_unavailable",
    "event_id_unavailable",
    "event_replay_unavailable",
    "run_status_not_persistent",
    "provider_policy_not_immutable",
    "actual_provider_evidence_unavailable",
    "approval_exact_binding_unavailable",
    "stop_reconciliation_unavailable",
)

# Blockers that remain until an explicit local / cutover setting clears them.
_DEFAULT_PLATFORM_BLOCKERS: Final[tuple[str, ...]] = (
    "authenticated_mutation_bff_unavailable",
    "prompt_retention_boundary_unavailable",
    "composer_resume_stop_unavailable",
    "research_workflow_submission_unavailable",
    "independent_security_review_unavailable",
    "user_chat_cutover_approval_required",
)


def _local_mutation_enabled(settings: Settings) -> bool:
    local = getattr(settings, "local_mutation", None)
    return bool(getattr(local, "enabled", False))


def _local_composer_open(settings: Settings) -> bool:
    local = getattr(settings, "local_mutation", None)
    return bool(getattr(local, "composer_open", False))


def authority_readiness(settings: Settings) -> dict[str, object]:
    """Schema readiness for ledger, session registry, and research workflow binding.

    ``ready`` covers ordinary managed-session create/fork/turn authorities
    (ledger + session registry). ``research_binding_ready`` additionally
    requires the 006 workflow-binding schema.
    """
    ledger_version = command_ledger_schema_version(settings)
    session_version = session_registry_schema_version(settings)
    binding_version = workflow_binding_schema_version(settings)
    ledger_ready = ledger_version is not None
    session_ready = session_version is not None
    binding_ready = binding_version is not None
    core_ready = ledger_ready and session_ready
    research_ready = core_ready and binding_ready
    mutation_on = _local_mutation_enabled(settings)
    composer_wanted = _local_composer_open(settings)
    # Local composer opens only when mutation is on, schemas are research-ready,
    # and the operator explicitly set composer_open.
    composer_ready = bool(mutation_on and composer_wanted and research_ready)
    return {
        "command_ledger_schema_ready": ledger_ready,
        "command_ledger_schema_version": ledger_version,
        "session_registry_schema_ready": session_ready,
        "session_registry_schema_version": session_version,
        "workflow_binding_schema_ready": binding_ready,
        "workflow_binding_schema_version": binding_version,
        "ready": core_ready,
        "research_binding_ready": research_ready,
        # Dark supervised claim/dispatch is schema-gated (V5).
        "dark_dispatch_ready": research_ready,
        "mutation_enabled": mutation_on,
        "composer_write_ready": composer_ready,
        "chat_write_ready": composer_ready,
    }


def platform_delivery_blockers(settings: Settings) -> list[str]:
    """Ordered platform blockers. Settings-gated first, then dynamic schema gaps."""
    mutation_on = _local_mutation_enabled(settings)
    composer_wanted = _local_composer_open(settings)
    ready = authority_readiness(settings)
    blockers: list[str] = []

    if not mutation_on:
        blockers.append("authenticated_mutation_bff_unavailable")
        blockers.append("independent_security_review_unavailable")
        blockers.append("user_chat_cutover_approval_required")

    # Prompt bodies still must not land in platform durable stores. Local
    # supervised dispatch uses metadata/fixed-input resolvers; browser research
    # submission that needs encrypted HQA intent still reports this until the
    # intent path is fully wired into the BFF.
    if not mutation_on:
        blockers.append("prompt_retention_boundary_unavailable")

    # Full composer resume/stop state machine remains a V6 gap even when local
    # mutation BFF is open. Clear only when operator also asks for composer_open.
    if not (mutation_on and composer_wanted):
        blockers.append("composer_resume_stop_unavailable")

    if not (mutation_on and ready["research_binding_ready"]):
        blockers.append("research_workflow_submission_unavailable")

    if not ready["command_ledger_schema_ready"]:
        blockers.append("command_ledger_schema_unavailable")
    if not ready["session_registry_schema_ready"]:
        blockers.append("session_registry_schema_unavailable")
    if not ready["workflow_binding_schema_ready"]:
        blockers.append("hqa_task_attempt_binding_unavailable")
        blockers.append("command_dispatch_adapter_unavailable")
    return _dedupe(blockers)


def chat_write_blockers(
    settings: Settings,
    *operational: str,
) -> dict[str, list[str]]:
    """Full chat blocker envelope used by ``GET /api/hermes/gateway``."""
    # When local composer is intentionally open, suppress the durable-upstream
    # product blockers so the readiness surface matches the authorized path.
    # They remain documented in UPSTREAM_CHAT_WRITE_BLOCKERS for audits.
    if (
        _local_mutation_enabled(settings)
        and _local_composer_open(settings)
        and bool(authority_readiness(settings)["research_binding_ready"])
    ):
        upstream: list[str] = []
    else:
        upstream = list(UPSTREAM_CHAT_WRITE_BLOCKERS)
    platform = platform_delivery_blockers(settings)
    return {
        "upstream_blockers": upstream,
        "platform_delivery_blockers": platform,
        "blockers": _dedupe([*operational, *upstream, *platform]),
    }


def composer_readiness_snapshot(settings: Settings) -> dict[str, object]:
    """Composite readiness view for authorities / health / workspace surfaces."""
    authorities = authority_readiness(settings)
    platform = platform_delivery_blockers(settings)
    return {
        **authorities,
        "platform_delivery_blockers": platform,
        "platform_delivery_blocker_count": len(platform),
        "composer_open": bool(authorities["chat_write_ready"]),
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


__all__ = [
    "UPSTREAM_CHAT_WRITE_BLOCKERS",
    "authority_readiness",
    "chat_write_blockers",
    "composer_readiness_snapshot",
    "platform_delivery_blockers",
]
