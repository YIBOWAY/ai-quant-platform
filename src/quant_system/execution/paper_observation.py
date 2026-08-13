"""Hung paper sleeves may fill while live stays killed.

The global kill_switch means live/danger is frozen. It is not a paper
observation freeze. Emergency stop and unknown authority still freeze hung
fills. Only allocated, automation-managed, paper_only sleeves qualify.
"""

from __future__ import annotations

from typing import Any, Mapping

from quant_system.config.settings import Settings

_AUTHORITY_OUTAGE_CODES = frozenset(
    {"d34_authority_unavailable", "d34_safety_unavailable"}
)


def hung_sleeve_eligible(sleeve: Any) -> bool:
    metadata = getattr(sleeve, "metadata", None) or {}
    mode = getattr(getattr(sleeve, "mode", None), "value", getattr(sleeve, "mode", ""))
    status = getattr(
        getattr(sleeve, "status", None),
        "value",
        getattr(sleeve, "status", ""),
    )
    return (
        str(mode) == "allocated"
        and str(status) == "running"
        and metadata.get("automation_managed") is True
        and str(metadata.get("promotion_scope", "")) == "paper_only"
    )


def hung_observation_allows_fill(
    settings: Settings,
    *,
    emergency_stop: bool,
    authority_available: bool = True,
    sleeve_eligible: bool = True,
) -> bool:
    return (
        sleeve_eligible is True
        and authority_available is True
        and settings.safety.paper_trading is True
        and settings.safety.paper_observation_enabled is True
        and settings.safety.live_trading_enabled is not True
        and emergency_stop is False
    )


def hung_observation_open_for_sleeve(
    settings: Settings,
    sleeve: Any,
    context: Mapping[str, Any] | None = None,
) -> bool:
    payload = context or {}
    blockers = payload.get("blockers") or []
    authority_available = payload.get("authority_available", True) is True
    if any(str(code) in _AUTHORITY_OUTAGE_CODES for code in blockers):
        authority_available = False
    return hung_observation_allows_fill(
        settings,
        emergency_stop=payload.get("emergency_stop") is True,
        authority_available=authority_available,
        sleeve_eligible=hung_sleeve_eligible(sleeve),
    )


__all__ = [
    "hung_observation_allows_fill",
    "hung_observation_open_for_sleeve",
    "hung_sleeve_eligible",
]
