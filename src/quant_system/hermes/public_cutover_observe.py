"""Project public cutover facts onto the workspace spine.

Production reads exclusively from PostgreSQL :class:`ReleaseAuthority`.
The V8-M6 in-process authority remains an explicitly hermetic contract-test
adapter and is reachable only through the legacy helper used by hermetic
workspaces.

``public_cutovers[]`` is a separate namespace from canary_grants/approvals/gates.
Empty remains honest. A raw durable cutover row reports whether that cutover is
open; it never claims that the current runtime still passes the effective
release gate. Composer/write readiness is projected separately.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from quant_system.config.settings import Settings
from quant_system.hermes.public_cutover_authority import (
    PublicCutover,
    default_public_cutover_authority,
)
from quant_system.hermes.release_authority import (
    PublicCutoverRecord,
    ReleaseAuthority,
    ReleaseAuthorityError,
)


class DurablePublicCutoverReader(Protocol):
    """Read-only seam implemented by PostgreSQL ReleaseAuthority."""

    def list_public_cutovers(
        self,
        workspace_id: str,
        *,
        limit: int = 20,
    ) -> tuple[PublicCutoverRecord, ...]: ...


@dataclass(frozen=True)
class DurablePublicCutoverProjection:
    rows: tuple[dict[str, object], ...]
    health: str


def _public_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("release authority timestamp must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def project_durable_public_cutover(
    row: PublicCutoverRecord,
) -> dict[str, object]:
    """Return one bounded durable cutover fact without readiness claims."""

    payload: dict[str, object] = {
        "authority_source": "postgres_release_authority",
        "cutover_digest": row.cutover_digest,
        "cutover_id": row.cutover_id,
        "cutover_ref": f"cutover:{row.cutover_id}",
        "kind": "agent_v0_2.release.public_cutover",
        "opened_at": _public_timestamp(row.opened_at),
        "public_flag_open": row.status == "open",
        "release_digest": row.release_digest,
        "route": row.route,
        "stamp_id": row.stamp_id,
        "status": row.status,
    }
    optional: tuple[tuple[str, object | None], ...] = (
        ("closed_at", None if row.closed_at is None else _public_timestamp(row.closed_at)),
        ("close_reason", row.close_reason),
        ("candidate_admission_id", row.candidate_admission_id),
        ("candidate_admission_digest", row.candidate_admission_digest),
        ("candidate_acceptance_digest", row.candidate_acceptance_digest),
        ("evidence_set_id", row.evidence_set_id),
        ("evidence_set_digest", row.evidence_set_digest),
        ("final_order_snapshot_digest", row.final_order_snapshot_digest),
        ("paper_authority_epoch", row.paper_authority_epoch),
    )
    payload.update({key: value for key, value in optional if value is not None})
    return payload


def project_durable_workspace_public_cutovers(
    settings: Settings,
    workspace_id: str,
    *,
    authority: DurablePublicCutoverReader | None = None,
    limit: int = 20,
) -> DurablePublicCutoverProjection:
    """Read current + recent historical cutovers from the canonical PG store.

    An authority outage is represented as unavailable-empty. It never falls
    back to the restart-volatile hermetic store.
    """

    reader = authority or ReleaseAuthority(settings)
    try:
        records = reader.list_public_cutovers(workspace_id, limit=limit)
        rows = tuple(project_durable_public_cutover(record) for record in records)
    except (ReleaseAuthorityError, ValueError):
        return DurablePublicCutoverProjection(rows=(), health="unavailable")
    return DurablePublicCutoverProjection(rows=rows, health="ready")


def project_public_cutover_public(
    row: Mapping[str, Any] | PublicCutover,
) -> dict[str, object]:
    if isinstance(row, PublicCutover):
        return row.to_public_dict()
    return dict(row)


def project_workspace_public_cutovers(workspace_id: str) -> list[dict[str, object]]:
    """Project the legacy in-process authority for hermetic tests only."""

    auth = default_public_cutover_authority()
    return [c.to_public_dict() for c in auth.list_observed(workspace_id)]


def public_cutover_authority_health() -> dict[str, str]:
    """Mounted hermetic public cutover authority (contract tests only)."""

    return {"public_cutover": "ready"}


def workspace_public_flag_open(workspace_id: str) -> bool:
    return default_public_cutover_authority().is_public_flag_open(workspace_id)


def note_public_cutover_opened(*, workspace_id: str, cutover: PublicCutover) -> None:
    _ = (workspace_id, cutover)


def note_public_cutover_closed(*, workspace_id: str, cutover: PublicCutover) -> None:
    _ = (workspace_id, cutover)


__all__ = [
    "DurablePublicCutoverProjection",
    "DurablePublicCutoverReader",
    "note_public_cutover_closed",
    "note_public_cutover_opened",
    "project_durable_public_cutover",
    "project_durable_workspace_public_cutovers",
    "project_public_cutover_public",
    "project_workspace_public_cutovers",
    "public_cutover_authority_health",
    "workspace_public_flag_open",
]
