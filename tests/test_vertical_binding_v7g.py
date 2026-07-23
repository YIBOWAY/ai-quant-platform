"""V7g-A-M1: hermetic Vertical A options research binding on spine."""

from __future__ import annotations

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import (
    BindOptionsVerticalA,
    WorkspaceRef,
    action_to_document,
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.result_observe import (
    project_workspace_results,
    reset_default_result_observe_journal,
)
from quant_system.hermes.result_surface_authority import (
    default_result_surface_authority,
    reset_default_result_surface_authority,
)
from quant_system.hermes.submission_saga import submit_action
from quant_system.hermes.vertical_binding_authority import (
    default_vertical_binding_authority,
    reset_default_vertical_binding_authority,
)
from quant_system.hermes.vertical_observe import (
    default_vertical_observe_journal,
    project_workspace_tasks,
    reset_default_vertical_observe_journal,
    vertical_authority_health,
)

WS = "ws-v7g-vertical-a"


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    yield
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _bind_doc(
    *,
    client_action_id: str = "act-v7g-1",
    include_provider_evidence: bool = True,
    ticker: str = "AAPL",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "vertical.options_a.bind",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "ticker": ticker,
        "goal_note": "研究 AAPL 卖 Put",
        "expiry": "2026-08-15",
        "strike": 180.0,
        "bid": 2.35,
        "ask": 2.45,
        "delta": -0.25,
        "iv": 0.28,
        "apr": 0.12,
        "include_provider_evidence": include_provider_evidence,
        "provider_mode": "hermetic_fixture",
        "auth_envelope": None,
    }


def test_parse_and_digest_bind_stable() -> None:
    doc = _bind_doc()
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is BindOptionsVerticalA
    assert parsed.ticker == "AAPL"
    assert action_to_document(parsed) == doc
    d1 = canonical_action_digest(parsed)
    d2 = canonical_action_digest(parse_user_action_v1(doc))
    assert d1 == d2
    assert len(d1) == 64


def test_bind_completed_with_evidence_and_snapshot() -> None:
    doc = _bind_doc(include_provider_evidence=True)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.task_id
    assert receipt.attempt_id
    assert receipt.run_id
    assert receipt.result_id
    assert receipt.terminal_status == "completed"

    tasks = project_workspace_tasks(WS)
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == receipt.task_id
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["result_id"] == receipt.result_id

    results = project_workspace_results(WS)
    assert len(results) == 1
    row = results[0]
    assert row["result_id"] == receipt.result_id
    assert row["kind"] == "options_vertical_a"
    assert row["sample_or_real"] == "sample"  # hermetic never REAL
    assert row["ticker"] == "AAPL"
    assert row["apr"] == 0.12
    assert row["status"] == "completed"
    assert row["task_id"] == receipt.task_id
    assert row["attempt_id"] == receipt.attempt_id
    assert row["run_id"] == receipt.run_id
    assert "hermetic_fixture_apr" in (row.get("provider_evidence") or [])
    assert "not_live_futu_quote" in (row.get("limitations") or [])
    assert "not_tradeable" in (row.get("limitations") or [])

    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS)).to_public_dict()
    assert receipt.task_id in snap["tasks"]
    assert receipt.attempt_id in snap["attempts"]
    assert receipt.run_id in snap["runs"]
    assert len(snap["results"]) == 1
    assert snap["results"][0]["result_id"] == receipt.result_id
    health = snap["authority_health"]
    assert health["task"] == "ready"
    assert health["attempt"] == "ready"
    assert health["run"] == "ready"
    assert health["result"] == "ready"
    # Never invent approvals/gates from bind
    assert snap["approvals"] == []
    assert snap["gates"] == []


def test_bind_completed_degraded_without_evidence() -> None:
    doc = _bind_doc(
        client_action_id="act-v7g-degraded",
        include_provider_evidence=False,
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.terminal_status == "completed_degraded"

    results = project_workspace_results(WS)
    assert len(results) == 1
    row = results[0]
    assert row["status"] == "completed_degraded"
    assert row["sample_or_real"] == "sample"
    assert row["read_status"] == "degraded"
    assert not row.get("provider_evidence")
    assert "unverified_without_provider_evidence" in (row.get("limitations") or [])


def test_bind_idempotent_replay() -> None:
    doc = _bind_doc(client_action_id="act-v7g-idem")
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    r2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    assert r2.status == "accepted"
    assert r1.task_id == r2.task_id
    assert r1.result_id == r2.result_id
    assert r1.action_digest == r2.action_digest
    # Single task / single result
    assert len(project_workspace_tasks(WS)) == 1
    assert len(project_workspace_results(WS)) == 1


def test_bind_digest_conflict() -> None:
    doc = _bind_doc(client_action_id="act-v7g-conflict")
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    bad = dict(doc)
    bad["goal_note"] = "不同的目标备注造成 digest 冲突"
    r2 = submit_action(_settings(), bad, mutation_enabled=True)
    assert r2.status == "conflict"
    assert len(project_workspace_tasks(WS)) == 1


def test_mutation_off_fail_closed() -> None:
    doc = _bind_doc(client_action_id="act-v7g-off")
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    assert project_workspace_tasks(WS) == []
    assert project_workspace_results(WS) == []


def test_conversation_turn_does_not_invent_task() -> None:
    """Ordinary conversation.turn must not create Task/Attempt/Run rows."""
    doc = {
        "schema_version": 1,
        "kind": "conversation.turn",
        "client_action_id": "act-turn-no-task",
        "workspace": {"workspace_id": WS},
        "session_ref": "session:s-hermetic",
        "prompt": "hello without vertical bind",
    }
    # May be unavailable without session registry; either way zero tasks.
    try:
        submit_action(_settings(), doc, mutation_enabled=True)
    except Exception:
        pass
    assert project_workspace_tasks(WS) == []
    assert vertical_authority_health() == {
        "task": "ready",
        "attempt": "ready",
        "run": "ready",
    }


def test_start_research_still_dark() -> None:
    """Bind is separate; StartResearch remains dark with explicit reason_code."""
    from quant_system.hermes.agent_workspace_actions import StartResearch

    doc = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "act-research-dark",
        "workspace": {"workspace_id": WS},
        "managed_session_ref": "session:s-research-dark",
        "payload_ref": "payload:sha256:" + ("a" * 64),
        "payload_digest": "a" * 64,
        "initial_mode": "plan_only",
    }
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is StartResearch
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"
    # Bind path still works independently; research never invents vertical rows.
    assert project_workspace_tasks(WS) == []
    bind = parse_user_action_v1(_bind_doc(client_action_id="act-vs-research"))
    assert type(bind) is BindOptionsVerticalA


