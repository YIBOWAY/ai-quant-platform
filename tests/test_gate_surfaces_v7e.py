"""V7e-Gate-Surfaces-M1: hermetic Domain Gate 1/2/3 on snapshot/follow spine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import (
    ConfirmFormulaSource,
    PreparePromotionReview,
    ReviewCandidateCAS,
    WorkspaceRef,
    action_to_document,
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.gate_observe import (
    default_gate_observe_journal,
    gate_authority_health,
    project_gate_public,
    project_workspace_gates,
    reset_default_gate_observe_journal,
)
from quant_system.hermes.gate_surface_authority import (
    default_gate_surface_authority,
    reset_default_gate_surface_authority,
)
from quant_system.hermes.submission_saga import submit_action

WS = "ws-v7e-gates"
DIGEST = "a" * 64
DIGEST_B = "b" * 64
BASE = "c" * 40


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_gate_surface_authority()
    reset_default_gate_observe_journal()
    yield
    reset_default_gate_surface_authority()
    reset_default_gate_observe_journal()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _future_expiry(hours: int = 1) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(hours=hours)
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def test_parse_and_digest_gate_actions_stable() -> None:
    g1 = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-g1",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:t1",
        "reviewed_source_sha256": DIGEST,
        "confirmation_note": "looks good",
    }
    a1 = parse_user_action_v1(g1)
    assert type(a1) is ConfirmFormulaSource
    assert action_to_document(a1) == g1
    d1 = canonical_action_digest(a1)
    assert len(d1) == 64

    g2 = {
        "schema_version": 1,
        "kind": "gate2.candidate.review",
        "client_action_id": "act-g2",
        "workspace": {"workspace_id": WS},
        "candidate_ref": "candidate:c1",
        "expected_digest": DIGEST_B,
        "expected_status": "pending",
        "note": "ship it",
    }
    a2 = parse_user_action_v1(g2)
    assert type(a2) is ReviewCandidateCAS
    assert action_to_document(a2) == g2

    g3 = {
        "schema_version": 1,
        "kind": "gate3.promotion_review.prepare",
        "client_action_id": "act-g3",
        "workspace": {"workspace_id": WS},
        "candidate_ref": "candidate:c2",
        "expected_digest": DIGEST,
        "final_backtest_receipt_ref": "receipt:r1",
        "base_commit": BASE,
    }
    a3 = parse_user_action_v1(g3)
    assert type(a3) is PreparePromotionReview
    assert action_to_document(a3) == g3


def test_gate1_confirm_cas_and_snapshot_projection() -> None:
    auth = default_gate_surface_authority()
    auth.seed_gate1_pending(
        workspace_id=WS,
        gate_id="g1-1",
        task_id="t1",
        reviewed_source_sha256=DIGEST,
        expires_at=_future_expiry(),
    )
    rows = project_workspace_gates(WS)
    assert len(rows) == 1
    assert rows[0]["gate_kind"] == "gate1"
    assert rows[0]["status"] == "pending"
    assert "approval_id" not in rows[0]

    doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-g1-ok",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:t1",
        "reviewed_source_sha256": DIGEST,
        "confirmation_note": "reviewed source matches",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"

    rows2 = project_workspace_gates(WS)
    assert len(rows2) == 1
    assert rows2[0]["status"] == "confirmed"
    assert rows2[0]["note"] == "reviewed source matches"

    # Exact replay accepted
    receipt2 = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt2.status == "accepted"

    # Wrong digest fails closed
    bad = dict(doc)
    bad["client_action_id"] = "act-g1-bad"
    bad["reviewed_source_sha256"] = DIGEST_B
    receipt3 = submit_action(_settings(), bad, mutation_enabled=True)
    assert receipt3.status == "conflict"


def test_gate2_review_cas_no_refetch() -> None:
    auth = default_gate_surface_authority()
    auth.seed_gate2_pending(
        workspace_id=WS,
        gate_id="g2-1",
        candidate_id="cand-1",
        expected_digest=DIGEST_B,
    )
    doc = {
        "schema_version": 1,
        "kind": "gate2.candidate.review",
        "client_action_id": "act-g2-ok",
        "workspace": {"workspace_id": WS},
        "candidate_ref": "candidate:cand-1",
        "expected_digest": DIGEST_B,
        "expected_status": "pending",
        "note": "candidate ok",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    rows = project_workspace_gates(WS)
    assert rows[0]["status"] == "reviewed"


def test_gate3_prepare_only_no_commit_side_effect() -> None:
    auth = default_gate_surface_authority()
    auth.seed_gate3_pending(
        workspace_id=WS,
        gate_id="g3-1",
        candidate_id="cand-p",
        expected_digest=DIGEST,
        final_backtest_receipt_id="rcpt-1",
        base_commit=BASE,
    )
    doc = {
        "schema_version": 1,
        "kind": "gate3.promotion_review.prepare",
        "client_action_id": "act-g3-ok",
        "workspace": {"workspace_id": WS},
        "candidate_ref": "candidate:cand-p",
        "expected_digest": DIGEST,
        "final_backtest_receipt_ref": "receipt:rcpt-1",
        "base_commit": BASE,
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    rows = project_workspace_gates(WS)
    assert rows[0]["status"] == "prepared"
    assert "human_git_commit_required" in str(rows[0].get("note") or "")


def test_mutation_off_fail_closed() -> None:
    auth = default_gate_surface_authority()
    auth.seed_gate1_pending(
        workspace_id=WS,
        gate_id="g1-off",
        task_id="t-off",
        reviewed_source_sha256=DIGEST,
    )
    doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-off",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:t-off",
        "reviewed_source_sha256": DIGEST,
        "confirmation_note": "should not land",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    rows = project_workspace_gates(WS)
    assert rows[0]["status"] == "pending"


def test_snapshot_and_follow_carry_gates_not_approvals() -> None:
    auth = default_gate_surface_authority()
    auth.seed_gate1_pending(
        workspace_id=WS,
        gate_id="g1-snap",
        task_id="t-snap",
        reviewed_source_sha256=DIGEST,
    )
    ws = PlatformAgentWorkspace(_settings(), mutation_enabled=False)
    snap = ws.snapshot(ROOT_USER_ID, WorkspaceRef(workspace_id=WS))
    public = snap.to_public_dict()
    assert "gates" in public
    assert len(public["gates"]) == 1
    assert public["gates"][0]["gate_id"] == "g1-snap"
    # Never stuff gates into approvals
    assert public["approvals"] == []
    health = public["authority_health"]
    assert health["gate_1"] == "ready"
    assert health["gate_2"] == "ready"
    assert health["gate_3"] == "ready"
    assert health["command_approval"] == "ready"

    # Follow may resync when PG off; still must not invent gates into approvals
    # when authorities_ready is false. When ready=false, EventPage has no gates.
    # Direct projector path remains the honest empty/seeded source.
    assert gate_authority_health() == {
        "gate_1": "ready",
        "gate_2": "ready",
        "gate_3": "ready",
    }


def test_gates_fingerprint_changes_on_decide() -> None:
    journal = default_gate_observe_journal()
    auth = default_gate_surface_authority()
    auth.seed_gate2_pending(
        workspace_id=WS,
        gate_id="g2-fp",
        candidate_id="c-fp",
        expected_digest=DIGEST,
    )
    gates1 = project_workspace_gates(WS)
    first = journal.take_gates_if_changed(WS, gates1)
    assert first is not None
    second = journal.take_gates_if_changed(WS, gates1)
    assert second is None  # unchanged fingerprint

    submit_action(
        _settings(),
        {
            "schema_version": 1,
            "kind": "gate2.candidate.review",
            "client_action_id": "act-fp",
            "workspace": {"workspace_id": WS},
            "candidate_ref": "candidate:c-fp",
            "expected_digest": DIGEST,
            "expected_status": "pending",
            "note": "fp change",
        },
        mutation_enabled=True,
    )
    gates2 = project_workspace_gates(WS)
    third = journal.take_gates_if_changed(WS, gates2)
    assert third is not None
    assert third[0]["status"] == "reviewed"


def test_project_gate_public_never_looks_like_approval() -> None:
    row = project_gate_public(
        {
            "gate_id": "x",
            "gate_kind": "gate1",
            "status": "pending",
            "task_id": "t",
            "reviewed_source_sha256": DIGEST,
        }
    )
    assert "approval_id" not in row
    assert row["gate_id"] == "x"
    assert row["kind"] == "gate1.formula_source"


def test_confirm_research_plan_is_not_gate1() -> None:
    """ConfirmResearchPlan remains research kind — never parsed as Gate 1."""
    doc = {
        "schema_version": 1,
        "kind": "research.plan.confirm",
        "client_action_id": "act-plan",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:t1",
        "plan_version": 1,
        "plan_digest": DIGEST,
        "confirmation_note": "plan ok",
    }
    parsed = parse_user_action_v1(doc)
    assert type(parsed).__name__ == "ConfirmResearchPlan"
    assert type(parsed) is not ConfirmFormulaSource


def test_ledger_conflict_after_cas_still_accepted(monkeypatch) -> None:
    """Post-CAS ledger conflict must not lie that the Gate failed (V7c precedent)."""
    from quant_system.hermes import submission_saga as saga

    auth = default_gate_surface_authority()
    auth.seed_gate1_pending(
        workspace_id=WS,
        gate_id="g1-ledger",
        task_id="t-ledger",
        reviewed_source_sha256=DIGEST,
        expires_at=_future_expiry(),
    )

    def _boom(*_a, **_k):
        raise saga.SubmissionSagaError("conflict", "simulated ledger digest conflict")

    # Force ledger path + force create to conflict after CAS.
    monkeypatch.setattr(saga, "_ensure_ready", lambda _settings: True)
    monkeypatch.setattr(saga, "_create_idempotent_command", _boom)

    doc = {
        "schema_version": 1,
        "kind": "gate1.formula_source.confirm",
        "client_action_id": "act-ledger-conflict",
        "workspace": {"workspace_id": WS},
        "task_ref": "task:t-ledger",
        "reviewed_source_sha256": DIGEST,
        "confirmation_note": "human note required",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.command_id is None
    rows = project_workspace_gates(WS)
    assert rows[0]["status"] == "confirmed"
    assert rows[0]["note"] == "human note required"
