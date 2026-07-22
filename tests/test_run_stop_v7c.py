"""V7c-Hermes-Stop-M1: hermetic Run-scoped stop + layered receipt."""

from __future__ import annotations

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    RequestStop,
    WorkspaceRef,
    canonical_action_digest,
    parse_user_action_v1,
)
from quant_system.hermes.run_stop_port import (
    FakeHermesRunStopAdapter,
    RunStopError,
    build_layered_stop_receipt,
    classify_optional_layer,
    default_run_stop_adapter,
    reset_default_run_stop_adapter,
    strip_run_ref,
)
from quant_system.hermes.submission_saga import (
    submit_action as _submit_action,
)
from quant_system.hermes.submission_saga import (
    submit_stop_run_request,
)


def submit_action(*args, **kwargs):
    """Exercise the explicitly hermetic M1 adapter in this contract suite."""
    kwargs.setdefault("allow_hermetic_authorities", True)
    return _submit_action(*args, **kwargs)

WS = "ws-v7c-stop"
RUN_ID = "hermes.v7c.1"
RUN_REF = f"run:{RUN_ID}"


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_run_stop_adapter()
    yield
    reset_default_run_stop_adapter()


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _stop_doc(
    *,
    client_action_id: str = "act-v7c-stop-1",
    run_ref: str = RUN_REF,
    task_ref=None,
    attempt_ref=None,
    platform_job_ref=None,
    workspace_id: str = WS,
) -> dict:
    return {
        "schema_version": 1,
        "kind": "run.stop.request",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": workspace_id},
        "run_ref": run_ref,
        "task_ref": task_ref,
        "attempt_ref": attempt_ref,
        "platform_job_ref": platform_job_ref,
    }


def test_parse_request_stop_round_trip() -> None:
    doc = _stop_doc(
        task_ref="task:research.1",
        attempt_ref=None,
        platform_job_ref=None,
    )
    action = parse_user_action_v1(doc)
    assert type(action) is RequestStop
    assert action.run_ref == RUN_REF
    assert action.task_ref == "task:research.1"
    assert action.attempt_ref is None
    assert action.platform_job_ref is None
    digest = canonical_action_digest(action)
    again = parse_user_action_v1(doc)
    assert canonical_action_digest(again) == digest


def test_parse_request_stop_rejects_bad_refs() -> None:
    with pytest.raises((AgentWorkspaceActionError, TypeError, ValueError)):
        parse_user_action_v1(_stop_doc(run_ref="run:"))
    with pytest.raises((AgentWorkspaceActionError, TypeError, ValueError)):
        parse_user_action_v1(_stop_doc(run_ref="task:hermes.1"))
    with pytest.raises((AgentWorkspaceActionError, TypeError, ValueError)):
        parse_user_action_v1(_stop_doc(attempt_ref="run:wrong.1"))
    with pytest.raises((AgentWorkspaceActionError, TypeError, ValueError)):
        parse_user_action_v1(_stop_doc(platform_job_ref="job:"))


def test_strip_run_ref_and_classify_layers() -> None:
    assert strip_run_ref(RUN_REF) == RUN_ID
    with pytest.raises(RunStopError):
        strip_run_ref("task:x")
    assert classify_optional_layer(None) == "not_applicable"
    assert classify_optional_layer("attempt:a.1") == "unknown"


def test_adapter_stop_running_to_stopped_once() -> None:
    adapter = FakeHermesRunStopAdapter()
    adapter.ensure_run(RUN_ID, status="running")
    first = adapter.stop(RUN_ID)
    assert first.status == "stopped"
    assert first.idempotent_replay is False
    events = adapter.events(RUN_ID)
    assert [e["event_type"] for e in events] == ["run.cancelled"]
    second = adapter.stop(RUN_ID)
    assert second.status == "stopped"
    assert second.idempotent_replay is True
    # No second cancellation event on terminal replay.
    assert len(adapter.events(RUN_ID)) == 1


def test_adapter_already_terminal_honest() -> None:
    adapter = FakeHermesRunStopAdapter()
    for terminal in ("succeeded", "failed", "stopped"):
        rid = f"hermes.term.{terminal}"
        adapter.ensure_run(rid, status=terminal)
        result = adapter.stop(rid)
        assert result.status == terminal
        assert result.idempotent_replay is True
        assert adapter.events(rid) == []


