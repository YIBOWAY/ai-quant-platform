"""V7g-B-M2: hermetic Vertical B factor plan-confirm cascade notch."""

from __future__ import annotations

import concurrent.futures
from contextlib import suppress
from functools import partial
from pathlib import Path

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import (
    PlatformAgentWorkspace as _PlatformAgentWorkspace,
)
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    ConfirmFactorVerticalBPlan,
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
    reset_default_result_surface_authority,
)
from quant_system.hermes.submission_saga import (
    SubmissionSagaError,
)
from quant_system.hermes.submission_saga import (
    submit_action as _submit_action,
)
from quant_system.hermes.vertical_binding_authority import (
    canonical_factor_b_plan_digest,
    default_vertical_binding_authority,
    reset_default_vertical_binding_authority,
)
from quant_system.hermes.vertical_observe import (
    default_vertical_observe_journal,
    project_workspace_attempts,
    project_workspace_tasks,
    reset_default_vertical_observe_journal,
)

submit_action = partial(_submit_action, allow_hermetic_authorities=True)
PlatformAgentWorkspace = partial(
    _PlatformAgentWorkspace,
    hermetic_authorities=True,
)

WS = "ws-v7g-vertical-b-m2"
PAPER_DIGEST = "a" * 64
CONFIRM_LIMITATIONS = {
    "hermetic_fixture",
    "not_live_backtest",
    "not_tradeable",
    "zero_orders",
    "plan_confirmed",
    "gate_cascade_locked",
    "not_git_commit",
}


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
    client_action_id: str = "act-v7gb-m2-bind",
    include_provider_evidence: bool = True,
    factor_name: str = "momentum_20d_reversal",
    goal_note: str = "复现论文动量反转因子（hermetic）",
) -> dict:
    return {
        "schema_version": 1,
        "kind": "vertical.factor_b.bind",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "goal_note": goal_note,
        "paper_ref": "fixture:paper/momentum_reversal_v1.pdf",
        "paper_digest": PAPER_DIGEST,
        "factor_name": factor_name,
        "formula_sketch": "ret_20d = close/close.shift(20)-1; signal = -ret_20d",
        "universe_note": "CSI300 hermetic fixture",
        "include_provider_evidence": include_provider_evidence,
    }


def _options_doc(*, client_action_id: str = "act-v7ga-iso-m2") -> dict:
    return {
        "schema_version": 1,
        "kind": "vertical.options_a.bind",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "ticker": "AAPL",
        "goal_note": "研究 AAPL 卖 Put",
        "expiry": "2026-08-15",
        "strike": 180.0,
        "bid": 2.35,
        "ask": 2.45,
        "delta": -0.25,
        "iv": 0.28,
        "apr": 0.12,
        "include_provider_evidence": True,
        "provider_mode": "hermetic_fixture",
        "auth_envelope": None,
    }


