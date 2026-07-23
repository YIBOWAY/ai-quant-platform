"""V7g-B-M4: hermetic Vertical B factor Gate1 decide→cascade coupler."""

from __future__ import annotations

import concurrent.futures
from functools import partial
from pathlib import Path

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import (
    PlatformAgentWorkspace as _PlatformAgentWorkspace,
)
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    ConfirmFactorVerticalBGate1,
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
from quant_system.hermes.submission_saga import (
    SubmissionSagaError,
)
from quant_system.hermes.submission_saga import (
    submit_action as _submit_action,
)
from quant_system.hermes.vertical_binding_authority import (
    canonical_factor_b_formula_source_digest,
    canonical_factor_b_plan_digest,
    default_vertical_binding_authority,
    reset_default_vertical_binding_authority,
)
from quant_system.hermes.vertical_observe import (
    project_workspace_tasks,
    reset_default_vertical_observe_journal,
)

submit_action = partial(_submit_action, allow_hermetic_authorities=True)
PlatformAgentWorkspace = partial(
    _PlatformAgentWorkspace,
    hermetic_authorities=True,
)

WS = "ws-v7g-vertical-b-m4"
PAPER_DIGEST = "a" * 64
CONFIRM_LIMITATIONS = {
    "hermetic_fixture",
    "not_live_backtest",
    "not_tradeable",
    "zero_orders",
    "plan_confirmed",
    "gate1_seeded",
    "gate1_confirmed",
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
    client_action_id: str = "act-v7gb-m4-bind",
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


def _options_doc(*, client_action_id: str = "act-v7ga-iso-m4") -> dict:
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
    client_action_id: str = "act-v7gb-m4-bind",
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


def _confirm_plan_doc(
    *,
    task_id: str,
    bind_digest: str,
    plan_digest: str | None = None,
    client_action_id: str = "act-v7gb-m4-plan",
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
    bind_id: str = "act-v7gb-m4-bind",
    plan_id: str = "act-v7gb-m4-plan",
):
    bind = _bind_completed(client_action_id=bind_id)
    doc = _confirm_plan_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id=plan_id,
    )
    plan = submit_action(_settings(), doc, mutation_enabled=True)
    assert plan.status == "accepted"
    return bind, plan


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
    client_action_id: str = "act-v7gb-m4-seed",
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


def _gate1_seeded(
    *,
    bind_id: str = "act-v7gb-m4-bind",
    plan_id: str = "act-v7gb-m4-plan",
    seed_id: str = "act-v7gb-m4-seed",
):
    bind, plan = _plan_confirmed(bind_id=bind_id, plan_id=plan_id)
    doc = _seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id=seed_id,
    )
    seed = submit_action(_settings(), doc, mutation_enabled=True)
    assert seed.status == "accepted"
    return bind, plan, seed, doc


def _confirm_doc(
    *,
    task_id: str,
    bind_digest: str,
    expected_gate1_id: str,
    plan_digest: str | None = None,
    reviewed_source_sha256: str | None = None,
    client_action_id: str = "act-v7gb-m4-confirm",
    confirmation_note: str = "confirm Gate1 formula source for hermetic factor_b",
) -> dict:
    pd = plan_digest if plan_digest is not None else _plan_digest_for_task(task_id)
    src = (
        reviewed_source_sha256
        if reviewed_source_sha256 is not None
        else _formula_source_digest_for_task(task_id)
    )
    return {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate1_confirm",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{task_id}",
        "expected_bind_digest": bind_digest,
        "expected_plan_digest": pd,
        "expected_gate1_id": expected_gate1_id,
        "reviewed_source_sha256": src,
        "confirmation_note": confirmation_note,
    }


