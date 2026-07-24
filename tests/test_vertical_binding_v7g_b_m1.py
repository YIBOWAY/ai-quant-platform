"""V7g-B-M1: hermetic Vertical B factor research binding on spine."""

from __future__ import annotations

import concurrent.futures

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    BindFactorVerticalB,
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
from quant_system.hermes.submission_saga import SubmissionSagaError, submit_action
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

WS = "ws-v7g-vertical-b"
PAPER_DIGEST = "a" * 64
REQUIRED_LIMITATIONS = {
    "hermetic_fixture",
    "not_live_backtest",
    "not_tradeable",
    "zero_orders",
    "plan_confirm_required",
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
    client_action_id: str = "act-v7gb-1",
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


def _options_doc(*, client_action_id: str = "act-v7ga-iso") -> dict:
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


# TC-B-M1-01
def test_parse_and_digest_bind_stable() -> None:
    doc = _bind_doc()
    parsed = parse_user_action_v1(doc)
    assert type(parsed) is BindFactorVerticalB
    assert parsed.factor_name == "momentum_20d_reversal"
    assert parsed.paper_digest == PAPER_DIGEST
    assert action_to_document(parsed) == doc
    d1 = canonical_action_digest(parsed)
    d2 = canonical_action_digest(parse_user_action_v1(doc))
    assert d1 == d2
    assert len(d1) == 64


# TC-B-M1-02
def test_bind_completed_with_evidence() -> None:
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
    assert tasks[0]["vertical"] == "factor_b"
    assert tasks[0]["result_id"] == receipt.result_id
    assert tasks[0].get("factor_name") == "momentum_20d_reversal"
    assert "ticker" not in tasks[0]

    results = project_workspace_results(WS)
    assert len(results) == 1
    row = results[0]
    assert row["result_id"] == receipt.result_id
    assert row["kind"] == "factor"
    assert row["sample_or_real"] == "sample"
    assert row["factor_name"] == "momentum_20d_reversal"
    assert row["payload_digest"] == PAPER_DIGEST
    assert row["status"] == "completed"
    assert row["task_id"] == receipt.task_id
    assert row["attempt_id"] == receipt.attempt_id
    assert row["run_id"] == receipt.run_id
    assert "hermetic_factor_fixture" in (row.get("provider_evidence") or [])
    assert row.get("ic_mean") == 0.0
    assert row.get("sample_window") == "hermetic_fixture_window"
    assert row.get("source") == "hermetic_vertical_b_binding"


# TC-B-M1-03
def test_limitations_honesty() -> None:
    submit_action(
        _settings(),
        _bind_doc(client_action_id="act-v7gb-lim"),
        mutation_enabled=True,
    )
    row = project_workspace_results(WS)[0]
    lim = set(row.get("limitations") or [])
    assert REQUIRED_LIMITATIONS.issubset(lim)


# TC-B-M1-04
def test_bind_completed_degraded_without_evidence() -> None:
    doc = _bind_doc(
        client_action_id="act-v7gb-degraded",
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
    assert row.get("ic_mean") is None
    assert row.get("sample_window") is None


# TC-B-M1-05
def test_snapshot_projection() -> None:
    doc = _bind_doc(client_action_id="act-v7gb-snap")
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
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
    assert snap["approvals"] == []
    assert snap["gates"] == []


# TC-B-M1-06
def test_exact_links() -> None:
    receipt = submit_action(
        _settings(),
        _bind_doc(client_action_id="act-v7gb-links"),
        mutation_enabled=True,
    )
    row = project_workspace_results(WS)[0]
    assert row["task_id"] == receipt.task_id
    assert row["attempt_id"] == receipt.attempt_id
    assert row["run_id"] == receipt.run_id
    links = row.get("exact_links") or {}
    assert links.get("task_id") == receipt.task_id
    assert links.get("task_ref") == f"task:{receipt.task_id}"
    assert links.get("attempt_ref") == f"attempt:{receipt.attempt_id}"
    assert links.get("run_ref") == f"run:{receipt.run_id}"


# TC-B-M1-07
def test_bind_idempotent_replay() -> None:
    doc = _bind_doc(client_action_id="act-v7gb-idem")
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    r2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    assert r2.status == "accepted"
    assert r1.task_id == r2.task_id
    assert r1.result_id == r2.result_id
    assert r1.action_digest == r2.action_digest
    assert len(project_workspace_tasks(WS)) == 1
    assert len(project_workspace_results(WS)) == 1


# TC-B-M1-08
def test_bind_digest_conflict() -> None:
    doc = _bind_doc(client_action_id="act-v7gb-conflict")
    r1 = submit_action(_settings(), doc, mutation_enabled=True)
    assert r1.status == "accepted"
    bad = dict(doc)
    bad["goal_note"] = "不同的目标备注造成 digest 冲突"
    r2 = submit_action(_settings(), bad, mutation_enabled=True)
    assert r2.status == "conflict"
    assert len(project_workspace_tasks(WS)) == 1


# TC-B-M1-09
def test_mutation_off_fail_closed() -> None:
    doc = _bind_doc(client_action_id="act-v7gb-off")
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    assert project_workspace_tasks(WS) == []
    assert project_workspace_results(WS) == []


# TC-B-M1-10
def test_start_research_still_dark() -> None:
    doc = {
        "schema_version": 1,
        "kind": "research.start",
        "client_action_id": "act-research-dark-b",
        "workspace": {"workspace_id": WS},
        "managed_session_ref": "session:s-research-dark-b",
        "payload_ref": "payload:sha256:" + ("b" * 64),
        "payload_digest": "b" * 64,
        "initial_mode": "plan_only",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"
    assert project_workspace_tasks(WS) == []


# TC-B-M1-11
def test_confirm_research_plan_still_dark() -> None:
    doc = {
        "schema_version": 1,
        "kind": "research.plan.confirm",
        "client_action_id": "act-plan-dark-b",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:t-dark",
        "plan_version": 1,
        "plan_digest": "c" * 64,
        "confirmation_note": "must stay dark",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "research_workflow_submission_unavailable"
    assert project_workspace_tasks(WS) == []


# TC-B-M1-12
def test_gate1_not_auto_seeded() -> None:
    receipt = submit_action(
        _settings(),
        _bind_doc(client_action_id="act-v7gb-no-gate"),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS)).to_public_dict()
    assert snap["gates"] == []
    assert snap["approvals"] == []


# TC-B-M1-13
def test_never_real_honesty_coercion() -> None:
    rauth = default_result_surface_authority()
    row = rauth.seed_factor_vertical_b_sample(
        workspace_id=WS,
        result_id="result-honesty-coerce",
        factor_name="coerce_factor",
        paper_ref="fixture:x",
        paper_digest=PAPER_DIGEST,
        formula_sketch="x = 1",
        universe_note="fixture",
        sample_or_real="real",  # must coerce
    )
    assert row.sample_or_real == "sample"
    pub = row.to_public_dict()
    assert pub["sample_or_real"] == "sample"


# TC-B-M1-14
def test_concurrent_storm_same_action() -> None:
    doc = _bind_doc(client_action_id="act-v7gb-storm")
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


# TC-B-M1-15
def test_follow_sse_vertical_ids() -> None:
    journal = default_vertical_observe_journal()
    # Bind then project via snapshot follow path
    receipt = submit_action(
        _settings(),
        _bind_doc(client_action_id="act-v7gb-follow"),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    tasks = project_workspace_tasks(WS)
    attempts = default_vertical_binding_authority().list_attempts(WS)
    runs = default_vertical_binding_authority().list_runs(WS)
    task_ids = [t["task_id"] for t in tasks]
    attempt_ids = [a.attempt_id for a in attempts]
    run_ids = [r.run_id for r in runs]
    first = journal.take_vertical_ids_if_changed(WS, task_ids, attempt_ids, run_ids)
    assert first is not None
    assert receipt.task_id in first["tasks"]
    second = journal.take_vertical_ids_if_changed(WS, task_ids, attempt_ids, run_ids)
    assert second is None

    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    page = ws.follow(
        ROOT_USER_ID, WorkspaceRef(workspace_id=WS), after=0
    ).to_public_dict()
    assert receipt.task_id in (page.get("tasks") or [])
    assert receipt.attempt_id in (page.get("attempts") or [])
    assert receipt.run_id in (page.get("runs") or [])
    assert any(r.get("result_id") == receipt.result_id for r in page.get("results") or [])


# TC-B-M1-16
def test_a_isolation() -> None:
    a = submit_action(
        _settings(), _options_doc(client_action_id="act-iso-a"), mutation_enabled=True
    )
    b = submit_action(
        _settings(),
        _bind_doc(client_action_id="act-iso-b"),
        mutation_enabled=True,
    )
    assert a.status == "accepted"
    assert b.status == "accepted"
    assert a.task_id != b.task_id
    tasks = project_workspace_tasks(WS)
    assert len(tasks) == 2
    by_id = {t["task_id"]: t for t in tasks}
    assert by_id[a.task_id]["vertical"] == "options_a"
    assert by_id[b.task_id]["vertical"] == "factor_b"
    assert by_id[a.task_id].get("ticker") == "AAPL"
    assert "ticker" not in by_id[b.task_id]
    assert by_id[b.task_id].get("factor_name") == "momentum_20d_reversal"

    results = project_workspace_results(WS)
    assert len(results) == 2
    by_rid = {r["result_id"]: r for r in results}
    assert by_rid[a.result_id]["kind"] == "options_vertical_a"
    assert by_rid[b.result_id]["kind"] == "factor"
    assert "factor_name" not in by_rid[a.result_id] or by_rid[a.result_id].get(
        "factor_name"
    ) is None
    assert by_rid[b.result_id].get("factor_name") == "momentum_20d_reversal"
    assert "ticker" not in by_rid[b.result_id]


# TC-B-M1-17
def test_validation_rejects() -> None:
    base = _bind_doc(client_action_id="act-v7gb-val")
    # empty factor_name
    bad = dict(base)
    bad["factor_name"] = ""
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError)):
        submit_action(_settings(), bad, mutation_enabled=True)
    # non-hex paper_digest
    bad = dict(base)
    bad["client_action_id"] = "act-v7gb-val2"
    bad["paper_digest"] = "zzzz" + ("0" * 60)
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, Exception)):
        try:
            parse_user_action_v1(bad)
        except AgentWorkspaceActionError:
            raise
        submit_action(_settings(), bad, mutation_enabled=True)
    # missing paper_ref
    bad = dict(base)
    bad.pop("paper_ref")
    bad["client_action_id"] = "act-v7gb-val3"
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, KeyError, Exception)):
        try:
            parse_user_action_v1(bad)
        except Exception:
            raise
    # control chars in goal
    bad = dict(base)
    bad["client_action_id"] = "act-v7gb-val4"
    bad["goal_note"] = "bad\x00goal"
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError)):
        submit_action(_settings(), bad, mutation_enabled=True)
    assert project_workspace_tasks(WS) == []
    assert project_workspace_results(WS) == []