def _bind_completed(
    *,
    client_action_id: str = "act-v7gb-m2-bind",
    include_provider_evidence: bool = True,
):
    receipt = submit_action(
        _settings(),
        _bind_doc(
            client_action_id=client_action_id,
            include_provider_evidence=include_provider_evidence,
        ),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    return receipt


def _plan_digest_for_task(task_id: str) -> str:
    binder = default_vertical_binding_authority()
    task = binder.get_task(WS, task_id)
    assert task is not None
    return canonical_factor_b_plan_digest(task)


def _confirm_doc(
    *,
    task_id: str,
    bind_digest: str,
    plan_digest: str | None = None,
    client_action_id: str = "act-v7gb-m2-confirm",
    plan_version: int = 1,
    confirmation_note: str = "确认 hermetic 因子研究计划 v1",
) -> dict:
    pd = plan_digest if plan_digest is not None else _plan_digest_for_task(task_id)
    return {
        "schema_version": 1,
        "kind": "vertical.factor_b.plan_confirm",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{task_id}",
        "expected_bind_digest": bind_digest,
        "plan_version": plan_version,
        "plan_digest": pd,
        "confirmation_note": confirmation_note,
    }


# TC-B-M2-01
def test_parse_and_digest_confirm_stable() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is ConfirmFactorVerticalBPlan
    assert parsed.plan_version == 1
    assert action_to_document(parsed) == doc
    d1 = canonical_action_digest(parsed)
    d2 = canonical_action_digest(parse_user_action_v1(doc))
    assert d1 == d2
    assert len(d1) == 64


# TC-B-M2-02
def test_confirm_happy_path_new_artifacts() -> None:
    bind = _bind_completed()
    bind_attempt = bind.attempt_id
    bind_run = bind.run_id
    bind_result = bind.result_id
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.task_id == bind.task_id
    assert receipt.attempt_id != bind_attempt
    assert receipt.run_id != bind_run
    assert receipt.result_id != bind_result
    assert receipt.terminal_status == "completed"

    tasks = project_workspace_tasks(WS)
    assert len(tasks) == 1
    t = tasks[0]
    assert t["task_id"] == bind.task_id
    assert t["cascade_stage"] == "plan_confirmed"
    assert t["plan_version"] == 1
    assert t["plan_digest"] == doc["plan_digest"]
    assert t["attempt_id"] == receipt.attempt_id
    assert t["run_id"] == receipt.run_id
    assert t["result_id"] == receipt.result_id


# TC-B-M2-03
def test_confirm_limitations_honesty() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    rows = project_workspace_results(WS)
    confirm_row = next(r for r in rows if r["result_id"] == receipt.result_id)
    lim = set(confirm_row.get("limitations") or [])
    assert CONFIRM_LIMITATIONS.issubset(lim)
    assert "plan_confirm_required" not in lim
    assert confirm_row["sample_or_real"] == "sample"
    assert confirm_row["kind"] == "factor"
    assert confirm_row["payload_digest"] == doc["plan_digest"]
    assert confirm_row.get("source") == "hermetic_vertical_b_plan_confirm"


# TC-B-M2-04
def test_confirm_exact_links() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    row = next(r for r in project_workspace_results(WS) if r["result_id"] == receipt.result_id)
    assert row["task_id"] == bind.task_id
    assert row["attempt_id"] == receipt.attempt_id
    assert row["run_id"] == receipt.run_id
    assert row["attempt_id"] != bind.attempt_id


# TC-B-M2-05
def test_confirm_snapshot_projection() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS)).to_public_dict()
    assert bind.task_id in snap["tasks"]
    assert receipt.attempt_id in snap["attempts"]
    assert receipt.run_id in snap["runs"]
    # bind attempt/run still listed
    assert bind.attempt_id in snap["attempts"]
    assert bind.run_id in snap["runs"]
    assert any(r.get("result_id") == receipt.result_id for r in snap["results"])
    assert any(r.get("result_id") == bind.result_id for r in snap["results"])
    health = snap["authority_health"]
    assert health["task"] == "hermetic"
    assert health["attempt"] == "hermetic"
    assert health["run"] == "hermetic"
    assert health["result"] == "hermetic"
    assert snap["approvals"] == []
    assert snap["gates"] == []


# TC-B-M2-06
def test_confirm_idempotent_replay() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    r2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    assert r2.status == "accepted"
    assert r1.task_id == r2.task_id == bind.task_id
    assert r1.attempt_id == r2.attempt_id
    assert r1.result_id == r2.result_id
    # one task; two results (bind + confirm); one confirm attempt
    assert len(project_workspace_tasks(WS)) == 1
    results = project_workspace_results(WS)
    assert len(results) == 2
    attempts = project_workspace_attempts(WS)
    confirm_attempts = [a for a in attempts if a["attempt_id"] == r1.attempt_id]
    assert len(confirm_attempts) == 1


# TC-B-M2-07
def test_confirm_digest_conflict() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    bad = dict(doc)
    bad["confirmation_note"] = "不同的确认备注造成 digest 冲突"
    r2 = submit_action(_settings(), bad, mutation_enabled=True)
    assert r2.status == "conflict"
    tasks = project_workspace_tasks(WS)
    assert tasks[0]["cascade_stage"] == "plan_confirmed"
    assert len([r for r in project_workspace_results(WS) if r["result_id"] == r1.result_id]) == 1


