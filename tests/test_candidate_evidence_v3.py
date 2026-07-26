from __future__ import annotations

import pytest

from quant_system.hermes.agent_workspace_actions import (
    DecideHermesCommandApproval,
    RequestStop,
    WorkspaceRef,
    canonical_action_digest,
)
from quant_system.hermes.candidate_evidence_v3 import (
    CandidateEvidenceV3Error,
    canonical_approval_control_evidence,
    canonical_stop_control_evidence,
    canonical_transcript_observation,
)


def _messages() -> dict[str, object]:
    return {
        "session_id": "web_session",
        "omitted_message_count": 0,
        "data": [
            {
                "id": "1",
                "role": "user",
                "content": "first",
                "timestamp": "2026-07-24T01:00:00Z",
                "fork_point": "message:1",
            },
            {
                "id": "2",
                "role": "assistant",
                "content": "answer one",
                "timestamp": "2026-07-24T01:00:01Z",
                "fork_point": "message:2",
            },
            {
                "id": "3",
                "role": "user",
                "content": "second",
                "timestamp": "2026-07-24T01:00:02Z",
                "fork_point": "message:3",
            },
            {
                "id": "4",
                "role": "assistant",
                "content": "answer two",
                "timestamp": "2026-07-24T01:00:03Z",
                "fork_point": "message:4",
            },
        ],
    }


def test_transcript_digest_binds_exact_canonical_messages() -> None:
    first, count, roles = canonical_transcript_observation(
        _messages(),
        expected_session_id="web_session",
    )
    repeated, _, _ = canonical_transcript_observation(
        _messages(),
        expected_session_id="web_session",
    )
    changed = _messages()
    changed["data"][3]["content"] = "different answer"  # type: ignore[index]
    changed_digest, _, _ = canonical_transcript_observation(
        changed,
        expected_session_id="web_session",
    )

    assert first == repeated
    assert first != changed_digest
    assert count == 4
    assert roles == {"assistant": 2, "user": 2}


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update({"session_id": "substituted"}),
        lambda value: value.update({"omitted_message_count": 1}),
        lambda value: value["data"].append(value["data"][0]),  # type: ignore[index,union-attr]
        lambda value: value["data"][0].update({"role": "tool"}),  # type: ignore[index]
        lambda value: value["data"][0].update({"content": "   "}),  # type: ignore[index]
    ),
)
def test_transcript_digest_rejects_substitution_truncation_and_bad_rows(
    mutation,
) -> None:
    document = _messages()
    mutation(document)

    with pytest.raises(CandidateEvidenceV3Error):
        canonical_transcript_observation(
            document,
            expected_session_id="web_session",
        )


def _event(
    seq: int,
    kind: str,
    *,
    run_id: str = "run-candidate-1",
    **values: object,
) -> dict[str, object]:
    return {
        "seq": seq,
        "event": kind,
        "event_id": f"event-{seq}",
        "run_id": run_id,
        "timestamp": 4_070_908_700.0 + seq,
        **values,
    }


def test_approval_control_evidence_binds_platform_digest_to_exact_hermes_cas() -> None:
    action = DecideHermesCommandApproval(
        client_action_id="approve-candidate-1",
        workspace=WorkspaceRef("workspace-root"),
        approval_ref="approval:challenge-1",
        run_ref="run:run-candidate-1",
        command_digest="a" * 64,
        expected_status="pending",
        expected_expires_at="2099-01-01T00:00:00.000000Z",
        decision="allow_once",
    )
    identity = {
        "challenge_id": "challenge-1",
        "approval_id": "approval-core-1",
        "action_digest": "a" * 64,
    }
    events = (
        _event(
            1,
            "approval.request",
            **identity,
            expires_at=4_070_908_800.0,
            choices=["once", "deny"],
        ),
        _event(2, "approval.decision_recorded", **identity, choice="once"),
        _event(
            3,
            "approval.release_committed",
            **identity,
            choice="once",
            decision_status="committed",
            waiter_signal_status="unknown",
        ),
        _event(
            4,
            "approval.signalled",
            **identity,
            choice="once",
            decision_status="committed",
            waiter_signal_status="confirmed",
        ),
        _event(5, "run.completed"),
    )

    evidence = canonical_approval_control_evidence(
        events,
        run_id="run-candidate-1",
        workspace_id="workspace-root",
        control_command_id="control-approval-1",
        client_action_id="approve-candidate-1",
        canonical_request_digest=canonical_action_digest(action),
    )

    assert evidence["decision"] == "allow_once"
    assert evidence["choice"] == "once"
    assert evidence["challenge_id"] == "challenge-1"
    assert evidence["waiter_signal_status"] == "confirmed"
    assert evidence["event_ids"] == [
        "event-1",
        "event-2",
        "event-3",
        "event-4",
    ]