# TC-B-M4-01
def test_happy_confirm_plus_cascade() -> None:
    bind, _plan, seed, _seed_doc_body = _gate1_seeded()
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.gate_id == seed.gate_id
    assert receipt.terminal_status == "completed"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_confirmed"
    assert t["terminal_reason"] == "gate1_confirmed"
    assert t["gate1_id"] == seed.gate_id
    gates = project_workspace_gates(WS)
    g = next(x for x in gates if x.get("gate_id") == seed.gate_id)
    assert g["status"] == "confirmed"
    rows = project_workspace_results(WS)
    conf_row = next(r for r in rows if r["result_id"] == receipt.result_id)
    lim = set(conf_row.get("limitations") or [])
    assert "gate1_confirmed" in lim
    assert "gate_cascade_locked" in lim
    assert conf_row.get("sample_or_real") == "sample"
    assert conf_row.get("source") == "hermetic_vertical_b_gate1_confirm"


# TC-B-M4-02
def test_artifact_novelty_vs_seed() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-nov",
        plan_id="act-v7gb-m4-plan-nov",
        seed_id="act-v7gb-m4-seed-nov",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-nov",
    )
    conf = submit_action(_settings(), doc, mutation_enabled=True)
    assert conf.status == "accepted"
    assert conf.attempt_id != seed.attempt_id
    assert conf.run_id != seed.run_id
    assert conf.result_id != seed.result_id
    assert conf.gate_id == seed.gate_id
    assert conf.task_id == seed.task_id


# TC-B-M4-03
def test_seed_era_snapshot() -> None:
    bind, plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-snap",
        plan_id="act-v7gb-m4-plan-snap",
        seed_id="act-v7gb-m4-seed-snap",
    )
    pre = default_vertical_binding_authority().get_task(WS, bind.task_id)
    assert pre is not None
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-snap",
    )
    conf = submit_action(_settings(), doc, mutation_enabled=True)
    assert conf.status == "accepted"
    t = default_vertical_binding_authority().get_task(WS, bind.task_id)
    assert t is not None
    assert t.gate1_seed_attempt_id == seed.attempt_id
    assert t.gate1_seed_run_id == seed.run_id
    assert t.gate1_seed_result_id == seed.result_id
    assert t.bind_attempt_id == pre.bind_attempt_id
    assert t.bind_run_id == pre.bind_run_id
    assert t.bind_result_id == pre.bind_result_id
    assert t.plan_attempt_id == pre.plan_attempt_id
    assert t.plan_run_id == pre.plan_run_id
    assert t.plan_result_id == pre.plan_result_id
    assert t.plan_digest == plan.action_digest or t.plan_digest == pre.plan_digest
    assert t.gate1_confirm_action_id == "act-v7gb-m4-confirm-snap"
    assert t.gate1_confirmed_at is not None


# TC-B-M4-04
def test_limitations_honesty() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-lim",
        plan_id="act-v7gb-m4-plan-lim",
        seed_id="act-v7gb-m4-seed-lim",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-lim",
    )
    conf = submit_action(_settings(), doc, mutation_enabled=True)
    assert conf.status == "accepted"
    t = project_workspace_tasks(WS)[0]
    tlim = set(t.get("limitations") or [])
    assert CONFIRM_LIMITATIONS.issubset(tlim)
    for banned in (
        "gate_cascade_unlock",
        "gate2_seed",
        "start_research",
        "tradeable",
        "live_backtest",
        "plan_confirm_required",
    ):
        assert banned not in tlim
    row = next(r for r in project_workspace_results(WS) if r["result_id"] == conf.result_id)
    rlim = set(row.get("limitations") or [])
    assert CONFIRM_LIMITATIONS.issubset(rlim)
    assert row.get("sample_or_real") == "sample"


