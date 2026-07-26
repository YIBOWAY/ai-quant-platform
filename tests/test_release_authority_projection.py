"""Production public-cutover projection must come from durable ReleaseAuthority."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.public_cutover_observe import (
    project_durable_workspace_public_cutovers,
)
from quant_system.hermes.release_authority import (
    PublicCutoverRecord,
    ReleaseAuthorityUnavailable,
)

WORKSPACE_ID = "ws-release-projection"
OPENED_AT = datetime(2026, 7, 25, 8, 0, tzinfo=UTC)


class _ReleaseReader:
    def __init__(
        self,
        rows: tuple[PublicCutoverRecord, ...] = (),
        *,
        unavailable: bool = False,
    ) -> None:
        self.rows = rows
        self.unavailable = unavailable
        self.calls: list[tuple[str, int]] = []

    def list_public_cutovers(
        self,
        workspace_id: str,
        *,
        limit: int = 20,
    ) -> tuple[PublicCutoverRecord, ...]:
        self.calls.append((workspace_id, limit))
        if self.unavailable:
            raise ReleaseAuthorityUnavailable("test outage")
        return self.rows


def _cutover(
    cutover_id: str,
    *,
    status: str,
    opened_at: datetime,
    closed_at: datetime | None = None,
) -> PublicCutoverRecord:
    return PublicCutoverRecord(
        cutover_id=cutover_id,
        stamp_id=f"stamp-{cutover_id}",
        workspace_id=WORKSPACE_ID,
        route="/hermes",
        release_digest="1" * 64,
        cutover_digest=("2" if status == "open" else "3") * 64,
        status=status,  # type: ignore[arg-type]
        opened_at=opened_at,
        closed_at=closed_at,
        close_reason=("operator rollback" if closed_at is not None else None),
        candidate_admission_id="admission-1",
        candidate_admission_digest="4" * 64,
        candidate_acceptance_digest="5" * 64,
        evidence_set_id="evidence-1",
        evidence_set_digest="6" * 64,
        final_order_snapshot_digest="7" * 64,
        paper_authority_epoch=3,
    )


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def test_durable_projection_exposes_open_and_closed_postgres_facts() -> None:
    reader = _ReleaseReader(
        (
            _cutover("cutover-open", status="open", opened_at=OPENED_AT),
            _cutover(
                "cutover-closed",
                status="closed",
                opened_at=OPENED_AT - timedelta(hours=2),
                closed_at=OPENED_AT - timedelta(hours=1),
            ),
        )
    )

    projection = project_durable_workspace_public_cutovers(
        _settings(),
        WORKSPACE_ID,
        authority=reader,
    )

    assert projection.health == "ready"
    assert reader.calls == [(WORKSPACE_ID, 20)]
    assert [row["status"] for row in projection.rows] == ["open", "closed"]
    opened = projection.rows[0]
    assert opened == {
        "authority_source": "postgres_release_authority",
        "candidate_acceptance_digest": "5" * 64,
        "candidate_admission_digest": "4" * 64,
        "candidate_admission_id": "admission-1",
        "cutover_digest": "2" * 64,
        "cutover_id": "cutover-open",
        "cutover_ref": "cutover:cutover-open",
        "evidence_set_digest": "6" * 64,
        "evidence_set_id": "evidence-1",
        "final_order_snapshot_digest": "7" * 64,
        "kind": "agent_v0_2.release.public_cutover",
        "opened_at": "2026-07-25T08:00:00.000000Z",
        "paper_authority_epoch": 3,
        "public_flag_open": True,
        "release_digest": "1" * 64,
        "route": "/hermes",
        "stamp_id": "stamp-cutover-open",
        "status": "open",
    }
    assert projection.rows[1]["closed_at"] == "2026-07-25T07:00:00.000000Z"
    assert projection.rows[1]["close_reason"] == "operator rollback"
    assert projection.rows[1]["public_flag_open"] is False
    assert "chat_write_ready" not in opened
    assert "public_write_authorized" not in opened


def test_durable_projection_reports_unavailable_empty_instead_of_falling_back() -> None:
    projection = project_durable_workspace_public_cutovers(
        _settings(),
        WORKSPACE_ID,
        authority=_ReleaseReader(unavailable=True),
    )

    assert projection.rows == ()
    assert projection.health == "unavailable"


def test_production_workspace_snapshot_and_follow_use_release_reader() -> None:
    reader = _ReleaseReader(
        (_cutover("cutover-open", status="open", opened_at=OPENED_AT),)
    )
    workspace = PlatformAgentWorkspace(
        _settings(),
        release_cutover_reader=reader,
    )

    snapshot = workspace.snapshot(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
    )
    follow = workspace.follow(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
        after=0,
    )

    assert snapshot.public_cutovers[0]["cutover_id"] == "cutover-open"
    assert snapshot.authority_health["public_cutover"] == "ready"
    assert follow.public_cutovers is not None
    assert follow.public_cutovers[0]["cutover_id"] == "cutover-open"
    assert follow.authority_health is not None
    assert follow.authority_health["public_cutover"] == "ready"
    assert len(reader.calls) == 2


@pytest.mark.parametrize(
    "action",
    [
        {
            "schema_version": 1,
            "kind": "public.cutover.open",
            "client_action_id": "legacy-open",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "build_digest": "8" * 64,
            "route": "/hermes",
            "acceptance_id": "legacy-acceptance",
            "open_note": "must use the operator release CLI",
        },
        {
            "schema_version": 1,
            "kind": "public.cutover.close",
            "client_action_id": "legacy-close",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "cutover_ref": "cutover:legacy-cutover",
            "expected_cutover_digest": "9" * 64,
            "reason": "must use the operator release CLI",
        },
    ],
)
def test_production_legacy_cutover_actions_require_operator_cli(
    action: dict[str, object],
) -> None:
    workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)

    receipt = workspace.act(str(ROOT_USER_ID), action)
    public = receipt.to_public_dict()

    assert receipt.status == "unavailable"
    assert receipt.reason_code == "release_operator_cli_required"
    assert receipt.public_flag_open is False
    assert public["public_write_authorized"] is False
    assert public["chat_write_ready"] is False