# TC-B-M2-08
def test_confirm_mutation_off() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    # reset after bind so mutation-off path starts clean of confirm rows only —
    # keep bind state; just refuse confirm writes.
    before_results = len(project_workspace_results(WS))
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    assert len(project_workspace_results(WS)) == before_results
    tasks = project_workspace_tasks(WS)
    assert tasks[0]["cascade_stage"] == "bind_complete"


# TC-B-M2-09
def test_confirm_missing_task() -> None:
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.plan_confirm",
        "client_action_id": "act-missing-task",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:task-does-not-exist-zzzz",
        "expected_bind_digest": "b" * 64,
        "plan_version": 1,
        "plan_digest": "c" * 64,
        "confirmation_note": "missing task should fail",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_not_found"
    assert project_workspace_results(WS) == []


# TC-B-M2-10
def test_confirm_wrong_bind_digest() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest="f" * 64,
    )
    # plan_digest still computed from real task
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_bind_digest_mismatch"
    assert project_workspace_tasks(WS)[0]["cascade_stage"] == "bind_complete"


# TC-B-M2-11
def test_confirm_wrong_plan_digest() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        plan_digest="e" * 64,
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_plan_digest_mismatch"
    assert project_workspace_tasks(WS)[0]["cascade_stage"] == "bind_complete"


# TC-B-M2-12
def test_confirm_plan_version_two_rejected() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        plan_version=2,
    )
    with pytest.raises(AgentWorkspaceActionError):
        parse_user_action_v1(doc)
    # submit path re-validates via parse and surfaces as validation saga error
    with pytest.raises(SubmissionSagaError):
        submit_action(_settings(), doc, mutation_enabled=True)
    assert project_workspace_tasks(WS)[0]["cascade_stage"] == "bind_complete"


# TC-B-M2-13
def test_confirm_degraded_bind_blocked() -> None:
    bind = _bind_completed(
        client_action_id="act-v7gb-m2-degraded",
        include_provider_evidence=False,
    )
    assert bind.terminal_status == "completed_degraded"
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-confirm-degraded",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_bind_not_confirmable"
    task = project_workspace_tasks(WS)[0]
    assert task["cascade_stage"] == "bind_degraded"


# TC-B-M2-14
def test_confirm_options_a_task_wrong_vertical() -> None:
    opt = submit_action(_settings(), _options_doc(), mutation_enabled=True)
    assert opt.status == "accepted"
    # craft confirm against options task — plan digest will not match factor shape
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.plan_confirm",
        "client_action_id": "act-wrong-vertical",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{opt.task_id}",
        "expected_bind_digest": opt.action_digest,
        "plan_version": 1,
        "plan_digest": "d" * 64,
        "confirmation_note": "must fail wrong vertical",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_wrong_vertical"


# TC-B-M2-15
def test_double_confirm_different_action_conflict() -> None:
    bind = _bind_completed()
    doc1 = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-confirm-1",
    )
    r1 = submit_action(_settings(), doc1, mutation_enabled=True)
    assert r1.status == "accepted"
    doc2 = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-confirm-2",
        confirmation_note="第二次确认应被拒绝",
    )
    r2 = submit_action(_settings(), doc2, mutation_enabled=True)
    assert r2.status == "conflict"
    assert r2.reason_code == "cascade_already_plan_confirmed"
    assert project_workspace_tasks(WS)[0]["cascade_stage"] == "plan_confirmed"
    # still only one confirm result beyond bind
    confirm_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_plan_confirm"
    ]
    assert len(confirm_results) == 1


# TC-B-M2-16
def test_start_research_still_dark() -> None:
    doc = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "act-research-dark-m2",
        "workspace": {"workspace_id": WS},
        "managed_session_ref": "session:s-research-dark-m2",
        "payload_ref": "payload:sha256:" + ("a" * 64),
        "payload_digest": "a" * 64,
        "initial_mode": "plan_only",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"