# TC-B-M1-18
def test_reject_live_grant_smuggling() -> None:
    base = _bind_doc(client_action_id="act-v7gb-smuggle")
    smuggle = dict(base)
    smuggle["auth_envelope"] = {"grant_id": "x"}
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, Exception)):
        parse_user_action_v1(smuggle)
    smuggle2 = dict(base)
    smuggle2["provider_mode"] = "live_futu_ro"
    with pytest.raises((AgentWorkspaceActionError, SubmissionSagaError, Exception)):
        parse_user_action_v1(smuggle2)
    assert project_workspace_tasks(WS) == []


# TC-B-M1-19
def test_zero_orders_invariant() -> None:
    from pathlib import Path as _Path

    src = (
        _Path(__file__).resolve().parents[1]
        / "src/quant_system/hermes/vertical_binding_authority.py"
    ).read_text()
    # Bind factor path must not invoke order/place/submit trading symbols.
    forbidden = (
        "place_order",
        "submit_order",
        "create_order",
        "account_info",
        "unlock_trade",
    )
    # Only check within bind_factor_vertical_b method body region
    start = src.index("def bind_factor_vertical_b")
    end = src.index("def _release_reservation", start)
    body = src[start:end]
    for tok in forbidden:
        assert tok not in body, f"forbidden token {tok} in bind_factor_vertical_b"
    receipt = submit_action(
        _settings(),
        _bind_doc(client_action_id="act-v7gb-zero"),
        mutation_enabled=True,
    )
    assert receipt.status == "accepted"
    row = project_workspace_results(WS)[0]
    assert "zero_orders" in (row.get("limitations") or [])
    assert "not_tradeable" in (row.get("limitations") or [])


# TC-B-M1-20
def test_conversation_turn_no_task_invention() -> None:
    doc = {
        "schema_version": 1,
        "kind": "conversation.turn",
        "client_action_id": "act-turn-no-factor",
        "workspace": {"workspace_id": WS},
        "session_ref": "session:s-hermetic-b",
        "prompt": "hello without vertical bind",
    }
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
