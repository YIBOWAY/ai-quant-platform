"""L2b-Observe-M1 pure projection + hermetic snapshot/follow when PG available."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from quant_system.hermes.agent_workspace import project_managed_session_public
from quant_system.hermes.workspace_observe import (
    follow_resync_required,
    is_terminal_command_state,
    project_command_public,
    project_event_public,
    public_event_type,
)


def test_public_event_type_map_and_fallback() -> None:
    assert public_event_type(event_type="command_created", to_state="queued") == "command.queued"
    assert (
        public_event_type(event_type="command_delivered", to_state="delivered")
        == "command.delivered"
    )
    assert public_event_type(event_type="weird_custom", to_state="leased") == "command.leased"
    assert public_event_type(event_type="weird_custom", to_state=None) == "command.event"


def test_project_command_public_no_payload() -> None:
    cid = uuid4()
    now = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)
    pub = project_command_public(
        {
            "command_id": cid,
            "kind": "conversation_turn",
            "state": "delivered",
            "version": 4,
            "client_request_id": "act-1",
            "platform_session_id": "wm_abc",
            "hermes_session_id": "run_x",
            "hermes_run_id": "run_x",
            "last_error_code": None,
            "attempt_count": 1,
            "updated_at": now,
            "created_at": now,
        }
    )
    assert pub["command_id"] == str(cid)
    assert pub["client_action_id"] == "act-1"
    assert pub["state"] == "delivered"
    assert pub["hermes_run_id"] == "run_x"
    assert "payload" not in pub
    assert "payload_ref" not in pub
    assert str(pub["updated_at"]).endswith("Z")


def test_project_managed_session_public_is_bounded_and_honest() -> None:
    now = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)
    projection = project_managed_session_public(
        {
            "platform_session_id": "wm_abc",
            "hermes_session_id": "web_" + ("a" * 40),
            "provision_state": "retryable",
            "provision_attempt_count": 2,
            "provision_lease_until": None,
            "provision_next_attempt_at": now,
            "provision_last_error_code": "gateway_timeout",
            "provisioned_at": None,
            "parent_platform_session_id": "wm_parent",
            "fork_point": "message:7",
            "created_at": now,
            "updated_at": now,
        }
    )

    assert projection == {
        "platform_session_id": "wm_abc",
        "session_ref": "session:wm_abc",
        "hermes_session_id": "web_" + ("a" * 40),
        "provision_state": "retryable",
        "web_writable": False,
        "attempt_count": 2,
        "lease_until": None,
        "retry_at": "2026-07-24T12:00:00.000000Z",
        "last_error_code": "gateway_timeout",
        "provisioned_at": None,
        "parent_session_ref": "session:wm_parent",
        "fork_point": "message:7",
        "created_at": "2026-07-24T12:00:00.000000Z",
        "updated_at": "2026-07-24T12:00:00.000000Z",
    }
    # Never disclose the provisioning lease principal/token or immutable policy
    # digest through the browser observation surface.
    assert "lease_owner" not in projection
    assert "lease_token" not in projection
    assert "provider_policy_digest" not in projection


def test_project_managed_session_public_only_marks_ready_as_writable() -> None:
    base = {
        "platform_session_id": "wm_ready",
        "hermes_session_id": "web_" + ("b" * 40),
        "provision_attempt_count": 1,
        "provision_lease_until": None,
        "provision_next_attempt_at": None,
        "provision_last_error_code": None,
        "provisioned_at": datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC),
        "parent_platform_session_id": None,
        "fork_point": None,
        "created_at": datetime(2026, 7, 24, 11, 59, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC),
    }
    for state in ("pending", "leased", "retryable", "failed"):
        row = {
            **base,
            "provision_state": state,
            "provisioned_at": None,
        }
        assert project_managed_session_public(row)["web_writable"] is False

    ready = project_managed_session_public({**base, "provision_state": "ready"})
    assert ready["web_writable"] is True


def test_project_event_public_joins_command_identity() -> None:
    cid = uuid4()
    now = datetime(2026, 7, 22, 12, 0, 1, tzinfo=UTC)
    ev = project_event_public(
        {
            "event_id": 7,
            "command_id": cid,
            "command_version": 2,
            "event_type": "command_leased",
            "from_state": "queued",
            "to_state": "leased",
            "hermes_session_id": None,
            "hermes_run_id": None,
            "error_code": None,
            "occurred_at": now,
        },
        command={
            "client_request_id": "act-9",
            "kind": "conversation_turn",
            "platform_session_id": "wm_1",
        },
    )
    assert ev["event_id"] == 7
    assert ev["type"] == "command.leased"
    assert ev["client_action_id"] == "act-9"
    assert ev["state"] == "leased"
    assert ev["command_id"] == str(cid)


def test_follow_resync_and_terminal() -> None:
    assert follow_resync_required(after_cursor=0, head_event_id=0) is False
    assert follow_resync_required(after_cursor=3, head_event_id=3) is False
    assert follow_resync_required(after_cursor=4, head_event_id=3) is True
    assert follow_resync_required(after_cursor=-1, head_event_id=0) is True
    assert is_terminal_command_state("delivered")
    assert is_terminal_command_state("failed")
    assert not is_terminal_command_state("queued")
    assert not is_terminal_command_state(None)


@pytest.mark.pg
def test_snapshot_commands_are_objects_and_follow_emits_lifecycle() -> None:
    """Requires QS_TEST_DATABASE_URL; reuses agent_workspace fixture helpers."""
    import os

    if not os.environ.get("QS_TEST_DATABASE_URL"):
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")

    from quant_system.hermes.agent_workspace import (
        ActorRef,
        build_platform_agent_workspace,
    )
    from quant_system.hermes.agent_workspace_actions import (
        ConversationTurn,
        WorkspaceRef,
        session_ref,
    )
    from quant_system.hermes.command_ledger import ROOT_USER_ID
    from tests.test_agent_workspace import (
        WORKSPACE_ID,
        _create_action,
        _postgres_settings,
        _prepare,
    )

    settings = _postgres_settings()
    _prepare(settings)
    workspace = build_platform_agent_workspace(settings, mutation_enabled=True)
    actor = ActorRef(owner_user_id=str(ROOT_USER_ID))

    create = workspace.act(actor, _create_action("act-l2b-create"))
    assert create.status == "accepted"
    assert create.command_id is None
    assert create.platform_session_id is not None

    payload_digest = "d" * 64
    turn = workspace.act(
        actor,
        ConversationTurn(
            client_action_id="act-l2b-turn",
            workspace=WorkspaceRef(workspace_id=WORKSPACE_ID),
            managed_session_ref=session_ref(create.platform_session_id),
            payload_ref=f"payload:sha256:{payload_digest}",
            payload_digest=payload_digest,
        ),
    )
    assert turn.status == "accepted"
    assert turn.command_id

    snap = workspace.snapshot(actor, WorkspaceRef(workspace_id=WORKSPACE_ID))
    assert snap.snapshot_workspace_cursor >= 1
    assert snap.commands, "expected at least the create command object"
    cmd0 = snap.commands[0]
    assert isinstance(cmd0, dict)
    assert cmd0["command_id"] == turn.command_id
    assert cmd0["kind"] == "conversation_turn"
    assert cmd0["state"] == "queued"
    assert "client_action_id" in cmd0

    page = workspace.follow(actor, WORKSPACE_ID, after=0)
    assert page.resync_required is False
    assert page.events, "expected command_created event"
    types = [e["type"] for e in page.events]
    assert "command.queued" in types
    assert all("event_id" in e for e in page.events)
    assert page.next_cursor is not None and page.next_cursor >= 1

    # Advance cursor: idle page
    idle = workspace.follow(actor, WORKSPACE_ID, after=page.next_cursor)
    assert idle.resync_required is False
    assert idle.events == ()
    assert idle.next_cursor == page.next_cursor

    # Cursor ahead of head → resync
    ahead = workspace.follow(actor, WORKSPACE_ID, after=page.next_cursor + 10_000)
    assert ahead.resync_required is True
    assert ahead.recovery_action == "resnapshot_workspace"
    assert ahead.events == ()
