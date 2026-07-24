"""V7g-B-M3: hermetic Vertical B factor Gate1 seed cascade notch."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    BindFactorVerticalB,
    BindOptionsVerticalA,
    ConfirmFactorVerticalBPlan,
    SeedFactorVerticalBGate1,
    WorkspaceRef,
    action_to_document,
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.gate_observe import (
    project_workspace_gates,
    reset_default_gate_observe_journal,
)
from quant_system.hermes.gate_surface_authority import (
    default_gate_surface_authority,
    reset_default_gate_surface_authority,
)
from quant_system.hermes.result_observe import (
    project_workspace_results,
    reset_default_result_observe_journal,
)
from quant_system.hermes.result_surface_authority import (
    default_result_surface_authority,
    reset_default_result_surface_authority,
)
from quant_system.hermes.submission_saga import SubmissionSagaError, submit_action
from quant_system.hermes.vertical_binding_authority import (
    canonical_factor_b_formula_source_digest,
    canonical_factor_b_plan_digest,
    default_vertical_binding_authority,
    reset_default_vertical_binding_authority,
)
from quant_system.hermes.vertical_observe import (
    default_vertical_observe_journal,
    project_workspace_attempts,
    project_workspace_runs,
    project_workspace_tasks,
    reset_default_vertical_observe_journal,
)

WS = "ws-v7g-vertical-b-m3"
PAPER_DIGEST = "a" * 64
SEED_LIMITATIONS = {
    "hermetic_fixture",
    "not_live_backtest",
    "not_tradeable",
    "zero_orders",
    "plan_confirmed",
    "gate1_seeded",
    "gate_cascade_locked",
    "not_git_commit",
}


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    reset_default_gate_surface_authority()
    reset_default_gate_observe_journal()
    yield
    reset_default_vertical_binding_authority()
    reset_default_result_surface_authority()
    reset_default_result_observe_journal()
    reset_default_vertical_observe_journal()
    reset_default_gate_surface_authority()
    reset_default_gate_observe_journal()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _bind_doc(
    *,
    client_action_id: str = "act-v7gb-m3-bind",
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


def _options_doc(*, client_action_id: str = "act-v7ga-iso-m3") -> dict:
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
    client_action_id: str = "act-v7gb-m3-bind",
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
    client_action_id: str = "act-v7gb-m3-confirm",
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


def _plan_confirmed(
    *,
    bind_id: str = "act-v7gb-m3-bind",
    confirm_id: str = "act-v7gb-m3-confirm",
):
    bind = _bind_completed(client_action_id=bind_id)
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id=confirm_id,
    )
    confirm = submit_action(_settings(), doc, mutation_enabled=True)
    assert confirm.status == "accepted"
    return bind, confirm


def _formula_sketch_for_task(task_id: str) -> str:
    binder = default_vertical_binding_authority()
    task = binder.get_task(WS, task_id)
    assert task is not None
    rauth = default_result_surface_authority()
    bind_rid = task.bind_result_id
    assert bind_rid
    row = rauth.get(WS, bind_rid)
    assert row is not None
    assert row.formula_sketch
    return row.formula_sketch


def _formula_source_digest_for_task(task_id: str) -> str:
    binder = default_vertical_binding_authority()
    task = binder.get_task(WS, task_id)
    assert task is not None
    sketch = _formula_sketch_for_task(task_id)
    return canonical_factor_b_formula_source_digest(task, formula_sketch=sketch)


def _seed_doc(
    *,
    task_id: str,
    bind_digest: str,
    plan_digest: str | None = None,
    reviewed_source_sha256: str | None = None,
    client_action_id: str = "act-v7gb-m3-seed",
    seed_note: str = "seed Gate1 formula source for hermetic factor_b",
) -> dict:
    pd = plan_digest if plan_digest is not None else _plan_digest_for_task(task_id)
    src = (
        reviewed_source_sha256
        if reviewed_source_sha256 is not None
        else _formula_source_digest_for_task(task_id)
    )
    return {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate1_seed",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{task_id}",
        "expected_bind_digest": bind_digest,
        "expected_plan_digest": pd,
        "reviewed_source_sha256": src,
        "seed_note": seed_note,
    }


# TC-B-M3-01
def test_parse_and_digest_seed_stable() -> None:
    bind, _confirm = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is SeedFactorVerticalBGate1
    assert action_to_document(parsed) == doc
    d1 = canonical_action_digest(parsed)
    d2 = canonical_action_digest(parse_user_action_v1(doc))
    assert d1 == d2
    assert len(d1) == 64


# TC-B-M3-02
def test_seed_happy_path_new_artifacts() -> None:
    bind, confirm = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.task_id == bind.task_id
    assert receipt.attempt_id != confirm.attempt_id
    assert receipt.run_id != confirm.run_id
    assert receipt.result_id != confirm.result_id
    assert receipt.terminal_status == "completed"
    assert receipt.gate_id
    assert receipt.gate_id.startswith("gate-")

    tasks = project_workspace_tasks(WS)
    assert len(tasks) == 1
    t = tasks[0]
    assert t["task_id"] == bind.task_id
    assert t["cascade_stage"] == "gate1_seeded"
    assert t["gate1_id"] == receipt.gate_id
    assert t["attempt_id"] == receipt.attempt_id
    assert t["run_id"] == receipt.run_id
    assert t["result_id"] == receipt.result_id
    assert t["plan_digest"] == doc["expected_plan_digest"]
    assert t.get("plan_attempt_id") == confirm.attempt_id
    assert t.get("plan_run_id") == confirm.run_id
    assert t.get("plan_result_id") == confirm.result_id
    assert t.get("bind_result_id") == bind.result_id


# TC-B-M3-03
def test_seed_snapshot_gates_pending() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"

    gates = project_workspace_gates(WS)
    assert len(gates) >= 1
    g = next(x for x in gates if x.get("gate_id") == receipt.gate_id)
    assert g["status"] == "pending"
    assert g.get("gate_kind") == "gate1" or g.get("kind") in {
        "gate1",
        "gate1.formula_source",
    }
    assert g.get("task_id") == bind.task_id or g.get("task_ref") == f"task:{bind.task_id}"
    assert g["reviewed_source_sha256"] == doc["reviewed_source_sha256"]

    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS)).to_public_dict()
    assert any(x.get("gate_id") == receipt.gate_id for x in snap.get("gates") or [])
    assert snap.get("approvals") == []
    # gates must not leak into approvals
    assert not any(
        (a.get("gate_id") == receipt.gate_id) for a in (snap.get("approvals") or [])
    )


# TC-B-M3-04
def test_seed_limitations_honesty() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    rows = project_workspace_results(WS)
    seed_row = next(r for r in rows if r["result_id"] == receipt.result_id)
    lim = set(seed_row.get("limitations") or [])
    assert SEED_LIMITATIONS.issubset(lim)
    assert "plan_confirm_required" not in lim
    assert seed_row["sample_or_real"] == "sample"
    assert seed_row["kind"] == "factor"
    assert seed_row["payload_digest"] == doc["reviewed_source_sha256"]
    assert seed_row.get("source") == "hermetic_vertical_b_gate1_seed"


# TC-B-M3-05
def test_seed_exact_links() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    rows = project_workspace_results(WS)
    seed_row = next(r for r in rows if r["result_id"] == receipt.result_id)
    assert seed_row["task_id"] == bind.task_id
    assert seed_row["attempt_id"] == receipt.attempt_id
    assert seed_row["run_id"] == receipt.run_id
    t = project_workspace_tasks(WS)[0]
    assert t["gate1_id"] == receipt.gate_id
    gates = project_workspace_gates(WS)
    assert any(g.get("gate_id") == t["gate1_id"] for g in gates)


# TC-B-M3-06
def test_seed_idempotent_replay() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    r2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    assert r2.status == "accepted"
    assert r1.task_id == r2.task_id
    assert r1.result_id == r2.result_id
    assert r1.gate_id == r2.gate_id
    gates = [
        g
        for g in project_workspace_gates(WS)
        if g.get("status") == "pending" and g.get("gate_id") == r1.gate_id
    ]
    assert len(gates) == 1
    seed_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_gate1_seed"
    ]
    assert len(seed_results) == 1


# TC-B-M3-07
def test_seed_digest_conflict() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    bad = dict(doc)
    bad["seed_note"] = "不同的 seed note 造成 digest 冲突"
    r2 = submit_action(_settings(), bad, mutation_enabled=True)
    assert r2.status == "conflict"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_seeded"
    assert t["gate1_id"] == r1.gate_id


# TC-B-M3-08
def test_seed_mutation_off() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "plan_confirmed"
    assert project_workspace_gates(WS) == []


# TC-B-M3-09
def test_seed_missing_task() -> None:
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate1_seed",
        "client_action_id": "act-v7gb-m3-missing",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:task-does-not-exist",
        "expected_bind_digest": "b" * 64,
        "expected_plan_digest": "c" * 64,
        "reviewed_source_sha256": "d" * 64,
        "seed_note": "missing task seed",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_not_found"


# TC-B-M3-10
def test_seed_wrong_bind_digest() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest="f" * 64,
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_bind_digest_mismatch"
    assert project_workspace_gates(WS) == []


# TC-B-M3-11
def test_seed_wrong_plan_digest() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        plan_digest="e" * 64,
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_plan_digest_mismatch"
    assert project_workspace_gates(WS) == []


# TC-B-M3-12
def test_seed_wrong_formula_source_digest() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        reviewed_source_sha256="1" * 64,
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_formula_source_digest_mismatch"
    assert project_workspace_gates(WS) == []


# TC-B-M3-13
def test_seed_bind_complete_without_plan_confirm_blocked() -> None:
    bind = _bind_completed(client_action_id="act-v7gb-m3-bind-only")
    # Fabricate seed doc with dummy plan/source digests — stage is not plan_confirmed.
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate1_seed",
        "client_action_id": "act-v7gb-m3-seed-early",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "expected_bind_digest": bind.action_digest,
        "expected_plan_digest": "a" * 64,
        "reviewed_source_sha256": "b" * 64,
        "seed_note": "too early seed",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate1_not_seedable"


# TC-B-M3-14
def test_seed_degraded_bind_blocked() -> None:
    bind = _bind_completed(
        client_action_id="act-v7gb-m3-degraded",
        include_provider_evidence=False,
    )
    assert bind.terminal_status == "completed_degraded"
    # plan_confirm itself should refuse degraded
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-confirm-degraded",
        plan_digest="c" * 64,
    )
    confirm = submit_action(_settings(), doc, mutation_enabled=True)
    assert confirm.status == "unavailable"
    # And seed against bind_degraded is also blocked
    seed = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate1_seed",
        "client_action_id": "act-v7gb-m3-seed-degraded",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "expected_bind_digest": bind.action_digest,
        "expected_plan_digest": "c" * 64,
        "reviewed_source_sha256": "d" * 64,
        "seed_note": "degraded seed",
    }
    receipt = submit_action(_settings(), seed, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate1_not_seedable"


# TC-B-M3-15
def test_seed_options_a_task_wrong_vertical() -> None:
    opt = submit_action(_settings(), _options_doc(), mutation_enabled=True)
    assert opt.status == "accepted"
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate1_seed",
        "client_action_id": "act-v7gb-m3-seed-opt",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{opt.task_id}",
        "expected_bind_digest": opt.action_digest,
        "expected_plan_digest": "a" * 64,
        "reviewed_source_sha256": "b" * 64,
        "seed_note": "options wrong vertical",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_wrong_vertical"


# TC-B-M3-16
def test_double_seed_different_action_conflict() -> None:
    bind, _ = _plan_confirmed()
    doc1 = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-a",
    )
    r1 = submit_action(_settings(), doc1, mutation_enabled=True)
    assert r1.status == "accepted"
    doc2 = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-b",
    )
    r2 = submit_action(_settings(), doc2, mutation_enabled=True)
    assert r2.status == "conflict"
    assert r2.reason_code == "cascade_already_gate1_seeded"
    pending = [
        g
        for g in project_workspace_gates(WS)
        if g.get("status") == "pending"
    ]
    assert len(pending) == 1
    assert pending[0]["gate_id"] == r1.gate_id


# TC-B-M3-17
def test_start_research_still_dark_after_seed() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    assert submit_action(_settings(), doc, mutation_enabled=True).status == "accepted"
    research = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "act-research-dark-m3",
        "workspace": {"workspace_id": WS},
        "managed_session_ref": "session:s-research-dark-m3",
        "payload_ref": "payload:sha256:" + ("a" * 64),
        "payload_digest": "a" * 64,
        "initial_mode": "plan_only",
    }
    receipt = submit_action(_settings(), research, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"


# TC-B-M3-18
def test_global_confirm_research_plan_still_dark() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    assert submit_action(_settings(), doc, mutation_enabled=True).status == "accepted"
    global_confirm = {
        "schema_version": 1,
        "kind": "research.plan.confirm",
        "client_action_id": "act-global-confirm-m3",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "plan_version": 1,
        "plan_digest": _plan_digest_for_task(bind.task_id),
        "confirmation_note": "global confirm still dark",
    }
    receipt = submit_action(_settings(), global_confirm, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"


# TC-B-M3-19
def test_plan_confirm_still_does_not_auto_seed() -> None:
    bind, confirm = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-noauto",
        confirm_id="act-v7gb-m3-confirm-noauto",
    )
    assert confirm.status == "accepted"
    assert project_workspace_gates(WS) == []
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "plan_confirmed"
    # Static scan: confirm body must not call seed_gate1
    src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/"
        "vertical_binding_authority.py"
    ).read_text()
    # Extract confirm method body roughly
    start = src.index("def confirm_factor_vertical_b_plan")
    end = src.index("def seed_factor_vertical_b_gate1", start)
    body = src[start:end]
    assert "seed_gate1" not in body
    assert "seed_gate1_pending" not in body


# TC-B-M3-20
def test_v7e_confirm_after_seed_keeps_cascade_locked() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    seed = submit_action(_settings(), doc, mutation_enabled=True)
    assert seed.status == "accepted"
    confirm_gate = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-v7e-confirm-after-m3",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "reviewed_source_sha256": doc["reviewed_source_sha256"],
        "confirmation_note": "V7e decide after M3 seed",
    }
    decided = submit_action(_settings(), confirm_gate, mutation_enabled=True)
    assert decided.status == "accepted"
    gates = project_workspace_gates(WS)
    g = next(x for x in gates if x.get("gate_id") == seed.gate_id)
    assert g["status"] == "confirmed"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_seeded"
    rows = project_workspace_results(WS)
    seed_row = next(r for r in rows if r["result_id"] == seed.result_id)
    lim = set(seed_row.get("limitations") or [])
    assert "gate_cascade_locked" in lim


# TC-B-M3-21
def test_v7e_confirm_without_seed_still_fails() -> None:
    bind, _ = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-noseed",
        confirm_id="act-v7gb-m3-confirm-noseed",
    )
    src = _formula_source_digest_for_task(bind.task_id)
    confirm_gate = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-v7e-confirm-noseed",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "reviewed_source_sha256": src,
        "confirmation_note": "no pending gate",
    }
    decided = submit_action(_settings(), confirm_gate, mutation_enabled=True)
    assert decided.status in {"conflict", "unavailable"}


# TC-B-M3-22
def test_follow_sse_vertical_ids_include_seed() -> None:
    bind, _ = _plan_confirmed()
    doc = _seed_doc(task_id=bind.task_id, bind_digest=bind.action_digest)
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    page = ws.follow(
        ROOT_USER_ID, WorkspaceRef(workspace_id=WS), after=0
    ).to_public_dict()
    assert receipt.task_id in (page.get("tasks") or [])
    assert receipt.attempt_id in (page.get("attempts") or [])
    assert receipt.run_id in (page.get("runs") or [])
    assert any(r.get("result_id") == receipt.result_id for r in page.get("results") or [])


# TC-B-M3-23
def test_gate_observe_journal_raised() -> None:
    bind, _ = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-jrnl",
        confirm_id="act-v7gb-m3-confirm-jrnl",
    )
    before = project_workspace_gates(WS)
    assert before == []
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-jrnl",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    after = project_workspace_gates(WS)
    assert any(g.get("gate_id") == receipt.gate_id for g in after)


# TC-B-M3-24
def test_concurrent_seed_storm() -> None:
    bind, _ = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-race",
        confirm_id="act-v7gb-m3-confirm-race",
    )
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-race",
    )
    settings = _settings()

    def _once():
        return submit_action(settings, doc, mutation_enabled=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_once) for _ in range(16)]
        receipts = [f.result() for f in futs]
    assert all(r.status == "accepted" for r in receipts)
    assert len({r.gate_id for r in receipts}) == 1
    assert len({r.result_id for r in receipts}) == 1
    pending = [g for g in project_workspace_gates(WS) if g.get("status") == "pending"]
    assert len(pending) == 1
    seed_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_gate1_seed"
    ]
    assert len(seed_results) == 1


# TC-B-M3-25
def test_reject_smuggled_keys() -> None:
    bind, _ = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-smug",
        confirm_id="act-v7gb-m3-confirm-smug",
    )
    base = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-smug",
    )
    for key, val in (
        ("auth_envelope", {"tickers": ["AAPL"]}),
        ("provider_mode", "live_futu_ro"),
        ("gate_id", "gate-smuggled"),
        ("plan_version", 1),
        ("confirmation_note", "nope"),
        ("extra_field", "x"),
    ):
        bad = dict(base)
        bad["client_action_id"] = f"act-smug-{key}"
        bad[key] = val
        with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, TypeError, ValueError)):
            try:
                parse_user_action_v1(bad)
            except AgentWorkspaceActionError:
                raise
            submit_action(_settings(), bad, mutation_enabled=True)


# TC-B-M3-26
def test_zero_orders_invariant_on_seed_source() -> None:
    src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/"
        "vertical_binding_authority.py"
    ).read_text()
    start = src.index("def seed_factor_vertical_b_gate1")
    # Bound end at M4 confirm so seed body scan stays seed-only.
    end = src.index("def confirm_factor_vertical_b_gate1", start)
    body = src[start:end]
    for banned in (
        "place_order",
        "submit_order",
        "unlock_trade",
        "import hqa",
        "import_hqa",
    ):
        assert banned not in body
    # Also ensure no decide call
    assert "confirm_formula_source" not in body


# TC-B-M3-27
def test_bind_and_plan_results_preserved() -> None:
    bind, confirm = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-pres",
        confirm_id="act-v7gb-m3-confirm-pres",
    )
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-pres",
    )
    seed = submit_action(_settings(), doc, mutation_enabled=True)
    assert seed.status == "accepted"
    rows = {r["result_id"]: r for r in project_workspace_results(WS)}
    assert bind.result_id in rows
    assert confirm.result_id in rows
    assert seed.result_id in rows
    assert rows[bind.result_id].get("source") == "hermetic_vertical_b_binding" or (
        "hermetic" in (rows[bind.result_id].get("source") or "")
    )
    assert rows[confirm.result_id].get("source") == "hermetic_vertical_b_plan_confirm"
    assert rows[seed.result_id].get("source") == "hermetic_vertical_b_gate1_seed"


# TC-B-M3-28
def test_empty_seed_note_rejected() -> None:
    bind, _ = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-empty",
        confirm_id="act-v7gb-m3-confirm-empty",
    )
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-empty",
        seed_note="   ",
    )
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError)):
        try:
            parse_user_action_v1(doc)
        except AgentWorkspaceActionError:
            raise
        submit_action(_settings(), doc, mutation_enabled=True)


# TC-B-M3-29
def test_a_isolation_with_factor_seed() -> None:
    opt = submit_action(
        _settings(),
        _options_doc(client_action_id="act-v7ga-iso-m3b"),
        mutation_enabled=True,
    )
    assert opt.status == "accepted"
    bind, _ = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-iso",
        confirm_id="act-v7gb-m3-confirm-iso",
    )
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m3-seed-iso",
    )
    seed = submit_action(_settings(), doc, mutation_enabled=True)
    assert seed.status == "accepted"
    tasks = {t["task_id"]: t for t in project_workspace_tasks(WS)}
    assert tasks[opt.task_id].get("cascade_stage") in (None, "")
    assert "gate1_id" not in tasks[opt.task_id] or tasks[opt.task_id].get("gate1_id") is None
    assert tasks[bind.task_id]["cascade_stage"] == "gate1_seeded"


# TC-B-M3-30
def test_canonical_formula_source_digest_golden() -> None:
    bind, _ = _plan_confirmed(
        bind_id="act-v7gb-m3-bind-golden",
        confirm_id="act-v7gb-m3-confirm-golden",
    )
    binder = default_vertical_binding_authority()
    task = binder.get_task(WS, bind.task_id)
    assert task is not None
    sketch = _formula_sketch_for_task(bind.task_id)
    d1 = canonical_factor_b_formula_source_digest(task, formula_sketch=sketch)
    d2 = canonical_factor_b_formula_source_digest(task, formula_sketch=sketch)
    assert d1 == d2
    assert len(d1) == 64
    # Sensitivity: formula_sketch change alters digest
    d3 = canonical_factor_b_formula_source_digest(
        task, formula_sketch=sketch + "; extra"
    )
    assert d3 != d1
    # Sensitivity: plan_digest change alters digest
    from dataclasses import replace

    mutated = replace(task, plan_digest="f" * 64)
    d4 = canonical_factor_b_formula_source_digest(mutated, formula_sketch=sketch)
    assert d4 != d1


# TC-B-M3-31
def test_conversation_turn_invents_zero_factor_tasks_or_gates() -> None:
    before_tasks = project_workspace_tasks(WS)
    before_gates = project_workspace_gates(WS)
    doc = {
        "schema_version": 1,
        "kind": "conversation.turn",
        "client_action_id": "act-turn-no-task-m3",
        "workspace": {"workspace_id": WS},
        "session_ref": "session:s-hermetic-m3",
        "prompt": "hello without vertical seed",
    }
    try:
        submit_action(_settings(), doc, mutation_enabled=True)
    except Exception:
        pass
    assert project_workspace_tasks(WS) == before_tasks
    assert project_workspace_gates(WS) == before_gates