# TC-B-M4-05
def test_cascade_only_after_v7e() -> None:
    bind, _plan, seed, seed_doc = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-v7e",
        plan_id="act-v7gb-m4-plan-v7e",
        seed_id="act-v7gb-m4-seed-v7e",
    )
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-v7e-confirm-m4-first",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "reviewed_source_sha256": seed_doc["reviewed_source_sha256"],
        "confirmation_note": "V7e decide before M4",
    }
    v7e = submit_action(_settings(), v7e_doc, mutation_enabled=True)
    assert v7e.status == "accepted"
    gauth = default_gate_surface_authority()
    pre = gauth.get(WS, seed.gate_id)
    assert pre is not None and pre.status == "confirmed"
    assert pre.decision_action_id == "act-v7e-confirm-m4-first"
    v7e_decision_digest = pre.decision_action_digest

    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-after-v7e",
        reviewed_source_sha256=seed_doc["reviewed_source_sha256"],
    )
    conf = submit_action(_settings(), doc, mutation_enabled=True)
    assert conf.status == "accepted"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_confirmed"
    post = gauth.get(WS, seed.gate_id)
    assert post is not None
    assert post.status == "confirmed"
    assert post.decision_action_id == "act-v7e-confirm-m4-first"
    assert post.decision_action_digest == v7e_decision_digest


# TC-B-M4-06
def test_v7e_alone_still_stuck_at_gate1_seeded() -> None:
    bind, _plan, seed, seed_doc = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-stuck",
        plan_id="act-v7gb-m4-plan-stuck",
        seed_id="act-v7gb-m4-seed-stuck",
    )
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-v7e-confirm-m4-alone",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "reviewed_source_sha256": seed_doc["reviewed_source_sha256"],
        "confirmation_note": "V7e alone keeps cascade stuck",
    }
    decided = submit_action(_settings(), v7e_doc, mutation_enabled=True)
    assert decided.status == "accepted"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_seeded"
    rows = project_workspace_results(WS)
    seed_row = next(r for r in rows if r["result_id"] == seed.result_id)
    lim = set(seed_row.get("limitations") or [])
    assert "gate_cascade_locked" in lim
    assert "gate1_confirmed" not in (t.get("limitations") or [])


# TC-B-M4-07
def test_pure_v7e_fixture_unaffected() -> None:
    gauth = default_gate_surface_authority()
    gate = gauth.seed_gate1_pending(
        workspace_id=WS,
        gate_id="gate-pure-v7e-m4",
        task_id="task-pure-v7e-m4",
        reviewed_source_sha256="b" * 64,
    )
    assert gate.status == "pending"
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-v7e-pure-m4",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:task-pure-v7e-m4",
        "reviewed_source_sha256": "b" * 64,
        "confirmation_note": "pure V7e fixture gate",
    }
    decided = submit_action(_settings(), v7e_doc, mutation_enabled=True)
    assert decided.status == "accepted"
    post = gauth.get(WS, "gate-pure-v7e-m4")
    assert post is not None and post.status == "confirmed"
    tasks = project_workspace_tasks(WS)
    assert all(t.get("cascade_stage") in (None, "") for t in tasks)