def test_adapter_partial_stop_commits_then_raises() -> None:
    adapter = FakeHermesRunStopAdapter()
    adapter.ensure_run(RUN_ID, status="running")
    adapter.next_fault = "partial_stop"
    with pytest.raises(RunStopError) as exc:
        adapter.stop(RUN_ID)
    assert exc.value.code == "transport_error"
    # Commit landed despite lost ack.
    assert adapter.get_status(RUN_ID) == "stopped"
    assert [e["event_type"] for e in adapter.events(RUN_ID)] == ["run.cancelled"]
    # Replay heals as already-terminal.
    healed = adapter.stop(RUN_ID)
    assert healed.status == "stopped"
    assert healed.idempotent_replay is True


def test_build_layered_receipt_run_only_stopped() -> None:
    from quant_system.hermes.run_stop_port import StopResult

    layers = build_layered_stop_receipt(
        stop=StopResult(run_id=RUN_ID, status="stopped"),
        hermes_run_layer="confirmed",
        attempt_ref=None,
        platform_job_ref=None,
    )
    assert layers.hermes_run == "confirmed"
    assert layers.hqa_attempt == "not_applicable"
    assert layers.platform_job == "not_applicable"
    assert layers.overall == "stopped"


def test_build_layered_receipt_unknown_attempt_keeps_reconciling() -> None:
    from quant_system.hermes.run_stop_port import StopResult

    layers = build_layered_stop_receipt(
        stop=StopResult(run_id=RUN_ID, status="stopped"),
        hermes_run_layer="confirmed",
        attempt_ref="attempt:research.1",
        platform_job_ref=None,
    )
    assert layers.hermes_run == "confirmed"
    assert layers.hqa_attempt == "unknown"
    assert layers.platform_job == "not_applicable"
    assert layers.overall == "reconciling"


def test_saga_mutation_off_unavailable() -> None:
    default_run_stop_adapter().ensure_run(RUN_ID, status="running")
    receipt = submit_action(_settings(), _stop_doc(), mutation_enabled=False)
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "authenticated_mutation_bff_unavailable"
    assert default_run_stop_adapter().stop_calls == 0
    assert default_run_stop_adapter().get_status(RUN_ID) == "running"


