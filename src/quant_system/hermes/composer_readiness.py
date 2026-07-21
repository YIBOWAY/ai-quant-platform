"""Composer / chat_write readiness surface (V4).

Public composer stays fail-closed. This module is the single source of truth for:

- permanent cutover / security blockers that never clear in V4
- dynamic schema/authority blockers derived from PostgreSQL readiness
- the always-false ``chat_write_ready`` / ``composer_write_ready`` flags

It does **not** enable writes. Callers (gateway health, workspace authorities,
snapshot health) import from here so blocker strings stay consistent.
"""

from __future__ import annotations

from typing import Final

from quant_system.config.settings import Settings
from quant_system.hermes.command_ledger import command_ledger_schema_version
from quant_system.hermes.session_registry import session_registry_schema_version
from quant_system.hermes.workflow_binding import workflow_binding_schema_version

# Upstream Hermes capability gaps (necessary but not sufficient for chat write).
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

# Platform delivery blockers that remain until explicit later-slice cutover.
# These never clear as a side-effect of schema readiness alone.
_PERMANENT_PLATFORM_BLOCKERS: Final[tuple[str, ...]] = (
    # Owner session + CSRF exist; public mutation BFF gate still hard OFF.
    "authenticated_mutation_bff_unavailable",
    # Prompt body must not land in platform durable stores (HQA intent only).
    "prompt_retention_boundary_unavailable",
    # V5 supervised claim/dispatch worker not authorized.
    "command_dispatch_adapter_unavailable",
    # V6 resume/stop composer state machine not delivered.
    "composer_resume_stop_unavailable",
    # Browser research.start → HQA prepare → ensure_bound_command path not open.
    "research_workflow_submission_unavailable",
    # Independent security review still required before any public write.
    "independent_security_review_unavailable",
    # Explicit user cutover approval still required (V8).
    "user_chat_cutover_approval_required",
)


def authority_readiness(settings: Settings) -> dict[str, object]:
    """Schema readiness for ledger, session registry, and research workflow binding.

    ``ready`` covers ordinary managed-session create/fork/turn authorities
    (ledger + session registry). ``research_binding_ready`` additionally
    requires the 006 workflow-binding schema. Neither flag implies public
    mutation is allowed.
    """
    ledger_version = command_ledger_schema_version(settings)
    session_version = session_registry_schema_version(settings)
    binding_version = workflow_binding_schema_version(settings)
    ledger_ready = ledger_version is not None
    session_ready = session_version is not None
    binding_ready = binding_version is not None
    core_ready = ledger_ready and session_ready
    research_ready = core_ready and binding_ready
    return {
        "command_ledger_schema_ready": ledger_ready,
        "command_ledger_schema_version": ledger_version,
        "session_registry_schema_ready": session_ready,
        "session_registry_schema_version": session_version,
        "workflow_binding_schema_ready": binding_ready,
        "workflow_binding_schema_version": binding_version,
        "ready": core_ready,
        "research_binding_ready": research_ready,
        # Public write flags — hard OFF for the entire V4 surface.
        "mutation_enabled": False,
        "composer_write_ready": False,
        "chat_write_ready": False,
    }


def platform_delivery_blockers(settings: Settings) -> list[str]:
    """Ordered platform blockers. Permanent first, then dynamic schema gaps."""
    blockers: list[str] = list(_PERMANENT_PLATFORM_BLOCKERS)
    ready = authority_readiness(settings)
    if not ready["command_ledger_schema_ready"]:
        blockers.append("command_ledger_schema_unavailable")
    if not ready["session_registry_schema_ready"]:
        blockers.append("session_registry_schema_unavailable")
    # hqa_task_attempt_binding_unavailable tracks the 006 schema itself.
    # Even when the schema is ready on an isolated DB, research browser
    # submission stays blocked via research_workflow_submission_unavailable.
    if not ready["workflow_binding_schema_ready"]:
        blockers.append("hqa_task_attempt_binding_unavailable")
    return _dedupe(blockers)


def chat_write_blockers(
    settings: Settings,
    *operational: str,
) -> dict[str, list[str]]:
    """Full chat blocker envelope used by ``GET /api/hermes/gateway``."""
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
        # Explicit: schema readiness never opens the composer in V4.
        "composer_open": False,
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