# TC-B-M4-08
def test_missing_seed_not_confirmable() -> None:
    bind, _plan = _plan_confirmed(
        bind_id="act-v7gb-m4-bind-noseed",
        plan_id="act-v7gb-m4-plan-noseed",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id="gate-missing-m4",
        client_action_id="act-v7gb-m4-confirm-noseed",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate1_not_confirmable"


# TC-B-M4-09
def test_wrong_bind_digest() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-wbd",
        plan_id="act-v7gb-m4-plan-wbd",
        seed_id="act-v7gb-m4-seed-wbd",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest="c" * 64,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-wbd",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_bind_digest_mismatch"


# TC-B-M4-10
def test_wrong_plan_digest() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-wpd",
        plan_id="act-v7gb-m4-plan-wpd",
        seed_id="act-v7gb-m4-seed-wpd",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        plan_digest="d" * 64,
        client_action_id="act-v7gb-m4-confirm-wpd",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_plan_digest_mismatch"


# TC-B-M4-11
def test_wrong_formula_source_digest() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-wfs",
        plan_id="act-v7gb-m4-plan-wfs",
        seed_id="act-v7gb-m4-seed-wfs",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        reviewed_source_sha256="e" * 64,
        client_action_id="act-v7gb-m4-confirm-wfs",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_formula_source_digest_mismatch"


# TC-B-M4-12
def test_wrong_gate1_id() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-wgi",
        plan_id="act-v7gb-m4-plan-wgi",
        seed_id="act-v7gb-m4-seed-wgi",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id="gate-wrong-id-m4",
        client_action_id="act-v7gb-m4-confirm-wgi",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate1_id_mismatch"
    assert seed.gate_id != "gate-wrong-id-m4"


# TC-B-M4-13
def test_options_a_wrong_vertical() -> None:
    opt = submit_action(
        _settings(),
        _options_doc(client_action_id="act-v7ga-wrong-vert-m4"),
        mutation_enabled=True,
    )
    assert opt.status == "accepted"
    doc = _confirm_doc(
        task_id=opt.task_id,
        bind_digest=opt.action_digest,
        expected_gate1_id="gate-na-m4",
        plan_digest="f" * 64,
        reviewed_source_sha256="a" * 64,
        client_action_id="act-v7gb-m4-confirm-wrongvert",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_wrong_vertical"


# TC-B-M4-14
def test_unknown_task() -> None:
    doc = _confirm_doc(
        task_id="task-does-not-exist-m4",
        bind_digest="a" * 64,
        expected_gate1_id="gate-na",
        plan_digest="b" * 64,
        reviewed_source_sha256="c" * 64,
        client_action_id="act-v7gb-m4-confirm-missing",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_not_found"


# TC-B-M4-15
def test_already_gate1_confirmed_conflict() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-dup",
        plan_id="act-v7gb-m4-plan-dup",
        seed_id="act-v7gb-m4-seed-dup",
    )
    doc1 = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-dup1",
    )
    r1 = submit_action(_settings(), doc1, mutation_enabled=True)
    assert r1.status == "accepted"
    doc2 = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-dup2",
    )
    r2 = submit_action(_settings(), doc2, mutation_enabled=True)
    assert r2.status == "conflict"
    assert r2.reason_code == "cascade_already_gate1_confirmed"


# TC-B-M4-16
def test_idempotent_replay() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-idem",
        plan_id="act-v7gb-m4-plan-idem",
        seed_id="act-v7gb-m4-seed-idem",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-idem",
    )
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    r2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    assert r2.status == "accepted"
    assert r1.result_id == r2.result_id
    assert r1.attempt_id == r2.attempt_id
    assert r1.run_id == r2.run_id
    conf_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_gate1_confirm"
    ]
    assert len(conf_results) == 1
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_confirmed"


# TC-B-M4-17
def test_client_action_id_digest_conflict() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-cdc",
        plan_id="act-v7gb-m4-plan-cdc",
        seed_id="act-v7gb-m4-seed-cdc",
    )
    doc1 = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-cdc",
        confirmation_note="note one",
    )
    r1 = submit_action(_settings(), doc1, mutation_enabled=True)
    assert r1.status == "accepted"
    doc2 = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-cdc",
        confirmation_note="note two different",
    )
    r2 = submit_action(_settings(), doc2, mutation_enabled=True)
    assert r2.status == "conflict"


# TC-B-M4-18
def test_empty_confirmation_note_rejected() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-empty",
        plan_id="act-v7gb-m4-plan-empty",
        seed_id="act-v7gb-m4-seed-empty",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-empty",
        confirmation_note="   ",
    )
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError)):
        try:
            parse_user_action_v1(doc)
        except AgentWorkspaceActionError:
            raise
        submit_action(_settings(), doc, mutation_enabled=True)


