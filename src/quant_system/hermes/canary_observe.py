"""V8-M5: project hermetic canary grants onto workspace spine.

``canary_grants[]`` is a separate namespace from approvals/gates/results.
Empty remains honest. Never invents public-write readiness.
"""

from __future__ import annotations

from typing import Any, Mapping

from quant_system.hermes.canary_grant_authority import (
    CanaryGrant,
    DualVerticalAcceptance,
    default_canary_grant_authority,
)


def project_canary_grant_public(
    row: Mapping[str, Any] | CanaryGrant,
) -> dict[str, object]:
    if isinstance(row, CanaryGrant):
        return row.to_public_dict()
    return dict(row)


def project_workspace_canary_grants(workspace_id: str) -> list[dict[str, object]]:
    auth = default_canary_grant_authority()
    return [g.to_public_dict() for g in auth.list_observed(workspace_id)]


def project_workspace_canary_acceptances(
    workspace_id: str,
) -> list[dict[str, object]]:
    auth = default_canary_grant_authority()
    return [a.to_public_dict() for a in auth.list_acceptances(workspace_id)]


def canary_authority_health() -> dict[str, str]:
    """Mounted hermetic canary authority (empty honest)."""
    return {"canary_grant": "ready"}


def note_canary_issued(*, workspace_id: str, grant: CanaryGrant) -> None:
    # Projection is pull-based; hook reserved for future journal/SSE.
    _ = (workspace_id, grant)


def note_canary_revoked(*, workspace_id: str, grant: CanaryGrant) -> None:
    _ = (workspace_id, grant)


def note_canary_accepted(
    *, workspace_id: str, grant: CanaryGrant, acceptance: DualVerticalAcceptance
) -> None:
    _ = (workspace_id, grant, acceptance)


__all__ = [
    "canary_authority_health",
    "note_canary_accepted",
    "note_canary_issued",
    "note_canary_revoked",
    "project_canary_grant_public",
    "project_workspace_canary_acceptances",
    "project_workspace_canary_grants",
]
