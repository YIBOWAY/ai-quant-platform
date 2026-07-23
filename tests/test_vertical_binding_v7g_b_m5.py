"""V7g-B-M5: hermetic Vertical B factor Gate2 seed cascade notch."""

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
    SeedFactorVerticalBGate2,
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
    canonical_factor_b_gate2_candidate_digest,
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

WS = "ws-v7g-vertical-b-m5"
PAPER_DIGEST = "a" * 64
SEED_LIMITATIONS = {
    "hermetic_fixture",
    "not_live_backtest",
    "not_tradeable",
    "zero_orders",
    "plan_confirmed",
    "gate1_seeded",
    "gate1_confirmed",
    "gate2_seeded",
    "gate_cascade_locked",
    "not_git_commit",
}
BANNED_LIMITATIONS = {
    "plan_confirm_required",
    "gate_cascade_unlock",
    "gate2_decide",
    "gate2_confirmed",
    "start_research",
    "tradeable",
    "live_backtest",
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
    client_action_id: str = "act-v7gb-m5-bind",
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


def _options_doc(*, client_action_id: str = "act-v7ga-iso-m5") -> dict:
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
    client_action_id: str = "act-v7gb-m5-bind",
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
    client_action_id: str = "act-v7gb-m5-plan",
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
    bind_id: str = "act-v7gb-m5-bind",
    plan_id: str = "act-v7gb-m5-plan",
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


def _candidate_digest_for_task(task_id: str) -> str:
    binder = default_vertical_binding_authority()
    task = binder.get_task(WS, task_id)
    assert task is not None
    sketch = _formula_sketch_for_task(task_id)
    return canonical_factor_b_gate2_candidate_digest(task, formula_sketch=sketch)


def _seed_gate1_doc(
    *,
    task_id: str,
    bind_digest: str,
    plan_digest: str | None = None,
    reviewed_source_sha256: str | None = None,
    client_action_id: str = "act-v7gb-m5-g1seed",
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


def _confirm_gate1_doc(
    *,
    task_id: str,
    bind_digest: str,
    expected_gate1_id: str,
    plan_digest: str | None = None,
    reviewed_source_sha256: str | None = None,
    client_action_id: str = "act-v7gb-m5-g1confirm",
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


def _gate1_confirmed(
    *,
    bind_id: str = "act-v7gb-m5-bind",
    plan_id: str = "act-v7gb-m5-plan",
    seed_id: str = "act-v7gb-m5-g1seed",
    confirm_id: str = "act-v7gb-m5-g1confirm",
):
    bind, plan = _plan_confirmed(bind_id=bind_id, plan_id=plan_id)
    seed_doc = _seed_gate1_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id=seed_id,
    )
    seed = submit_action(_settings(), seed_doc, mutation_enabled=True)
    assert seed.status == "accepted"
    conf_doc = _confirm_gate1_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id=confirm_id,
        reviewed_source_sha256=seed_doc["reviewed_source_sha256"],
    )
    conf = submit_action(_settings(), conf_doc, mutation_enabled=True)
    assert conf.status == "accepted"
    return bind, plan, seed, conf, seed_doc, conf_doc


def _gate2_seed_doc(
    *,
    task_id: str,
    bind_digest: str,
    expected_gate1_id: str,
    expected_gate1_confirm_digest: str | None = None,
    plan_digest: str | None = None,
    expected_candidate_digest: str | None = None,
    client_action_id: str = "act-v7gb-m5-seed",
    seed_note: str = "seed Gate2 candidate for hermetic factor_b",
) -> dict:
    pd = plan_digest if plan_digest is not None else _plan_digest_for_task(task_id)
    if expected_gate1_confirm_digest is None:
        binder = default_vertical_binding_authority()
        task = binder.get_task(WS, task_id)
        assert task is not None
        assert task.gate1_confirm_action_digest
        expected_gate1_confirm_digest = task.gate1_confirm_action_digest
    cand = (
        expected_candidate_digest
        if expected_candidate_digest is not None
        else _candidate_digest_for_task(task_id)
    )
    return {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate2_seed",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{task_id}",
        "expected_bind_digest": bind_digest,
        "expected_plan_digest": pd,
        "expected_gate1_id": expected_gate1_id,
        "expected_gate1_confirm_digest": expected_gate1_confirm_digest,
        "expected_candidate_digest": cand,
        "seed_note": seed_note,
    }


# TC-B-M5-01
def test_parse_and_digest_seed_stable() -> None:
    bind, _plan, seed, conf, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-parse",
        plan_id="act-v7gb-m5-plan-parse",
        seed_id="act-v7gb-m5-g1seed-parse",
        confirm_id="act-v7gb-m5-g1confirm-parse",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-parse",
    )
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is SeedFactorVerticalBGate2
    assert action_to_document(parsed) == doc
    d1 = canonical_action_digest(parsed)
    d2 = canonical_action_digest(parse_user_action_v1(doc))
    assert d1 == d2
    assert len(d1) == 64
    out = action_to_document(parsed)
    assert out["kind"] == "vertical.factor_b.gate2_seed"
    assert "gate_id" not in out
    assert "gate2_id" not in out
    assert "candidate_id" not in out
    assert "reviewed_source_sha256" not in out
    assert "confirmation_note" not in out
    assert conf.action_digest  # conf happened