# TC-B-M4-19
def test_reject_smuggled_keys() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-smug",
        plan_id="act-v7gb-m4-plan-smug",
        seed_id="act-v7gb-m4-seed-smug",
    )
    base = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-smug",
    )
    for key, val in (
        ("auth_envelope", {"tickers": ["AAPL"]}),
        ("provider_mode", "live_futu_ro"),
        ("gate_id", "gate-smuggled"),
        ("plan_version", 1),
        ("seed_note", "nope"),
        ("extra_field", "x"),
    ):
        bad = dict(base)
        bad["client_action_id"] = f"act-smug-m4-{key}"
        bad[key] = val
        with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, TypeError, ValueError)):
            try:
                parse_user_action_v1(bad)
            except AgentWorkspaceActionError:
                raise
            submit_action(_settings(), bad, mutation_enabled=True)


# TC-B-M4-20
def test_mutation_off() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-mutoff",
        plan_id="act-v7gb-m4-plan-mutoff",
        seed_id="act-v7gb-m4-seed-mutoff",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-mutoff",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"


# TC-B-M4-21
def test_global_research_plan_confirm_still_dark() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-darkplan",
        plan_id="act-v7gb-m4-plan-darkplan",
        seed_id="act-v7gb-m4-seed-darkplan",
    )
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-darkplan",
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"
    dark = {
        "schema_version": 1,
        "kind": "research.plan.confirm",
        "client_action_id": "act-global-plan-after-m4",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "plan_version": 1,
        "plan_digest": "a" * 64,
        "confirmation_note": "should stay dark",
    }
    receipt = submit_action(_settings(), dark, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"


# TC-B-M4-22
def test_research_start_still_dark() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-darkstart",
        plan_id="act-v7gb-m4-plan-darkstart",
        seed_id="act-v7gb-m4-seed-darkstart",
    )
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-darkstart",
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"
    dark = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "act-start-after-m4",
        "workspace": {"workspace_id": WS},
        "managed_session_ref": "session:s-dark-m4",
        "payload_ref": "payload:sha256:" + ("a" * 64),
        "payload_digest": "a" * 64,
        "initial_mode": "plan_only",
    }
    receipt = submit_action(_settings(), dark, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"


# TC-B-M4-23
def test_no_auto_gate2() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-nog2",
        plan_id="act-v7gb-m4-plan-nog2",
        seed_id="act-v7gb-m4-seed-nog2",
    )
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-nog2",
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"
    gates = project_workspace_gates(WS)
    assert all(g.get("gate_kind") != "gate2" for g in gates)
    assert all(g.get("gate_kind") == "gate1" for g in gates)


# TC-B-M4-24
def test_follow_sse_vertical_ids_include_confirm() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-follow",
        plan_id="act-v7gb-m4-plan-follow",
        seed_id="act-v7gb-m4-seed-follow",
    )
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-follow",
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    page = ws.follow(ROOT_USER_ID, WorkspaceRef(workspace_id=WS), after=0).to_public_dict()
    assert conf.task_id in (page.get("tasks") or [])
    assert conf.attempt_id in (page.get("attempts") or [])
    assert conf.run_id in (page.get("runs") or [])
    assert any(r.get("result_id") == conf.result_id for r in page.get("results") or [])


# TC-B-M4-25
def test_prior_results_preserved() -> None:
    bind, plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-pres",
        plan_id="act-v7gb-m4-plan-pres",
        seed_id="act-v7gb-m4-seed-pres",
    )
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-pres",
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"
    rows = {r["result_id"]: r for r in project_workspace_results(WS)}
    assert bind.result_id in rows
    assert plan.result_id in rows
    assert seed.result_id in rows
    assert conf.result_id in rows
    assert rows[plan.result_id].get("source") == "hermetic_vertical_b_plan_confirm"
    assert rows[seed.result_id].get("source") == "hermetic_vertical_b_gate1_seed"
    assert rows[conf.result_id].get("source") == "hermetic_vertical_b_gate1_confirm"


