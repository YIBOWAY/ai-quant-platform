"""V8-M6: project hermetic public cutover onto workspace spine.

``public_cutovers[]`` is a separate namespace from canary_grants/approvals/gates.
Empty remains honest. Opening cutover surfaces public_flag_open; closing is
G8 rollback and never deletes append-only facts.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_system.hermes.public_cutover_authority import (
    PublicCutover,
    default_public_cutover_authority,
)


def project_public_cutover_public(
    row: Mapping[str, Any] | PublicCutover,
) -> dict[str, object]:
    if isinstance(row, PublicCutover):
        return row.to_public_dict()
    return dict(row)


def project_workspace_public_cutovers(workspace_id: str) -> list[dict[str, object]]:
    auth = default_public_cutover_authority()
    return [c.to_public_dict() for c in auth.list_observed(workspace_id)]


def public_cutover_authority_health() -> dict[str, str]:
    """Mounted hermetic public cutover authority (empty honest)."""
    return {"public_cutover": "ready"}


def workspace_public_flag_open(workspace_id: str) -> bool:
    return default_public_cutover_authority().is_public_flag_open(workspace_id)


def note_public_cutover_opened(*, workspace_id: str, cutover: PublicCutover) -> None:
    _ = (workspace_id, cutover)


def note_public_cutover_closed(*, workspace_id: str, cutover: PublicCutover) -> None:
    _ = (workspace_id, cutover)


__all__ = [
    "note_public_cutover_closed",
    "note_public_cutover_opened",
    "project_public_cutover_public",
    "project_workspace_public_cutovers",
    "public_cutover_authority_health",
    "workspace_public_flag_open",
]