# TC-B-M5-02
def test_seed_happy_path_new_artifacts() -> None:
    bind, _plan, seed, conf, _, _ = _gate1_confirmed()
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.task_id == bind.task_id
    assert receipt.attempt_id != conf.attempt_id
    assert receipt.run_id != conf.run_id
    assert receipt.result_id != conf.result_id
    assert receipt.terminal_status == "completed"
    assert receipt.gate_id
    assert receipt.gate_id.startswith("gate-")
    assert receipt.gate_id != seed.gate_id

    tasks = project_workspace_tasks(WS)
    assert len(tasks) == 1
    t = tasks[0]
    assert t["task_id"] == bind.task_id
    assert t["cascade_stage"] == "gate2_seeded"
    assert t["gate2_id"] == receipt.gate_id
    assert t["gate1_id"] == seed.gate_id
    assert t["attempt_id"] == receipt.attempt_id
    assert t["run_id"] == receipt.run_id
    assert t["result_id"] == receipt.result_id
    assert t["plan_digest"] == doc["expected_plan_digest"]
    assert t.get("gate2_candidate_id")
    assert t.get("gate2_expected_digest") == doc["expected_candidate_digest"]

    gates = project_workspace_gates(WS)
    g2 = next(x for x in gates if x.get("gate_id") == receipt.gate_id)
    assert g2["status"] == "pending"
    assert g2.get("gate_kind") == "gate2"


# TC-B-M5-03
def test_confirm_era_snapshot_of_gate1_confirm_pointers() -> None:
    bind, _plan, seed, conf, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-snap",
        plan_id="act-v7gb-m5-plan-snap",
        seed_id="act-v7gb-m5-g1seed-snap",
        confirm_id="act-v7gb-m5-g1confirm-snap",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-snap",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    t = project_workspace_tasks(WS)[0]
    assert t.get("gate1_confirm_attempt_id") == conf.attempt_id
    assert t.get("gate1_confirm_run_id") == conf.run_id
    assert t.get("gate1_confirm_result_id") == conf.result_id
    assert t["attempt_id"] == receipt.attempt_id
    assert t["run_id"] == receipt.run_id
    assert t["result_id"] == receipt.result_id
    # seed-era stamps untouched
    assert t.get("gate1_seed_attempt_id") or t.get("gate1_seed_action_id")
    assert t.get("gate1_id") == seed.gate_id
    assert t.get("gate1_confirm_action_digest") == conf.action_digest


# TC-B-M5-04
def test_seed_limitations_honesty() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-lim",
        plan_id="act-v7gb-m5-plan-lim",
        seed_id="act-v7gb-m5-g1seed-lim",
        confirm_id="act-v7gb-m5-g1confirm-lim",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-lim",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    rows = project_workspace_results(WS)
    seed_row = next(r for r in rows if r["result_id"] == receipt.result_id)
    lim = set(seed_row.get("limitations") or [])
    assert SEED_LIMITATIONS.issubset(lim)
    assert BANNED_LIMITATIONS.isdisjoint(lim)
    assert seed_row["sample_or_real"] == "sample"
    assert seed_row["kind"] == "factor"
    assert seed_row["payload_digest"] == doc["expected_candidate_digest"]
    assert seed_row.get("source") == "hermetic_vertical_b_gate2_seed"