def test_follow_page_carries_vertical_ids() -> None:
    """MAJOR-2: EventPage (follow) attaches task/attempt/run ids, not only snapshot."""
    doc = _bind_doc(client_action_id="act-v7g-follow")
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    page = ws.follow(
        ROOT_USER_ID, WorkspaceRef(workspace_id=WS), after=0
    ).to_public_dict()
    assert receipt.task_id in (page.get("tasks") or [])
    assert receipt.attempt_id in (page.get("attempts") or [])
    assert receipt.run_id in (page.get("runs") or [])
    assert isinstance(page.get("results"), list)
    assert any(r.get("result_id") == receipt.result_id for r in page["results"])
    health = page.get("authority_health") or {}
    assert health.get("task") == "ready"
    assert health.get("attempt") == "ready"
    assert health.get("run") == "ready"


def test_vertical_observe_journal_fingerprint() -> None:
    journal = default_vertical_observe_journal()
    first = journal.take_vertical_ids_if_changed(WS, ["t1"], ["a1"], ["r1"])
    assert first == {"tasks": ["t1"], "attempts": ["a1"], "runs": ["r1"]}
    second = journal.take_vertical_ids_if_changed(WS, ["t1"], ["a1"], ["r1"])
    assert second is None
    third = journal.take_vertical_ids_if_changed(WS, ["t1", "t2"], ["a1"], ["r1"])
    assert third is not None
    assert third["tasks"] == ["t1", "t2"]


def test_concurrent_bind_same_action_no_orphan_results() -> None:
    """MAJOR-1: concurrent identical binds must not orphan typed results."""
    import concurrent.futures

    doc = _bind_doc(client_action_id="act-v7g-race-same")
    settings = _settings()

    def _once() -> object:
        return submit_action(settings, doc, mutation_enabled=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_once) for _ in range(16)]
        receipts = [f.result() for f in futs]
    assert all(r.status == "accepted" for r in receipts)
    task_ids = {r.task_id for r in receipts}
    result_ids = {r.result_id for r in receipts}
    assert len(task_ids) == 1
    assert len(result_ids) == 1
    assert len(project_workspace_tasks(WS)) == 1
    assert len(project_workspace_results(WS)) == 1
    # Result store has exactly the bound result for this workspace.
    rauth = default_result_surface_authority()
    observed = rauth.list_observed(WS, limit=100)
    assert len(observed) == 1
    assert observed[0].result_id == next(iter(result_ids))


def test_concurrent_bind_digest_conflict_no_orphan_results() -> None:
    """MAJOR-1: loser of digest conflict must not leave orphan result rows."""
    import concurrent.futures

    settings = _settings()
    base = _bind_doc(client_action_id="act-v7g-race-conflict")
    alt = dict(base)
    alt["goal_note"] = "冲突目标备注 — different digest"

    def _submit(doc: dict) -> object:
        return submit_action(settings, doc, mutation_enabled=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = []
        for i in range(16):
            futs.append(pool.submit(_submit, base if i % 2 == 0 else alt))
        receipts = [f.result() for f in futs]
    accepted = [r for r in receipts if r.status == "accepted"]
    conflicts = [r for r in receipts if r.status == "conflict"]
    assert accepted, "at least one bind must win"
    assert conflicts, "digest mismatch must surface as conflict"
    # Exactly one logical binding survives.
    assert len(project_workspace_tasks(WS)) == 1
    assert len(project_workspace_results(WS)) == 1
    winner_result = accepted[0].result_id
    assert all(r.result_id == winner_result for r in accepted)
    rauth = default_result_surface_authority()
    observed = rauth.list_observed(WS, limit=100)
    assert len(observed) == 1
    assert observed[0].result_id == winner_result
    # No binder rows without matching result, and no extra results.
    binder = default_vertical_binding_authority()
    tasks = binder.list_tasks(WS)
    assert len(tasks) == 1
    assert tasks[0].result_id == winner_result


def test_no_live_futu_markers_on_result() -> None:
    submit_action(
        _settings(),
        _bind_doc(client_action_id="act-no-futu"),
        mutation_enabled=True,
    )
    row = project_workspace_results(WS)[0]
    lim = " ".join(row.get("limitations") or [])
    assert "not_live_futu_quote" in lim
    assert "not_tradeable" in lim
    assert "zero_orders" in lim or "not_tradeable" in lim
    assert row["sample_or_real"] == "sample"
    assert row.get("source") == "hermetic_vertical_a_binding"