# TC-B-M4-26
def test_zero_orders_invariant_on_confirm_source() -> None:
    src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/"
        "vertical_binding_authority.py"
    ).read_text()
    start = src.index("def confirm_factor_vertical_b_gate1")
    end = src.index("def seed_factor_vertical_b_gate2", start)
    body = src[start:end]
    for banned in (
        "place_order",
        "submit_order",
        "unlock_trade",
        "import hqa",
        "import_hqa",
        "seed_gate2",
        "gate2_seed",
    ):
        assert banned not in body


# TC-B-M4-27
def test_v7e_confirm_source_has_no_cascade_write() -> None:
    gauth_src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/"
        "gate_surface_authority.py"
    ).read_text()
    start = gauth_src.index("def confirm_formula_source")
    end = gauth_src.index("def review_candidate", start)
    body = gauth_src[start:end]
    assert "cascade_stage" not in body
    assert "vertical_binding" not in body
    assert "_tasks" not in body

    saga_src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/submission_saga.py"
    ).read_text()
    s_start = saga_src.index("def submit_confirm_formula_source")
    # next def after this submit
    s_end = saga_src.index("\ndef submit_", s_start + 10)
    s_body = saga_src[s_start:s_end]
    assert "cascade_stage" not in s_body
    assert "confirm_factor_vertical_b_gate1" not in s_body


# TC-B-M4-28
def test_concurrent_m4_storm() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-race",
        plan_id="act-v7gb-m4-plan-race",
        seed_id="act-v7gb-m4-seed-race",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-race",
    )
    settings = _settings()

    def _once():
        return submit_action(settings, doc, mutation_enabled=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_once) for _ in range(16)]
        receipts = [f.result() for f in futs]
    assert all(r.status == "accepted" for r in receipts)
    assert len({r.result_id for r in receipts}) == 1
    assert len({r.gate_id for r in receipts}) == 1
    conf_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_gate1_confirm"
    ]
    assert len(conf_results) == 1
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_confirmed"
    gates = [g for g in project_workspace_gates(WS) if g.get("status") == "confirmed"]
    assert len(gates) == 1


# TC-B-M4-29
def test_concurrent_v7e_and_m4() -> None:
    bind, _plan, seed, seed_doc = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-race2",
        plan_id="act-v7gb-m4-plan-race2",
        seed_id="act-v7gb-m4-seed-race2",
    )
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-v7e-race-m4",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "reviewed_source_sha256": seed_doc["reviewed_source_sha256"],
        "confirmation_note": "V7e race with M4",
    }
    m4_doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-race2",
        reviewed_source_sha256=seed_doc["reviewed_source_sha256"],
    )
    settings = _settings()

    def _v7e():
        return submit_action(settings, v7e_doc, mutation_enabled=True)

    def _m4():
        return submit_action(settings, m4_doc, mutation_enabled=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_v7e), pool.submit(_m4), pool.submit(_m4), pool.submit(_v7e)]
        results = [f.result() for f in futs]

    # End state must be consistent: gate confirmed + cascade gate1_confirmed
    # (or ordered failure then successful retry). Never unlock umbrella.
    t = project_workspace_tasks(WS)[0]
    gauth = default_gate_surface_authority()
    gate = gauth.get(WS, seed.gate_id)
    assert gate is not None
    assert gate.status == "confirmed"
    # If M4 succeeded at least once (or via retry after V7e), stage advances.
    m4_ok = any(
        r.status == "accepted" and r.client_action_id == "act-v7gb-m4-confirm-race2"
        for r in results
    )
    if not m4_ok:
        # Retry M4 once after race settles.
        retry = submit_action(settings, m4_doc, mutation_enabled=True)
        assert retry.status == "accepted"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_confirmed"
    lim = set(t.get("limitations") or [])
    assert "gate_cascade_locked" in lim
    assert "gate_cascade_unlock" not in lim
    conf_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_gate1_confirm"
    ]
    assert len(conf_results) == 1