# TC-B-M5-05
def test_seed_exact_links() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-link",
        plan_id="act-v7gb-m5-plan-link",
        seed_id="act-v7gb-m5-g1seed-link",
        confirm_id="act-v7gb-m5-g1confirm-link",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-link",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    rows = project_workspace_results(WS)
    seed_row = next(r for r in rows if r["result_id"] == receipt.result_id)
    assert seed_row["task_id"] == bind.task_id
    assert seed_row["attempt_id"] == receipt.attempt_id
    assert seed_row["run_id"] == receipt.run_id
    t = project_workspace_tasks(WS)[0]
    assert t["gate2_id"] == receipt.gate_id
    gates = project_workspace_gates(WS)
    g2 = next(g for g in gates if g.get("gate_id") == t["gate2_id"])
    assert g2.get("candidate_id") == t.get("gate2_candidate_id")
    assert g2.get("expected_digest") == t.get("gate2_expected_digest")


# TC-B-M5-06
def test_seed_idempotent_replay() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-idem",
        plan_id="act-v7gb-m5-plan-idem",
        seed_id="act-v7gb-m5-g1seed-idem",
        confirm_id="act-v7gb-m5-g1confirm-idem",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-idem",
    )
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    r2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    assert r2.status == "accepted"
    assert r1.task_id == r2.task_id
    assert r1.result_id == r2.result_id
    assert r1.gate_id == r2.gate_id
    assert r1.attempt_id == r2.attempt_id
    assert r1.run_id == r2.run_id
    gates = [
        g
        for g in project_workspace_gates(WS)
        if g.get("status") == "pending" and g.get("gate_id") == r1.gate_id
    ]
    assert len(gates) == 1
    seed_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_gate2_seed"
    ]
    assert len(seed_results) == 1


# TC-B-M5-07
def test_seed_digest_conflict() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-conf",
        plan_id="act-v7gb-m5-plan-conf",
        seed_id="act-v7gb-m5-g1seed-conf",
        confirm_id="act-v7gb-m5-g1confirm-conf",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-conf",
    )
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    bad = dict(doc)
    bad["seed_note"] = "不同的 seed note 造成 digest 冲突"
    r2 = submit_action(_settings(), bad, mutation_enabled=True)
    assert r2.status == "conflict"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate2_seeded"
    assert t["gate2_id"] == r1.gate_id


# TC-B-M5-08
def test_seed_mutation_off() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-mut",
        plan_id="act-v7gb-m5-plan-mut",
        seed_id="act-v7gb-m5-g1seed-mut",
        confirm_id="act-v7gb-m5-g1confirm-mut",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-mut",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_confirmed"
    assert not any(g.get("gate_kind") == "gate2" for g in project_workspace_gates(WS))


# TC-B-M5-09
def test_seed_missing_task() -> None:
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate2_seed",
        "client_action_id": "act-v7gb-m5-seed-missing",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:task-does-not-exist",
        "expected_bind_digest": "a" * 64,
        "expected_plan_digest": "b" * 64,
        "expected_gate1_id": "gate-missing",
        "expected_gate1_confirm_digest": "c" * 64,
        "expected_candidate_digest": "d" * 64,
        "seed_note": "missing task",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_not_found"


# TC-B-M5-10
def test_seed_wrong_bind_digest() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-wbd",
        plan_id="act-v7gb-m5-plan-wbd",
        seed_id="act-v7gb-m5-g1seed-wbd",
        confirm_id="act-v7gb-m5-g1confirm-wbd",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest="f" * 64,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-wbd",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_bind_digest_mismatch"


# TC-B-M5-11
def test_seed_wrong_plan_digest() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-wpd",
        plan_id="act-v7gb-m5-plan-wpd",
        seed_id="act-v7gb-m5-g1seed-wpd",
        confirm_id="act-v7gb-m5-g1confirm-wpd",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        plan_digest="e" * 64,
        client_action_id="act-v7gb-m5-seed-wpd",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_plan_digest_mismatch"


# TC-B-M5-12
def test_seed_wrong_gate1_id() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-wg1",
        plan_id="act-v7gb-m5-plan-wg1",
        seed_id="act-v7gb-m5-g1seed-wg1",
        confirm_id="act-v7gb-m5-g1confirm-wg1",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id="gate-wrong-id",
        client_action_id="act-v7gb-m5-seed-wg1",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate1_id_mismatch"
    _ = seed