def test_saga_stop_running_accepted_with_layers() -> None:
    default_run_stop_adapter().ensure_run(RUN_ID, status="running")
    receipt = submit_action(_settings(), _stop_doc(), mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.run_id == RUN_ID
    assert receipt.stop_layers is not None
    assert receipt.stop_layers["hermes_run"] == "confirmed"
    assert receipt.stop_layers["hqa_attempt"] == "not_applicable"
    assert receipt.stop_layers["platform_job"] == "not_applicable"
    assert receipt.stop_layers["overall"] == "stopped"
    assert receipt.stop_layers["run_status"] == "stopped"
    assert receipt.stop_layers["idempotent_replay"] is False
    public = receipt.to_public_dict()
    assert public["stop_layers"]["overall"] == "stopped"
    assert default_run_stop_adapter().get_status(RUN_ID) == "stopped"
    events = default_run_stop_adapter().events(RUN_ID)
    assert [e["event_type"] for e in events] == ["run.cancelled"]


def test_saga_already_terminal_accepted_honest() -> None:
    default_run_stop_adapter().ensure_run(RUN_ID, status="succeeded")
    receipt = submit_action(_settings(), _stop_doc(), mutation_enabled=True)
    assert receipt.status == "accepted"
    assert receipt.stop_layers is not None
    assert receipt.stop_layers["hermes_run"] == "already_terminal"
    assert receipt.stop_layers["overall"] == "already_terminal"
    assert receipt.stop_layers["run_status"] == "succeeded"
    assert receipt.stop_layers["idempotent_replay"] is True
    # Must not append run.cancelled on already-succeeded.
    assert default_run_stop_adapter().events(RUN_ID) == []


def test_saga_idempotent_double_stop_same_action() -> None:
    default_run_stop_adapter().ensure_run(RUN_ID, status="running")
    doc = _stop_doc(client_action_id="act-v7c-idem")
    first = submit_action(_settings(), doc, mutation_enabled=True)
    second = submit_action(_settings(), doc, mutation_enabled=True)
    assert first.status == "accepted"
    assert second.status == "accepted"
    assert second.stop_layers is not None
    assert second.stop_layers["idempotent_replay"] is True
    assert second.stop_layers["hermes_run"] == "already_terminal"
    assert second.stop_layers["overall"] == "already_terminal"
    # Single cancellation event.
    assert len(default_run_stop_adapter().events(RUN_ID)) == 1
    assert default_run_stop_adapter().stop_calls == 2


def test_saga_digest_conflict_same_client_action_id() -> None:
    default_run_stop_adapter().ensure_run(RUN_ID, status="running")
    default_run_stop_adapter().ensure_run("hermes.v7c.other", status="running")
    doc_a = _stop_doc(client_action_id="act-conflict", run_ref=RUN_REF)
    doc_b = _stop_doc(
        client_action_id="act-conflict", run_ref="run:hermes.v7c.other"
    )
    first = submit_action(_settings(), doc_a, mutation_enabled=True)
    assert first.status == "accepted"
    second = submit_action(_settings(), doc_b, mutation_enabled=True)
    assert second.status == "conflict"
    assert second.reason_code == "idempotency_digest_conflict"
    # Second run untouched.
    assert default_run_stop_adapter().get_status("hermes.v7c.other") == "running"


def test_saga_partial_stop_reconciling_then_replay_heals() -> None:
    adapter = default_run_stop_adapter()
    adapter.ensure_run(RUN_ID, status="running")
    adapter.next_fault = "partial_stop"
    doc = _stop_doc(client_action_id="act-partial")
    first = submit_action(_settings(), doc, mutation_enabled=True)
    assert first.status == "reconciling"
    assert first.reason_code == "transport_error"
    assert first.stop_layers is not None
    assert first.stop_layers["hermes_run"] == "unknown"
    assert first.stop_layers["overall"] == "reconciling"
    # Durable fact is already stopped.
    assert adapter.get_status(RUN_ID) == "stopped"
    # Exact same action heals via terminal-honest replay.
    second = submit_action(_settings(), doc, mutation_enabled=True)
    assert second.status == "accepted"
    assert second.stop_layers is not None
    assert second.stop_layers["hermes_run"] == "already_terminal"
    assert second.stop_layers["overall"] == "already_terminal"
    assert second.stop_layers["idempotent_replay"] is True


def test_saga_unknown_attempt_ref_keeps_overall_reconciling() -> None:
    """Never paint Task stopped when Attempt layer is unknown (plan §5.5)."""
    default_run_stop_adapter().ensure_run(RUN_ID, status="running")
    doc = _stop_doc(attempt_ref="attempt:research.1")
    receipt = submit_action(_settings(), doc, mutation_enabled=True)
    # Run confirmed, but overall must stay reconciling.
    assert receipt.status == "reconciling"
    assert receipt.reason_code == "stop_layers_reconciling"
    assert receipt.stop_layers is not None
    assert receipt.stop_layers["hermes_run"] == "confirmed"
    assert receipt.stop_layers["hqa_attempt"] == "unknown"
    assert receipt.stop_layers["platform_job"] == "not_applicable"
    assert receipt.stop_layers["overall"] == "reconciling"
    # Run really is stopped underneath.
    assert default_run_stop_adapter().get_status(RUN_ID) == "stopped"


def test_saga_run_not_found_unavailable() -> None:
    receipt = submit_action(
        _settings(),
        _stop_doc(run_ref="run:hermes.missing"),
        mutation_enabled=True,
    )
    assert receipt.status == "unavailable"
    assert receipt.reason_code == "run_not_found"
    assert receipt.stop_layers is not None
    assert receipt.stop_layers["hermes_run"] == "unknown"
    assert receipt.stop_layers["overall"] == "reconciling"


def test_submit_stop_run_request_direct() -> None:
    default_run_stop_adapter().ensure_run(RUN_ID, status="running")
    action = RequestStop(
        client_action_id="act-direct",
        workspace=WorkspaceRef(workspace_id=WS),
        run_ref=RUN_REF,
        task_ref=None,
        attempt_ref=None,
        platform_job_ref=None,
    )
    receipt = submit_stop_run_request(
        _settings(), action, mutation_enabled=True
    )
    assert receipt.status == "accepted"
    assert receipt.run_id == RUN_ID