# TC-B-M4-30
def test_options_a_isolation() -> None:
    opt = submit_action(
        _settings(),
        _options_doc(client_action_id="act-v7ga-iso-m4b"),
        mutation_enabled=True,
    )
    assert opt.status == "accepted"
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-iso",
        plan_id="act-v7gb-m4-plan-iso",
        seed_id="act-v7gb-m4-seed-iso",
    )
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-iso",
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"
    tasks = {t["task_id"]: t for t in project_workspace_tasks(WS)}
    assert tasks[opt.task_id].get("cascade_stage") in (None, "")
    assert tasks[bind.task_id]["cascade_stage"] == "gate1_confirmed"


# TC-B-M4-31
def test_m4_then_v7e_conflicts() -> None:
    bind, _plan, seed, seed_doc = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-thenv7e",
        plan_id="act-v7gb-m4-plan-thenv7e",
        seed_id="act-v7gb-m4-seed-thenv7e",
    )
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-thenv7e",
            reviewed_source_sha256=seed_doc["reviewed_source_sha256"],
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-v7e-after-m4",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "reviewed_source_sha256": seed_doc["reviewed_source_sha256"],
        "confirmation_note": "V7e after M4 should conflict",
    }
    decided = submit_action(_settings(), v7e_doc, mutation_enabled=True)
    assert decided.status == "conflict"
    # V7e find-pending returns gate_challenge_not_found when the only match is
    # already decided by a different action (M4); gate_not_pending if row is
    # reached via exact gate_id path with non-matching decision action.
    assert decided.reason_code in {"gate_not_pending", "gate_challenge_not_found"}


# TC-B-M4-32
def test_rejected_gate_not_confirmable() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-rej",
        plan_id="act-v7gb-m4-plan-rej",
        seed_id="act-v7gb-m4-seed-rej",
    )
    gauth = default_gate_surface_authority()
    row = gauth.get(WS, seed.gate_id)
    assert row is not None
    # Fabricate non-pending non-confirmed status.
    row.status = "rejected"
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-rej",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate1_not_confirmable"


# TC-B-M4-33
def test_canonical_source_still_bind_era_only() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-era",
        plan_id="act-v7gb-m4-plan-era",
        seed_id="act-v7gb-m4-seed-era",
    )
    binder = default_vertical_binding_authority()
    task = binder.get_task(WS, bind.task_id)
    assert task is not None
    sketch = _formula_sketch_for_task(bind.task_id)
    d1 = canonical_factor_b_formula_source_digest(task, formula_sketch=sketch)
    d2 = canonical_factor_b_formula_source_digest(
        task, formula_sketch=sketch + "; plan_only:placeholder"
    )
    assert d1 != d2
    # Confirm with bind-era digest succeeds.
    conf = submit_action(
        _settings(),
        _confirm_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m4-confirm-era",
            reviewed_source_sha256=d1,
        ),
        mutation_enabled=True,
    )
    assert conf.status == "accepted"


# TC-B-M4-34 (parse/digest smoke covered inline; regression is suite-level)
def test_parse_and_digest_confirm_stable() -> None:
    bind, _plan, seed, _ = _gate1_seeded(
        bind_id="act-v7gb-m4-bind-parse",
        plan_id="act-v7gb-m4-plan-parse",
        seed_id="act-v7gb-m4-seed-parse",
    )
    doc = _confirm_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m4-confirm-parse",
    )
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is ConfirmFactorVerticalBGate1
    d1 = canonical_action_digest(parsed)
    d2 = canonical_action_digest(parse_user_action_v1(action_to_document(parsed)))
    assert d1 == d2
    assert len(d1) == 64
    # Round-trip document retains closed field set.
    out = action_to_document(parsed)
    assert out["kind"] == "vertical.factor_b.gate1_confirm"
    assert out["expected_gate1_id"] == seed.gate_id
    assert "seed_note" not in out
    assert "gate_id" not in out