# TC-B-M5-13
def test_seed_wrong_gate1_confirm_digest() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-wcd",
        plan_id="act-v7gb-m5-plan-wcd",
        seed_id="act-v7gb-m5-g1seed-wcd",
        confirm_id="act-v7gb-m5-g1confirm-wcd",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        expected_gate1_confirm_digest="c" * 64,
        client_action_id="act-v7gb-m5-seed-wcd",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate1_confirm_digest_mismatch"


# TC-B-M5-14
def test_seed_wrong_candidate_digest() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-wcand",
        plan_id="act-v7gb-m5-plan-wcand",
        seed_id="act-v7gb-m5-g1seed-wcand",
        confirm_id="act-v7gb-m5-g1confirm-wcand",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        expected_candidate_digest="d" * 64,
        client_action_id="act-v7gb-m5-seed-wcand",
    )
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_candidate_digest_mismatch"


# TC-B-M5-15
def test_seed_from_gate1_seeded_blocked() -> None:
    bind, _plan = _plan_confirmed(
        bind_id="act-v7gb-m5-bind-g1s",
        plan_id="act-v7gb-m5-plan-g1s",
    )
    seed_doc = _seed_gate1_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        client_action_id="act-v7gb-m5-g1seed-only",
    )
    seed = submit_action(_settings(), seed_doc, mutation_enabled=True)
    assert seed.status == "accepted"
    # Craft gate2 seed with dummy confirm digest — stage not gate1_confirmed
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate2_seed",
        "client_action_id": "act-v7gb-m5-seed-from-g1s",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "expected_bind_digest": bind.action_digest,
        "expected_plan_digest": _plan_digest_for_task(bind.task_id),
        "expected_gate1_id": seed.gate_id,
        "expected_gate1_confirm_digest": "a" * 64,
        "expected_candidate_digest": "b" * 64,
        "seed_note": "should block from gate1_seeded",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate2_not_seedable"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate1_seeded"


# TC-B-M5-16
def test_seed_from_plan_confirmed_blocked() -> None:
    bind, _plan = _plan_confirmed(
        bind_id="act-v7gb-m5-bind-pc",
        plan_id="act-v7gb-m5-plan-pc",
    )
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate2_seed",
        "client_action_id": "act-v7gb-m5-seed-from-pc",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "expected_bind_digest": bind.action_digest,
        "expected_plan_digest": _plan_digest_for_task(bind.task_id),
        "expected_gate1_id": "gate-none",
        "expected_gate1_confirm_digest": "a" * 64,
        "expected_candidate_digest": "b" * 64,
        "seed_note": "should block from plan_confirmed",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_gate2_not_seedable"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "plan_confirmed"


# TC-B-M5-17
def test_seed_options_a_wrong_vertical() -> None:
    opt = submit_action(
        _settings(),
        _options_doc(client_action_id="act-v7ga-wrong-vert-m5"),
        mutation_enabled=True,
    )
    assert opt.status == "accepted"
    doc = {
        "schema_version": 1,
        "kind": "vertical.factor_b.gate2_seed",
        "client_action_id": "act-v7gb-m5-seed-opt",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{opt.task_id}",
        "expected_bind_digest": opt.action_digest,
        "expected_plan_digest": "a" * 64,
        "expected_gate1_id": "gate-x",
        "expected_gate1_confirm_digest": "b" * 64,
        "expected_candidate_digest": "c" * 64,
        "seed_note": "options wrong vertical",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "factor_b_task_wrong_vertical"


# TC-B-M5-18
def test_double_seed_different_action_conflict() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-dbl",
        plan_id="act-v7gb-m5-plan-dbl",
        seed_id="act-v7gb-m5-g1seed-dbl",
        confirm_id="act-v7gb-m5-g1confirm-dbl",
    )
    doc1 = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-dbl-1",
    )
    r1 = submit_action(_settings(), doc1, mutation_enabled=True)
    assert r1.status == "accepted"
    doc2 = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-dbl-2",
    )
    r2 = submit_action(_settings(), doc2, mutation_enabled=True)
    assert r2.status == "conflict"
    assert r2.reason_code == "cascade_already_gate2_seeded"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate2_seeded"
    assert t["gate2_id"] == r1.gate_id


