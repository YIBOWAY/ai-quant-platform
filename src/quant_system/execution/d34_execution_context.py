"""Resolve the current durable D-34 authority into paper-policy inputs."""

from __future__ import annotations

from quant_system.config.settings import Settings
from quant_system.hermes.d34_safety_authority import (
    D34SafetyAuthority,
    D34SafetyAuthorityError,
)


def resolve_d34_execution_policy_context(
    settings: Settings,
    *,
    workspace_id: str,
) -> dict[str, object]:
    """Return a fail-closed context; caller input can never grant authority."""
    try:
        safety = D34SafetyAuthority(settings).observe(workspace_id=workspace_id)
    except (D34SafetyAuthorityError, OSError, ValueError) as exc:
        return {
            "contract": "hqa.d34_execution_policy_context/v1",
            "workspace_id": workspace_id,
            "paper_execution_enabled": False,
            "emergency_stop": False,
            "mandate_active": False,
            "mandate_paper_execution_allowed": False,
            "blockers": [str(getattr(exc, "code", "d34_safety_unavailable"))],
        }
    active_mandate = safety.get("active_mandate")
    mandate = active_mandate if isinstance(active_mandate, dict) else {}
    d34_raw = safety.get("d34")
    d34 = d34_raw if isinstance(d34_raw, dict) else {}
    emergency_raw = safety.get("emergency_stop")
    emergency = emergency_raw if isinstance(emergency_raw, dict) else {}
    return {
        "contract": "hqa.d34_execution_policy_context/v1",
        "workspace_id": workspace_id,
        "paper_execution_enabled": safety.get("paper_execution_enabled") is True,
        "emergency_stop": emergency.get("active") is True,
        "mandate_active": d34.get("mandate_active") is True,
        "mandate_paper_execution_allowed": (
            mandate.get("paper_execution_allowed") is True
        ),
        "mandate_id": mandate.get("mandate_id"),
        "blockers": list(safety.get("blockers", [])),
    }


__all__ = ["resolve_d34_execution_policy_context"]