# TC-B-M2-17
def test_global_confirm_research_plan_still_dark() -> None:
    bind = _bind_completed()
    doc = {
        "schema_version": 1,
        "kind": "research.plan.confirm",
        "client_action_id": "act-global-confirm-dark",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "plan_version": 1,
        "plan_digest": _plan_digest_for_task(bind.task_id),
        "confirmation_note": "global confirm must stay dark",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"
    assert project_workspace_tasks(WS)[0]["cascade_stage"] == "bind_complete"


# TC-B-M2-18
def test_gate1_not_auto_seeded() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    submit_action(_settings(), doc, mutation_enabled=True)
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS)).to_public_dict()
    assert snap["gates"] == []


# TC-B-M2-19
def test_follow_sse_vertical_ids_include_new() -> None:
    bind = _bind_completed()
    journal = default_vertical_observe_journal()
    # establish baseline fingerprint after bind
    journal.take_vertical_ids_if_changed(WS, [bind.task_id], [bind.attempt_id], [bind.run_id])
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    changed = journal.take_vertical_ids_if_changed(
        WS,
        [bind.task_id],
        sorted([bind.attempt_id, receipt.attempt_id]),
        sorted([bind.run_id, receipt.run_id]),
    )
    assert changed is not None
    assert bind.task_id in changed["tasks"]
    assert receipt.attempt_id in changed["attempts"]
    assert receipt.run_id in changed["runs"]
    # second identical call is stable
    again = journal.take_vertical_ids_if_changed(
        WS,
        [bind.task_id],
        sorted([bind.attempt_id, receipt.attempt_id]),
        sorted([bind.run_id, receipt.run_id]),
    )
    assert again is None

    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    page = ws.follow(ROOT_USER_ID, WorkspaceRef(workspace_id=WS), after=0).to_public_dict()
    assert bind.task_id in (page.get("tasks") or [])
    assert receipt.attempt_id in (page.get("attempts") or [])
    assert receipt.run_id in (page.get("runs") or [])


# TC-B-M2-20
def test_concurrent_confirm_storm() -> None:
    bind = _bind_completed(client_action_id="act-storm-bind")
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-storm-confirm",
    )
    settings = _settings()

    def _once():
        return submit_action(settings, doc, mutation_enabled=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_once) for _ in range(16)]
        receipts = [f.result() for f in futs]
    assert all(r.status == "accepted" for r in receipts)
    assert len({r.attempt_id for r in receipts}) == 1
    assert len({r.result_id for r in receipts}) == 1
    confirm_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_plan_confirm"
    ]
    assert len(confirm_results) == 1


# TC-B-M2-21
def test_reject_smuggled_keys() -> None:
    bind = _bind_completed()
    doc = _confirm_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    bad = dict(doc)
    bad["auth_envelope"] = {"grant_id": "x"}
    with pytest.raises(AgentWorkspaceActionError):
        parse_user_action_v1(bad)
    bad2 = dict(doc)
    bad2["provider_mode"] = "live_futu_ro"
    with pytest.raises(AgentWorkspaceActionError):
        parse_user_action_v1(bad2)


# TC-B-M2-22
def test_zero_orders_invariant_on_confirm_source() -> None:
    src = (
        Path(__file__).resolve().parents[1]
        / "src/quant_system/hermes/vertical_binding_authority.py"
    )
    body = src.read_text(encoding="utf-8")
    # Locate confirm method body roughly
    start = body.index("def confirm_factor_vertical_b_plan")
    # Bound confirm body before the M3 seed method (or release helper fallback).
    try:
        end = body.index("def seed_factor_vertical_b_gate1", start)
    except ValueError:
        end = body.index("def _release_reservation", start)
    chunk = body[start:end]
    for banned in (
        "place_order",
        "submit_order",
        "unlock_trade",
        "import hqa",
        "seed_gate1",
    ):
        assert banned not in chunk
    bind = _bind_completed(client_action_id="act-zero-orders-bind")
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-zero-orders-confirm",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    row = next(r for r in project_workspace_results(WS) if r["result_id"] == receipt.result_id)
    assert "zero_orders" in (row.get("limitations") or [])