# TC-B-M5-19
def test_start_research_still_dark_after_seed() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-darkstart",
        plan_id="act-v7gb-m5-plan-darkstart",
        seed_id="act-v7gb-m5-g1seed-darkstart",
        confirm_id="act-v7gb-m5-g1confirm-darkstart",
    )
    seeded = submit_action(
        _settings(),
        _gate2_seed_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m5-seed-darkstart",
        ),
        mutation_enabled=True,
    )
    assert seeded.status == "accepted"
    dark = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "act-start-after-m5",
        "workspace": {"workspace_id": WS},
        "managed_session_ref": "session:s-dark-m5",
        "payload_ref": "payload:sha256:" + ("a" * 64),
        "payload_digest": "a" * 64,
        "initial_mode": "plan_only",
    }
    receipt = submit_action(_settings(), dark, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"


# TC-B-M5-20
def test_global_confirm_research_plan_still_dark() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-darkplan",
        plan_id="act-v7gb-m5-plan-darkplan",
        seed_id="act-v7gb-m5-g1seed-darkplan",
        confirm_id="act-v7gb-m5-g1confirm-darkplan",
    )
    seeded = submit_action(
        _settings(),
        _gate2_seed_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m5-seed-darkplan",
        ),
        mutation_enabled=True,
    )
    assert seeded.status == "accepted"
    dark = {
        "schema_version": 1,
        "kind": "research.plan.confirm",
        "client_action_id": "act-global-plan-after-m5",
        "workspace": {"workspace_id": WS},
        "task_ref": f"task:{bind.task_id}",
        "plan_version": 1,
        "plan_digest": "a" * 64,
        "confirmation_note": "should stay dark",
    }
    receipt = submit_action(_settings(), dark, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"


# TC-B-M5-21
def test_no_auto_gate2_decide() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-nodec",
        plan_id="act-v7gb-m5-plan-nodec",
        seed_id="act-v7gb-m5-g1seed-nodec",
        confirm_id="act-v7gb-m5-g1confirm-nodec",
    )
    receipt = submit_action(
        _settings(),
        _gate2_seed_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m5-seed-nodec",
        ),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    gauth = default_gate_surface_authority()
    g2 = gauth.get(WS, receipt.gate_id)
    assert g2 is not None
    assert g2.status == "pending"
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate2_seeded"
    assert t["cascade_stage"] != "gate2_confirmed"


# TC-B-M5-22
def test_v7e_review_after_seed_keeps_cascade_at_gate2_seeded() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-v7e",
        plan_id="act-v7gb-m5-plan-v7e",
        seed_id="act-v7gb-m5-g1seed-v7e",
        confirm_id="act-v7gb-m5-g1confirm-v7e",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-v7e",
    )
    seeded = submit_action(_settings(), doc, mutation_enabled=True)
    assert seeded.status == "accepted"
    t = project_workspace_tasks(WS)[0]
    cand_id = t["gate2_candidate_id"]
    cand_digest = t["gate2_expected_digest"]
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate2.candidate.review",
        "client_action_id": "act-v7e-review-after-m5",
        "workspace": {"workspace_id": WS},
        "candidate_ref": f"candidate:{cand_id}",
        "expected_digest": cand_digest,
        "expected_status": "pending",
        "note": "V7e review alone keeps cascade at gate2_seeded",
    }
    reviewed = submit_action(_settings(), v7e_doc, mutation_enabled=True)
    assert reviewed.status == "accepted"
    gauth = default_gate_surface_authority()
    g2 = gauth.get(WS, seeded.gate_id)
    assert g2 is not None
    assert g2.status == "reviewed"
    t2 = project_workspace_tasks(WS)[0]
    assert t2["cascade_stage"] == "gate2_seeded"
    rows = project_workspace_results(WS)
    seed_row = next(r for r in rows if r["result_id"] == seeded.result_id)
    lim = set(seed_row.get("limitations") or [])
    assert "gate_cascade_locked" in lim


