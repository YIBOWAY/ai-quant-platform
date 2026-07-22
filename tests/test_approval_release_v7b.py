"""V7b-Hermes-Approval-Release-M1: hermetic raise → decide → respond_approval."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.approval_release_port import (
    ApprovalReleaseError,
    FakeHermesApprovalReleaseAdapter,
    default_approval_release_adapter,
    map_decision_to_release_choice,
    project_pending_challenge,
    reset_default_approval_release_adapter,
)
from quant_system.hermes.command_approval_authority import (
    default_command_approval_authority,
    reset_default_command_approval_authority,
)
from quant_system.hermes.submission_saga import submit_action

DIGEST = "a" * 64
WS = "ws-v7b-release"


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_command_approval_authority()
    reset_default_approval_release_adapter()
    yield
    reset_default_command_approval_authority()
    reset_default_approval_release_adapter()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def test_map_decision_to_release_choice() -> None:
    assert map_decision_to_release_choice("allow_once") == "once"
    assert map_decision_to_release_choice("deny") == "deny"
    with pytest.raises(ApprovalReleaseError) as exc:
        map_decision_to_release_choice("always_allow")
    assert exc.value.code == "validation"
    with pytest.raises(ApprovalReleaseError):
        map_decision_to_release_choice("allow")


def test_raise_and_project_pending_appears_in_list() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.1",
        command_digest=DIGEST,
        approval_id="challenge.v7b.1",
        command_id="cmd-v7b-1",
        ttl_seconds=600.0,
    )
    assert row["approval_id"] == "challenge.v7b.1"
    assert row["run_id"] == "hermes.v7b.1"
    assert row["status"] == "pending"
    assert row["digest"] == DIGEST
    pending = default_command_approval_authority().list_pending(WS)
    assert len(pending) == 1
    grants = default_approval_release_adapter().list_pending_grants()
    assert len(grants) == 1
    assert grants[0]["challenge_id"] == "challenge.v7b.1"


def test_allow_once_decide_releases_and_signals_once() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.allow",
        command_digest=DIGEST,
        approval_id="challenge.allow",
        ttl_seconds=3600.0,
    )
    exp = str(row["expires_at"])
    doc = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "act-v7b-allow",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.allow",
        "run_ref": "run:hermes.v7b.allow",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": exp,
        "decision": "allow_once",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.run_id == "hermes.v7b.allow"
    assert default_command_approval_authority().list_pending(WS) == []
    adapter = default_approval_release_adapter()
    assert adapter.respond_calls == 1
    events = adapter.events("hermes.v7b.allow")
    assert [e["event_type"] for e in events] == [
        "approval.responded",
        "approval.release_committed",
        "approval.signalled",
    ]
    assert events[-1]["payload"]["choice"] == "once"
    assert events[-1]["payload"]["waiter_signal_status"] == "confirmed"
    assert adapter.list_pending_grants() == []


def test_deny_decide_releases_with_choice_deny() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.deny",
        command_digest=DIGEST,
        approval_id="challenge.deny",
        ttl_seconds=3600.0,
    )
    exp = str(row["expires_at"])
    doc = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "act-v7b-deny",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.deny",
        "run_ref": "run:hermes.v7b.deny",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": exp,
        "decision": "deny",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "accepted"
    events = default_approval_release_adapter().events("hermes.v7b.deny")
    assert events[-1]["payload"]["choice"] == "deny"


def test_idempotent_replay_does_not_double_signal() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.idem",
        command_digest=DIGEST,
        approval_id="challenge.idem",
        ttl_seconds=3600.0,
    )
    exp = str(row["expires_at"])
    doc = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "act-v7b-idem",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.idem",
        "run_ref": "run:hermes.v7b.idem",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": exp,
        "decision": "allow_once",
    }
    first = submit_action(_settings(), doc, mutation_enabled=True)
    second = submit_action(_settings(), doc, mutation_enabled=True)
    assert first.status == "accepted"
    assert second.status == "accepted"
    adapter = default_approval_release_adapter()
    assert adapter.respond_calls == 2  # second is idempotent replay call
    events = adapter.events("hermes.v7b.idem")
    assert len([e for e in events if e["event_type"] == "approval.signalled"]) == 1


def test_second_decision_after_consume_is_conflict_no_extra_signal() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.once",
        command_digest=DIGEST,
        approval_id="challenge.once",
        ttl_seconds=3600.0,
    )
    exp = str(row["expires_at"])
    base = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.once",
        "run_ref": "run:hermes.v7b.once",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": exp,
    }
    first = submit_action(
        _settings(),
        {**base, "client_action_id": "act-1", "decision": "allow_once"},
        mutation_enabled=True,
    )
    assert first.status == "accepted"
    conflict = submit_action(
        _settings(),
        {**base, "client_action_id": "act-2", "decision": "deny"},
        mutation_enabled=True,
    )
    assert conflict.status == "conflict"
    assert "already_decided" in (conflict.reason_code or "")
    events = default_approval_release_adapter().events("hermes.v7b.once")
    assert len([e for e in events if e["event_type"] == "approval.signalled"]) == 1


def test_digest_mismatch_does_not_release() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.mismatch",
        command_digest=DIGEST,
        approval_id="challenge.mismatch",
        ttl_seconds=3600.0,
    )
    exp = str(row["expires_at"])
    doc = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "act-mismatch",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.mismatch",
        "run_ref": "run:hermes.v7b.mismatch",
        "command_digest": "b" * 64,
        "expected_status": "pending",
        "expected_expires_at": exp,
        "decision": "deny",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "conflict"
    assert "digest_mismatch" in (receipt.reason_code or "")
    assert len(default_command_approval_authority().list_pending(WS)) == 1
    assert default_approval_release_adapter().respond_calls == 0
    assert default_approval_release_adapter().events("hermes.v7b.mismatch") == []


def test_mutation_off_no_release_side_effect() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.off",
        command_digest=DIGEST,
        approval_id="challenge.off",
        ttl_seconds=3600.0,
    )
    exp = str(row["expires_at"])
    doc = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "act-off",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.off",
        "run_ref": "run:hermes.v7b.off",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": exp,
        "decision": "allow_once",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert len(default_command_approval_authority().list_pending(WS)) == 1
    assert default_approval_release_adapter().respond_calls == 0


def test_release_fault_after_cas_returns_reconciling() -> None:
    row = project_pending_challenge(
        workspace_id=WS,
        run_id="hermes.v7b.stale",
        command_digest=DIGEST,
        approval_id="challenge.stale",
        ttl_seconds=3600.0,
    )
    exp = str(row["expires_at"])
    adapter = default_approval_release_adapter()
    adapter.next_fault = "stale"
    doc = {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": "act-stale",
        "workspace": {"workspace_id": WS},
        "approval_ref": "approval:challenge.stale",
        "run_ref": "run:hermes.v7b.stale",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": exp,
        "decision": "allow_once",
    }
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    assert receipt.status == "reconciling"
    assert receipt.reason_code == "approval_challenge_invalid"
    # CAS already committed — pending must stay empty (no resurrect).
    assert default_command_approval_authority().list_pending(WS) == []
    # No signalled event because release failed closed.
    assert adapter.events("hermes.v7b.stale") == []


def test_adapter_rejects_always_allow_choice() -> None:
    adapter = FakeHermesApprovalReleaseAdapter()
    adapter.raise_approval(
        "hermes.x",
        action_digest=DIGEST,
        challenge_id="ch.x",
    )
    with pytest.raises(ApprovalReleaseError) as exc:
        adapter.respond_approval(
            "hermes.x",
            choice="always",
            challenge_id="ch.x",
            action_digest=DIGEST,
        )
    assert exc.value.code == "validation"


def test_adapter_digest_mismatch_does_not_consume() -> None:
    adapter = FakeHermesApprovalReleaseAdapter()
    adapter.raise_approval(
        "hermes.y",
        action_digest=DIGEST,
        challenge_id="ch.y",
        ttl_seconds=600.0,
    )
    with pytest.raises(ApprovalReleaseError) as exc:
        adapter.respond_approval(
            "hermes.y",
            choice="once",
            challenge_id="ch.y",
            action_digest="c" * 64,
        )
    assert exc.value.code == "approval_challenge_invalid"
    assert len(adapter.list_pending_grants()) == 1
    # Correct digest still works after failed mismatch.
    result = adapter.respond_approval(
        "hermes.y",
        choice="deny",
        challenge_id="ch.y",
        action_digest=DIGEST,
    )
    assert result.idempotent_replay is False
    assert result.choice == "deny"
    assert adapter.list_pending_grants() == []