@pytest.mark.parametrize(
    "mutation",
    (
        lambda events: events[2].update({"action_digest": "b" * 64}),
        lambda events: events[3].update({"waiter_signal_status": "unknown"}),
        lambda events: events.pop(2),
        lambda events: events[1].update({"seq": 3}),
    ),
)
def test_approval_control_evidence_rejects_substitution_and_incomplete_release(
    mutation,
) -> None:
    action = DecideHermesCommandApproval(
        client_action_id="approve-candidate-1",
        workspace=WorkspaceRef("workspace-root"),
        approval_ref="approval:challenge-1",
        run_ref="run:run-candidate-1",
        command_digest="a" * 64,
        expected_status="pending",
        expected_expires_at="2099-01-01T00:00:00.000000Z",
        decision="deny",
    )
    identity = {
        "challenge_id": "challenge-1",
        "approval_id": "approval-core-1",
        "action_digest": "a" * 64,
    }
    events = [
        _event(
            1,
            "approval.request",
            **identity,
            expires_at=4_070_908_800.0,
            choices=["once", "deny"],
        ),
        _event(2, "approval.decision_recorded", **identity, choice="deny"),
        _event(
            3,
            "approval.release_committed",
            **identity,
            choice="deny",
            decision_status="committed",
            waiter_signal_status="unknown",
        ),
        _event(
            4,
            "approval.signalled",
            **identity,
            choice="deny",
            decision_status="committed",
            waiter_signal_status="confirmed",
        ),
    ]
    mutation(events)

    with pytest.raises(CandidateEvidenceV3Error):
        canonical_approval_control_evidence(
            tuple(events),
            run_id="run-candidate-1",
            workspace_id="workspace-root",
            control_command_id="control-approval-1",
            client_action_id="approve-candidate-1",
            canonical_request_digest=canonical_action_digest(action),
        )


def test_stop_control_evidence_binds_request_to_cancelled_run() -> None:
    action = RequestStop(
        client_action_id="stop-candidate-1",
        workspace=WorkspaceRef("workspace-root"),
        run_ref="run:run-candidate-1",
        task_ref=None,
        attempt_ref=None,
        platform_job_ref=None,
    )
    events = (
        _event(1, "run.started"),
        _event(2, "run.stop_requested"),
        _event(3, "run.cancelled", reason="interrupted"),
    )

    evidence = canonical_stop_control_evidence(
        events,
        run_status={"object": "hermes.run", "run_id": "run-candidate-1", "status": "stopped"},
        run_id="run-candidate-1",
        workspace_id="workspace-root",
        control_command_id="control-stop-1",
        client_action_id="stop-candidate-1",
        canonical_request_digest=canonical_action_digest(action),
    )

    assert evidence["status"] == "stopped"
    assert evidence["stop_requested_event_id"] == "event-2"
    assert evidence["terminal_event_id"] == "event-3"
    assert evidence["idempotent_recovery_proven"] is True


def test_stop_control_evidence_rejects_running_or_non_cancelled_projection() -> None:
    action = RequestStop(
        client_action_id="stop-candidate-1",
        workspace=WorkspaceRef("workspace-root"),
        run_ref="run:run-candidate-1",
        task_ref=None,
        attempt_ref=None,
        platform_job_ref=None,
    )
    events = (
        _event(1, "run.started"),
        _event(2, "run.stop_requested"),
        _event(3, "run.completed"),
    )

    with pytest.raises(CandidateEvidenceV3Error):
        canonical_stop_control_evidence(
            events,
            run_status={
                "object": "hermes.run",
                "run_id": "run-candidate-1",
                "status": "running",
            },
            run_id="run-candidate-1",
            workspace_id="workspace-root",
            control_command_id="control-stop-1",
            client_action_id="stop-candidate-1",
            canonical_request_digest=canonical_action_digest(action),
        )