# TC-B-M5-23
def test_v7e_alone_before_m5_stays_gate1_confirmed() -> None:
    bind, _plan, seed, conf, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-stuck",
        plan_id="act-v7gb-m5-plan-stuck",
        seed_id="act-v7gb-m5-g1seed-stuck",
        confirm_id="act-v7gb-m5-g1confirm-stuck",
    )
    # Pure fixture Gate2 without M5 cascade seed
    gauth = default_gate_surface_authority()
    gauth.seed_gate2_pending(
        workspace_id=WS,
        gate_id="gate-fixture-before-m5",
        candidate_id="cand-fixture-before-m5",
        expected_digest="b" * 64,
    )
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate2.candidate.review",
        "client_action_id": "act-v7e-review-before-m5",
        "workspace": {"workspace_id": WS},
        "candidate_ref": "candidate:cand-fixture-before-m5",
        "expected_digest": "b" * 64,
        "expected_status": "pending",
        "note": "V7e alone before M5",
    }
    decided = submit_action(_settings(), v7e_doc, mutation_enabled=True)
    assert decided.status == "accepted"
    t = project_workspace_tasks(WS)[0]
    assert t["task_id"] == bind.task_id
    assert t["cascade_stage"] == "gate1_confirmed"
    assert t.get("gate2_id") in (None, "")
    _ = seed, conf


# TC-B-M5-24
def test_pure_v7e_gate2_fixture_unaffected() -> None:
    gauth = default_gate_surface_authority()
    gate = gauth.seed_gate2_pending(
        workspace_id=WS,
        gate_id="gate-pure-v7e-m5",
        candidate_id="cand-pure-v7e-m5",
        expected_digest="b" * 64,
    )
    assert gate.status == "pending"
    v7e_doc = {
        "schema_version": 1,
        "kind": "gate2.candidate.review",
        "client_action_id": "act-v7e-pure-m5",
        "workspace": {"workspace_id": WS},
        "candidate_ref": "candidate:cand-pure-v7e-m5",
        "expected_digest": "b" * 64,
        "expected_status": "pending",
        "note": "pure V7e fixture gate2",
    }
    decided = submit_action(_settings(), v7e_doc, mutation_enabled=True)
    assert decided.status == "accepted"
    post = gauth.get(WS, "gate-pure-v7e-m5")
    assert post is not None and post.status == "reviewed"
    tasks = project_workspace_tasks(WS)
    assert all(t.get("cascade_stage") in (None, "") for t in tasks)


# TC-B-M5-25
def test_follow_sse_vertical_ids_include_gate2_seed() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-follow",
        plan_id="act-v7gb-m5-plan-follow",
        seed_id="act-v7gb-m5-g1seed-follow",
        confirm_id="act-v7gb-m5-g1confirm-follow",
    )
    receipt = submit_action(
        _settings(),
        _gate2_seed_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m5-seed-follow",
        ),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    page = ws.follow(ROOT_USER_ID, WorkspaceRef(workspace_id=WS), after=0).to_public_dict()
    assert receipt.task_id in (page.get("tasks") or [])
    assert receipt.attempt_id in (page.get("attempts") or [])
    assert receipt.run_id in (page.get("runs") or [])
    assert any(r.get("result_id") == receipt.result_id for r in page.get("results") or [])
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS)).to_public_dict()
    assert any(x.get("gate_id") == receipt.gate_id for x in snap.get("gates") or [])


# TC-B-M5-26
def test_gate_observe_journal_raised() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-obs",
        plan_id="act-v7gb-m5-plan-obs",
        seed_id="act-v7gb-m5-g1seed-obs",
        confirm_id="act-v7gb-m5-g1confirm-obs",
    )
    receipt = submit_action(
        _settings(),
        _gate2_seed_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m5-seed-obs",
        ),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    gates = project_workspace_gates(WS)
    assert any(g.get("gate_id") == receipt.gate_id and g.get("status") == "pending" for g in gates)
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS)).to_public_dict()
    assert any(x.get("gate_id") == receipt.gate_id for x in snap.get("gates") or [])
    assert snap.get("approvals") == []
    assert not any((a.get("gate_id") == receipt.gate_id) for a in (snap.get("approvals") or []))


