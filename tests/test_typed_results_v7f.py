"""V7f-Typed-Results-M1: hermetic typed results on snapshot/follow spine."""

from __future__ import annotations

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import WorkspaceRef
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.result_observe import (
    default_result_observe_journal,
    project_result_public,
    project_workspace_results,
    reset_default_result_observe_journal,
    result_authority_health,
)
from quant_system.hermes.result_surface_authority import (
    ResultSurfaceAuthorityError,
    default_result_surface_authority,
    reset_default_result_surface_authority,
)

WS = "ws-v7f-results"


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    yield
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def test_seed_options_vertical_a_sample_fields() -> None:
    auth = default_result_surface_authority()
    row = auth.seed_options_vertical_a_sample(
        workspace_id=WS,
        result_id="res-aapl-1",
        ticker="AAPL",
        expiry="2026-08-21",
        strike=200,
        bid=1.2,
        ask=1.35,
        delta=0.25,
        iv=0.28,
        apr=0.18,
        task_id="task-1",
        run_id="run-1",
        artifact_id="art-1",
    )
    public = row.to_public_dict()
    assert public["kind"] == "options_vertical_a"
    assert public["sample_or_real"] == "sample"
    assert public["ticker"] == "AAPL"
    assert public["strike"] == 200
    assert public["delta"] == 0.25
    assert public["iv"] == 0.28
    assert public["apr"] == 0.18
    assert "hermetic_fixture" in public["limitations"]
    assert "not_live_futu_quote" in public["limitations"]
    assert public["exact_links"]["task_ref"] == "task:task-1"
    assert public["exact_links"]["run_ref"] == "run:run-1"
    assert public["id"] == "res-aapl-1"


def test_sample_vs_real_marking() -> None:
    auth = default_result_surface_authority()
    auth.seed_result(
        workspace_id=WS,
        result_id="real-1",
        kind="backtest",
        display_title="Real BT",
        sample_or_real="real",
        freshness="fresh",
    )
    rows = project_workspace_results(WS)
    assert len(rows) == 1
    assert rows[0]["sample_or_real"] == "real"


def test_empty_honest_and_health_ready() -> None:
    assert project_workspace_results(WS) == []
    assert result_authority_health() == {"result": "ready"}


def test_snapshot_carries_typed_results_not_gates() -> None:
    auth = default_result_surface_authority()
    auth.seed_options_vertical_a_sample(
        workspace_id=WS,
        result_id="res-snap",
        ticker="MSFT",
        expiry="2026-09-18",
        strike=400,
        bid=2.0,
        ask=2.1,
        delta=0.3,
        iv=0.22,
        apr=0.15,
    )
    ws = PlatformAgentWorkspace(
        _settings(),
        mutation_enabled=False,
        hermetic_authorities=True,
    )
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS))
    public = snap.to_public_dict()
    assert len(public["results"]) == 1
    assert public["results"][0]["result_id"] == "res-snap"
    assert public["results"][0]["ticker"] == "MSFT"
    assert public["results"][0]["sample_or_real"] == "sample"
    assert public["gates"] == []
    assert public["approvals"] == []
    assert public["tasks"] == []
    assert public["authority_health"]["result"] == "hermetic"
    # Never invent Task from result link alone
    assert public["tasks"] == []


def test_results_fingerprint_changes_on_seed() -> None:
    journal = default_result_observe_journal()
    auth = default_result_surface_authority()
    auth.seed_result(
        workspace_id=WS,
        result_id="fp-1",
        kind="generic",
        display_title="FP",
    )
    rows1 = project_workspace_results(WS)
    first = journal.take_results_if_changed(WS, rows1)
    assert first is not None
    second = journal.take_results_if_changed(WS, rows1)
    assert second is None
    auth.seed_result(
        workspace_id=WS,
        result_id="fp-2",
        kind="generic",
        display_title="FP2",
    )
    rows2 = project_workspace_results(WS)
    third = journal.take_results_if_changed(WS, rows2)
    assert third is not None
    assert len(third) == 2


def test_project_result_public_never_looks_like_gate_or_approval() -> None:
    row = project_result_public(
        {
            "result_id": "x",
            "kind": "generic",
            "display_title": "X",
            "status": "ready",
            "sample_or_real": "sample",
            "freshness": "unknown",
            "read_status": "available",
            "occurred_at": "2026-07-23T00:00:00.000000Z",
        }
    )
    assert "gate_id" not in row
    assert "approval_id" not in row
    assert row["result_id"] == "x"
    assert row["id"] == "x"


def test_rejects_invalid_kind_and_mark() -> None:
    auth = default_result_surface_authority()
    with pytest.raises(ResultSurfaceAuthorityError):
        auth.seed_result(
            workspace_id=WS,
            result_id="bad",
            kind="not_a_kind",
            display_title="x",
        )
    with pytest.raises(ResultSurfaceAuthorityError):
        auth.seed_result(
            workspace_id=WS,
            result_id="bad2",
            kind="generic",
            display_title="x",
            sample_or_real="maybe",
        )


def test_no_invented_exact_links_when_absent() -> None:
    auth = default_result_surface_authority()
    auth.seed_result(
        workspace_id=WS,
        result_id="nolink",
        kind="generic",
        display_title="No links",
    )
    rows = project_workspace_results(WS)
    assert "exact_links" not in rows[0]
    assert "task_id" not in rows[0]


def test_project_result_public_mapping_fail_closed() -> None:
    """Invalid/missing mark → sample; invalid/missing read_status → unavailable."""
    from quant_system.hermes.result_observe import project_result_public

    bare = project_result_public({"result_id": "r1", "display_title": "t"})
    assert bare["sample_or_real"] == "sample"
    assert bare["read_status"] == "unavailable"
    assert bare["status"] == "unknown"

    weird = project_result_public(
        {
            "result_id": "r2",
            "display_title": "t",
            "sample_or_real": "live",
            "read_status": "ok",
        }
    )
    assert weird["sample_or_real"] == "sample"
    assert weird["read_status"] == "unavailable"

    real = project_result_public(
        {
            "result_id": "r3",
            "display_title": "t",
            "sample_or_real": "real",
            "read_status": "available",
        }
    )
    assert real["sample_or_real"] == "real"
    assert real["read_status"] == "available"


def test_seed_options_helper_coerces_real_with_hermetic_limitations() -> None:
    """Hermetic limitations cannot wear REAL badge via convenience seeder."""
    from quant_system.hermes.result_surface_authority import (
        default_result_surface_authority,
    )

    auth = default_result_surface_authority()
    row = auth.seed_options_vertical_a_sample(
        workspace_id=WS,
        result_id="opt-real-footgun",
        ticker="AAPL",
        expiry="2026-08-21",
        strike=200,
        bid=1.0,
        ask=1.1,
        delta=0.2,
        iv=0.3,
        apr=0.1,
        sample_or_real="real",  # footgun attempt
    )
    assert row.sample_or_real == "sample"
    assert "hermetic_fixture" in row.limitations
