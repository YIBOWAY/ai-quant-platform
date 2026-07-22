"""V7a-Hermes-Approval-Decide-M1: hermetic authority + typed action + saga."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    DecideHermesCommandApproval,
    WorkspaceRef,
    action_to_document,
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.approval_release_port import (
    default_approval_release_adapter,
    project_pending_challenge,
    reset_default_approval_release_adapter,
)
from quant_system.hermes.command_approval_authority import (
    CommandApprovalAuthority,
    CommandApprovalAuthorityError,
    default_command_approval_authority,
    reset_default_command_approval_authority,
)
from quant_system.hermes.submission_saga import submit_action as _submit_action


def submit_action(*args, **kwargs):
    """Exercise the explicitly hermetic M1 adapter in this contract suite."""
    kwargs.setdefault("allow_hermetic_authorities", True)
    return _submit_action(*args, **kwargs)

DIGEST = "e" * 64
WS = "ws-v7a-decide"


@pytest.fixture(autouse=True)
def _reset_authority() -> None:
    reset_default_command_approval_authority()
    reset_default_approval_release_adapter()
    yield
    reset_default_command_approval_authority()
    reset_default_approval_release_adapter()


def _future_expiry(hours: int = 2) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _past_expiry() -> str:
    return (datetime.now(UTC) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def test_decide_action_round_trip_and_rejects_always_allow() -> None:
    exp = "2026-07-16T12:30:40.123456Z"
    action = DecideHermesCommandApproval(
        client_action_id="action:approval-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        approval_ref="approval:challenge.1",
        run_ref="run:hermes.1",
        command_digest=DIGEST,
        expected_status="pending",
        expected_expires_at="2026-07-16T20:30:40.123456+08:00",
        decision="allow_once",
    )
    assert action.expected_expires_at == exp
    doc = action_to_document(action)
    assert doc["kind"] == "hermes.command_approval.decide"
    assert doc["decision"] == "allow_once"
    assert parse_user_action_v1(doc) == action

    for bad in ("allow", "always", "allow_permanently", "allow_always", ""):
        with pytest.raises(AgentWorkspaceActionError):
            DecideHermesCommandApproval(
                client_action_id="action:bad",
                workspace=WorkspaceRef(workspace_id="workspace:alpha"),
                approval_ref="approval:challenge.1",
                run_ref="run:hermes.1",
                command_digest=DIGEST,
                expected_status="pending",
                expected_expires_at=exp,
                decision=bad,
            )


def test_authority_seed_list_decide_idempotent_and_single_use() -> None:
    auth = CommandApprovalAuthority()
    exp = _future_expiry()
    auth.seed_pending(
        workspace_id=WS,
        approval_id="challenge.1",
        run_id="hermes.1",
        command_digest=DIGEST,
        expires_at=exp,
    )
    pending = auth.list_pending(WS)
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert pending[0]["digest"] == DIGEST

    decided = auth.decide(
        workspace_id=WS,
        approval_ref="approval:challenge.1",
        run_ref="run:hermes.1",
        command_digest=DIGEST,
        expected_status="pending",
        expected_expires_at=exp,
        decision="allow_once",
        client_action_id="act-1",
        action_digest="a" * 64,
    )
    assert decided.status == "allowed_once"
    assert auth.list_pending(WS) == []

    # Exact same action is idempotent.
    again = auth.decide(
        workspace_id=WS,
        approval_ref="approval:challenge.1",
        run_ref="run:hermes.1",
        command_digest=DIGEST,
        expected_status="pending",
        expected_expires_at=exp,
        decision="allow_once",
        client_action_id="act-1",
        action_digest="a" * 64,
    )
    assert again.status == "allowed_once"

    # Different client / decision after consume fails closed.
    with pytest.raises(CommandApprovalAuthorityError) as exc:
        auth.decide(
            workspace_id=WS,
            approval_ref="approval:challenge.1",
            run_ref="run:hermes.1",
            command_digest=DIGEST,
            expected_status="pending",
            expected_expires_at=exp,
            decision="deny",
            client_action_id="act-2",
            action_digest="b" * 64,
        )
    assert exc.value.code == "conflict"
    assert "already_decided" in exc.value.message


def test_authority_fail_closed_matrix() -> None:
    auth = default_command_approval_authority()
    exp = _future_expiry()
    auth.seed_pending(
        workspace_id=WS,
        approval_id="challenge.x",
        run_id="hermes.x",
        command_digest=DIGEST,
        expires_at=exp,
    )

    # digest mismatch
    with pytest.raises(CommandApprovalAuthorityError) as exc:
        auth.decide(
            workspace_id=WS,
            approval_ref="approval:challenge.x",
            run_ref="run:hermes.x",
            command_digest="f" * 64,
            expected_status="pending",
            expected_expires_at=exp,
            decision="deny",
            client_action_id="a1",
            action_digest="c" * 64,
        )
    assert "digest_mismatch" in exc.value.message

    # run mismatch
    with pytest.raises(CommandApprovalAuthorityError) as exc:
        auth.decide(
            workspace_id=WS,
            approval_ref="approval:challenge.x",
            run_ref="run:other",
            command_digest=DIGEST,
            expected_status="pending",
            expected_expires_at=exp,
            decision="deny",
            client_action_id="a2",
            action_digest="d" * 64,
        )
    assert "run_mismatch" in exc.value.message

    # expires_at mismatch
    with pytest.raises(CommandApprovalAuthorityError) as exc:
        auth.decide(
            workspace_id=WS,
            approval_ref="approval:challenge.x",
            run_ref="run:hermes.x",
            command_digest=DIGEST,
            expected_status="pending",
            expected_expires_at=_future_expiry(9),
            decision="deny",
            client_action_id="a3",
            action_digest="e" * 64,
        )
    assert "expires_at_mismatch" in exc.value.message

    # unknown id
    with pytest.raises(CommandApprovalAuthorityError) as exc:
        auth.decide(
            workspace_id=WS,
            approval_ref="approval:missing",
            run_ref="run:hermes.x",
            command_digest=DIGEST,
            expected_status="pending",
            expected_expires_at=exp,
            decision="deny",
            client_action_id="a4",
            action_digest="1" * 64,
        )
    assert "not_found" in exc.value.message

    # expired
    auth.seed_pending(
        workspace_id=WS,
        approval_id="challenge.old",
        run_id="hermes.old",
        command_digest=DIGEST,
        expires_at=_past_expiry(),
    )
    with pytest.raises(CommandApprovalAuthorityError) as exc:
        auth.decide(
            workspace_id=WS,
            approval_ref="approval:challenge.old",
            run_ref="run:hermes.old",
            command_digest=DIGEST,
            expected_status="pending",
            expected_expires_at=_past_expiry(),
            decision="allow_once",
            client_action_id="a5",
            action_digest="2" * 64,
        )
    assert "expired" in exc.value.message
    # list_pending drops expired
    assert all(r["approval_id"] != "challenge.old" for r in auth.list_pending(WS))


def test_submit_action_decide_mutation_gate_and_accept(tmp_path=None) -> None:
    """Saga path without requiring PG: mutation OFF unavailable; ON accepts CAS+release."""
    from quant_system.config.settings import DatabaseSettings, Settings

    settings = Settings(
        database=DatabaseSettings(enabled=False, auto_migrate=False),
    )
    # Dual-seed authority + release port so V7b respond_approval can commit.
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.saga",
        command_digest=DIGEST,
        approval_id="challenge.saga",
        ttl_seconds=7200.0,
    )
    exp = str(row["expires_at"])
    doc = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "act-saga-1",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.saga",
        "run_ref": "run:hermes.saga",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": exp,
        "decision": "deny",
    }

    off = submit_action(settings, doc, mutation_enabled=False)
    assert off.status == "unavailable"
    assert off.reason_code == "authenticated_mutation_bff_unavailable"
    # Challenge still pending when mutation OFF (no side effect).
    assert len(default_command_approval_authority().list_pending(WS)) == 1
    assert default_approval_release_adapter().respond_calls == 0

    on = submit_action(settings, doc, mutation_enabled=True)
    assert on.status == "accepted"
    assert on.reason_code is None
    assert default_command_approval_authority().list_pending(WS) == []
    events = default_approval_release_adapter().events("hermes.saga")
    assert [e["event_type"] for e in events] == [
        "approval.responded",
        "approval.release_committed",
        "approval.signalled",
    ]
    assert events[0]["payload"]["choice"] == "deny"

    # Replay same action id+digest is accepted (idempotent release too).
    replay = submit_action(settings, doc, mutation_enabled=True)
    assert replay.status == "accepted"
    # No second signalled set.
    events2 = default_approval_release_adapter().events("hermes.saga")
    assert len(events2) == 3

    # Double-click different decision after consume → conflict.
    other = dict(doc, client_action_id="act-saga-2", decision="allow_once")
    conflict = submit_action(settings, other, mutation_enabled=True)
    assert conflict.status == "conflict"
    assert "already_decided" in (conflict.reason_code or "")


def test_canonical_digest_stable_for_decide() -> None:
    a = DecideHermesCommandApproval(
        client_action_id="action:test-1",
        workspace=WorkspaceRef(workspace_id="workspace:alpha"),
        approval_ref="approval:challenge.1",
        run_ref="run:hermes.1",
        command_digest=DIGEST,
        expected_status="pending",
        expected_expires_at="2026-07-16T20:30:40+08:00",
        decision="deny",
    )
    d1 = canonical_action_digest(a)
    d2 = canonical_action_digest(parse_user_action_v1(action_to_document(a)))
    assert d1 == d2
    assert len(d1) == 64


def test_snapshot_projects_pending_approvals_when_seeded() -> None:
    """Workspace snapshot surfaces hermetic pending rows + ready health."""
    from quant_system.config.settings import DatabaseSettings, Settings
    from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
    from quant_system.hermes.command_ledger import ROOT_USER_ID

    settings = Settings(
        database=DatabaseSettings(enabled=False, auto_migrate=False),
    )
    exp = _future_expiry()
    default_command_approval_authority().seed_pending(
        workspace_id="ws-local-main",
        approval_id="challenge.snap",
        run_id="hermes.snap",
        command_digest=DIGEST,
        expires_at=exp,
        command_id="cmd-1",
    )
    ws = PlatformAgentWorkspace(
        settings,
        mutation_enabled=True,
        hermetic_authorities=True,
    )
    snap = ws.snapshot(
        actor={"owner_user_id": str(ROOT_USER_ID)},
        workspace={"workspace_id": "ws-local-main"},
    )
    body = snap.to_public_dict() if hasattr(snap, "to_public_dict") else None
    if body is None:
        # dataclass public shape
        assert snap.authority_health["command_approval"] == "ready"
        assert snap.mutation_enabled is True
        assert len(snap.approvals) == 1
        row = snap.approvals[0]
        assert row["approval_id"] == "challenge.snap"
        assert row["run_id"] == "hermes.snap"
        assert row["digest"] == DIGEST
        assert row["status"] == "pending"
    else:
        assert body["authority_health"]["command_approval"] == "hermetic"
        assert len(body["approvals"]) == 1