# TC-B-M2-23
def test_conversation_turn_invents_zero_factor_tasks() -> None:
    before = project_workspace_tasks(WS)
    doc = {
        "schema_version": 1,
        "kind": "conversation.turn",
        "client_action_id": "act-turn-no-factor-m2",
        "workspace": {"workspace_id": WS},
        "session_ref": "session:s-hermetic-m2",
        "prompt": "hello without vertical confirm",
    }
    # conversation.turn uses managed_session_ref + payload fields in this codebase
    doc = {
        "schema_version": 1,
        "kind": "conversation.turn",
        "client_action_id": "act-turn-no-factor-m2",
        "workspace": {"workspace_id": WS},
        "managed_session_ref": "session:s-hermetic-m2",
        "payload_ref": "payload:sha256:" + ("c" * 64),
        "payload_digest": "c" * 64,
    }
    with suppress(Exception):
        submit_action(_settings(), doc, mutation_enabled=True)
    assert project_workspace_tasks(WS) == before


# TC-B-M2-24
def test_a_isolation_with_factor_confirm() -> None:
    opt = submit_action(
        _settings(),
        _options_doc(client_action_id="act-iso-opt"),
        mutation_enabled=True,
    )
    assert opt.status == "accepted"
    bind = _bind_completed(client_action_id="act-iso-bind")
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-iso-confirm",
    )
    conf = submit_action(_settings(), doc, mutation_enabled=True)
    assert conf.status == "accepted"
    tasks = {t["task_id"]: t for t in project_workspace_tasks(WS)}
    assert tasks[opt.task_id]["vertical"] == "options_a"
    assert "cascade_stage" not in tasks[opt.task_id] or tasks[opt.task_id].get("cascade_stage") in (
        None,
        "options_a",
    )
    # options task should not gain plan_confirmed
    assert tasks[opt.task_id].get("cascade_stage") != "plan_confirmed"
    assert tasks[bind.task_id]["vertical"] == "factor_b"
    assert tasks[bind.task_id]["cascade_stage"] == "plan_confirmed"


# TC-B-M2-25
def test_bind_result_preserved_after_confirm() -> None:
    bind = _bind_completed(client_action_id="act-preserve-bind")
    bind_result_id = bind.result_id
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-preserve-confirm",
    )
    conf = submit_action(_settings(), doc, mutation_enabled=True)
    assert conf.status == "accepted"
    results = {r["result_id"]: r for r in project_workspace_results(WS)}
    assert bind_result_id in results
    assert conf.result_id in results
    assert results[bind_result_id].get("source") == "hermetic_vertical_b_binding"
    assert results[conf.result_id].get("source") == "hermetic_vertical_b_plan_confirm"
    task = project_workspace_tasks(WS)[0]
    assert task["result_id"] == conf.result_id
    assert task.get("bind_result_id") == bind_result_id


# TC-B-M2-26
def test_empty_confirmation_note_rejected() -> None:
    bind = _bind_completed(client_action_id="act-empty-note-bind")
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-empty-note",
        confirmation_note="   ",
    )
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError)):
        parse_user_action_v1(doc)


# TC-B-M2-27
def test_canonical_plan_digest_helper_golden() -> None:
    bind = _bind_completed(client_action_id="act-golden-bind")
    task = default_vertical_binding_authority().get_task(WS, bind.task_id)
    assert task is not None
    d1 = canonical_factor_b_plan_digest(task)
    d2 = canonical_factor_b_plan_digest(task)
    assert d1 == d2
    assert len(d1) == 64
    # Mutating goal_note identity changes the digest. Re-bind with different
    # goals after resetting the singleton authorities.
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    r_a = submit_action(
        _settings(),
        _bind_doc(client_action_id="act-gold-a", goal_note="目标A"),
        mutation_enabled=True,
    )
    r_b = submit_action(
        _settings(),
        _bind_doc(client_action_id="act-gold-b", goal_note="目标B"),
        mutation_enabled=True,
    )
    ta = default_vertical_binding_authority().get_task(WS, r_a.task_id)
    tb = default_vertical_binding_authority().get_task(WS, r_b.task_id)
    assert canonical_factor_b_plan_digest(ta) != canonical_factor_b_plan_digest(tb)