# TC-B-M5-27
def test_prior_results_preserved() -> None:
    bind, plan, seed, conf, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-pres",
        plan_id="act-v7gb-m5-plan-pres",
        seed_id="act-v7gb-m5-g1seed-pres",
        confirm_id="act-v7gb-m5-g1confirm-pres",
    )
    g2 = submit_action(
        _settings(),
        _gate2_seed_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m5-seed-pres",
        ),
        mutation_enabled=True,
    )
    assert g2.status == "accepted"
    rows = {r["result_id"]: r for r in project_workspace_results(WS)}
    assert bind.result_id in rows
    assert plan.result_id in rows
    assert seed.result_id in rows
    assert conf.result_id in rows
    assert g2.result_id in rows
    assert rows[plan.result_id].get("source") == "hermetic_vertical_b_plan_confirm"
    assert rows[seed.result_id].get("source") == "hermetic_vertical_b_gate1_seed"
    assert rows[conf.result_id].get("source") == "hermetic_vertical_b_gate1_confirm"
    assert rows[g2.result_id].get("source") == "hermetic_vertical_b_gate2_seed"


# TC-B-M5-28
def test_zero_orders_invariant_on_seed_source() -> None:
    src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/"
        "vertical_binding_authority.py"
    ).read_text()
    start = src.index("def seed_factor_vertical_b_gate2")
    end = src.index("def _replay_outcome", start)
    body = src[start:end]
    for banned in (
        "place_order",
        "submit_order",
        "unlock_trade",
        "import hqa",
        "import_hqa",
        "kill_switch=False",
        "kill_switch = False",
    ):
        assert banned not in body
    seeder_src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/"
        "result_surface_authority.py"
    ).read_text()
    s_start = seeder_src.index("def seed_factor_vertical_b_gate2_seed_sample")
    s_end = seeder_src.index("\n    def ", s_start + 10)
    s_body = seeder_src[s_start:s_end]
    for banned in ("place_order", "submit_order", "import hqa"):
        assert banned not in s_body
    saga_src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/submission_saga.py"
    ).read_text()
    g_start = saga_src.index("def submit_seed_factor_vertical_b_gate2")
    g_end = saga_src.index("\ndef ", g_start + 10)
    g_body = saga_src[g_start:g_end]
    for banned in ("place_order", "submit_order", "import hqa"):
        assert banned not in g_body


# TC-B-M5-29
def test_v7e_source_has_no_cascade_write() -> None:
    gauth_src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/"
        "gate_surface_authority.py"
    ).read_text()
    start = gauth_src.index("def review_candidate")
    end = gauth_src.index("\n    def ", start + 10)
    body = gauth_src[start:end]
    assert "cascade_stage" not in body
    assert "vertical_binding" not in body
    assert "_tasks" not in body

    saga_src = Path(
        "/Users/sunyibo/programs/ai-quant-platform/src/quant_system/hermes/submission_saga.py"
    ).read_text()
    s_start = saga_src.index("def submit_review_candidate")
    s_end = saga_src.index("\ndef ", s_start + 10)
    s_body = saga_src[s_start:s_end]
    assert "cascade_stage" not in s_body
    assert "seed_factor_vertical_b_gate2" not in s_body


# TC-B-M5-30
def test_concurrent_seed_storm() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-race",
        plan_id="act-v7gb-m5-plan-race",
        seed_id="act-v7gb-m5-g1seed-race",
        confirm_id="act-v7gb-m5-g1confirm-race",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-race",
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
    seed_results = [
        r
        for r in project_workspace_results(WS)
        if r.get("source") == "hermetic_vertical_b_gate2_seed"
    ]
    assert len(seed_results) == 1
    t = project_workspace_tasks(WS)[0]
    assert t["cascade_stage"] == "gate2_seeded"
    gates = [
        g
        for g in project_workspace_gates(WS)
        if g.get("gate_kind") == "gate2" and g.get("status") == "pending"
    ]
    assert len(gates) == 1


# TC-B-M5-31
def test_reject_smuggled_keys() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-smug",
        plan_id="act-v7gb-m5-plan-smug",
        seed_id="act-v7gb-m5-g1seed-smug",
        confirm_id="act-v7gb-m5-g1confirm-smug",
    )
    base = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-smug",
    )
    for key, val in (
        ("auth_envelope", {"tickers": ["AAPL"]}),
        ("provider_mode", "live_futu_ro"),
        ("gate_id", "gate-smuggled"),
        ("gate2_id", "gate-smuggled-2"),
        ("candidate_id", "cand-smuggled"),
        ("candidate_ref", "candidate:c-smug"),
        ("cascade_stage", "gate2_confirmed"),
        ("reviewed_source_sha256", "a" * 64),
        ("confirmation_note", "nope"),
        ("plan_version", 1),
        ("formula_sketch", "x=1"),
        ("extra_field", "x"),
    ):
        bad = dict(base)
        bad["client_action_id"] = f"act-smug-m5-{key}"
        bad[key] = val
        with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, TypeError, ValueError)):
            try:
                parse_user_action_v1(bad)
            except AgentWorkspaceActionError:
                raise
            submit_action(_settings(), bad, mutation_enabled=True)


# TC-B-M5-32
def test_canonical_candidate_digest_golden() -> None:
    bind, _plan, seed, conf, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-gold",
        plan_id="act-v7gb-m5-plan-gold",
        seed_id="act-v7gb-m5-g1seed-gold",
        confirm_id="act-v7gb-m5-g1confirm-gold",
    )
    binder = default_vertical_binding_authority()
    task = binder.get_task(WS, bind.task_id)
    assert task is not None
    sketch = _formula_sketch_for_task(bind.task_id)
    d1 = canonical_factor_b_gate2_candidate_digest(task, formula_sketch=sketch)
    d2 = canonical_factor_b_gate2_candidate_digest(task, formula_sketch=sketch)
    assert d1 == d2
    assert len(d1) == 64
    # Sensitive to formula_sketch
    d_alt = canonical_factor_b_gate2_candidate_digest(task, formula_sketch=sketch + "; #alt")
    assert d_alt != d1
    # Sensitive to plan_digest
    from dataclasses import replace

    t2 = replace(task, plan_digest="f" * 64)
    d_plan = canonical_factor_b_gate2_candidate_digest(t2, formula_sketch=sketch)
    assert d_plan != d1
    # Sensitive to gate1_id
    t3 = replace(task, gate1_id="gate-alt")
    d_g1 = canonical_factor_b_gate2_candidate_digest(t3, formula_sketch=sketch)
    assert d_g1 != d1
    # Sensitive to gate1_confirm_action_digest
    t4 = replace(task, gate1_confirm_action_digest="e" * 64)
    d_c = canonical_factor_b_gate2_candidate_digest(t4, formula_sketch=sketch)
    assert d_c != d1
    _ = seed, conf


# TC-B-M5-33
def test_options_a_isolation_with_factor_gate2_seed() -> None:
    opt = submit_action(
        _settings(),
        _options_doc(client_action_id="act-v7ga-iso-m5b"),
        mutation_enabled=True,
    )
    assert opt.status == "accepted"
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-iso",
        plan_id="act-v7gb-m5-plan-iso",
        seed_id="act-v7gb-m5-g1seed-iso",
        confirm_id="act-v7gb-m5-g1confirm-iso",
    )
    g2 = submit_action(
        _settings(),
        _gate2_seed_doc(
            task_id=bind.task_id,
            bind_digest=bind.action_digest,
            expected_gate1_id=seed.gate_id,
            client_action_id="act-v7gb-m5-seed-iso",
        ),
        mutation_enabled=True,
    )
    assert g2.status == "accepted"
    tasks = {t["task_id"]: t for t in project_workspace_tasks(WS)}
    assert tasks[opt.task_id].get("cascade_stage") in (None, "")
    assert tasks[bind.task_id]["cascade_stage"] == "gate2_seeded"


# TC-B-M5-34
def test_empty_seed_note_rejected() -> None:
    bind, _plan, seed, _, _, _ = _gate1_confirmed(
        bind_id="act-v7gb-m5-bind-empty",
        plan_id="act-v7gb-m5-plan-empty",
        seed_id="act-v7gb-m5-g1seed-empty",
        confirm_id="act-v7gb-m5-g1confirm-empty",
    )
    doc = _gate2_seed_doc(
        task_id=bind.task_id,
        bind_digest=bind.action_digest,
        expected_gate1_id=seed.gate_id,
        client_action_id="act-v7gb-m5-seed-empty",
        seed_note="",
    )
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, TypeError, ValueError)):
        try:
            parse_user_action_v1(doc)
        except AgentWorkspaceActionError:
            raise
        submit_action(_settings(), doc, mutation_enabled=True)
