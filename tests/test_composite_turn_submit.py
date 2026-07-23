"""M1 tests for Composite Turn Submit (Fake store; no Keychain/Hermes)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quant_system.hermes.composite_turn_submit import (
    CompositeTurnRequest,
    CompositeTurnSubmitError,
    parse_submit_turn_body,
    submit_composite_turn,
)
from quant_system.hermes.dark_identity_profile import PLATFORM_WORKSPACE_ID
from quant_system.hermes.intent_payload_port import (
    FakeIntentPayloadPort,
    IntentPayloadPortError,
)
from quant_system.hermes.submission_saga import ActionReceipt


def _request(**overrides: object) -> CompositeTurnRequest:
    base = dict(
        workspace_id=PLATFORM_WORKSPACE_ID,
        managed_session_ref="session:managed-1",
        client_action_id="intent-m1-0001",
        prompt="Reply with exactly: L2a-pong",
    )
    base.update(overrides)
    return CompositeTurnRequest(**base)  # type: ignore[arg-type]


def _accepted_receipt(request: CompositeTurnRequest) -> ActionReceipt:
    return ActionReceipt(
        status="accepted",
        client_action_id=request.client_action_id,
        action_digest="d" * 64,
        workspace_id=request.workspace_id,
        command_id="00000000-0000-4000-8000-000000000099",
        platform_session_id="managed-1",
        hermes_session_id="hermes-s1",
        mutation_enabled=True,
    )


def test_parse_submit_turn_body_closed_schema() -> None:
    parsed = parse_submit_turn_body(
        {
            "workspace_id": PLATFORM_WORKSPACE_ID,
            "managed_session_ref": "session:s1",
            "client_action_id": "c1",
            "prompt": "hi",
        }
    )
    assert parsed.prompt == "hi"
    with pytest.raises(CompositeTurnSubmitError) as exc:
        parse_submit_turn_body(
            {
                "workspace_id": PLATFORM_WORKSPACE_ID,
                "managed_session_ref": "session:s1",
                "client_action_id": "c1",
                "prompt": "hi",
                "extra": 1,
            }
        )
    assert exc.value.code == "validation"


def test_submit_rejects_when_mutation_disabled() -> None:
    port = FakeIntentPayloadPort()
    with pytest.raises(CompositeTurnSubmitError) as exc:
        submit_composite_turn(
            SimpleNamespace(),
            _request(),
            mutation_enabled=False,
            port=port,
        )
    assert exc.value.http_status == 403
    assert port.puts == []


def test_submit_rejects_empty_and_oversized_prompt() -> None:
    port = FakeIntentPayloadPort()
    with pytest.raises(CompositeTurnSubmitError) as empty:
        submit_composite_turn(
            SimpleNamespace(),
            _request(prompt="  \n"),
            mutation_enabled=True,
            port=port,
        )
    assert empty.value.http_status == 400
    assert port.puts == []

    with pytest.raises(CompositeTurnSubmitError) as big:
        submit_composite_turn(
            SimpleNamespace(),
            _request(prompt="x" * 20_000),
            mutation_enabled=True,
            port=port,
        )
    assert big.value.http_status == 400
    assert port.puts == []


def test_submit_rejects_non_l2a_workspace() -> None:
    port = FakeIntentPayloadPort()
    with pytest.raises(CompositeTurnSubmitError) as exc:
        submit_composite_turn(
            SimpleNamespace(),
            _request(workspace_id="other"),
            mutation_enabled=True,
            port=port,
        )
    assert exc.value.code == "workspace_not_admitted"
    assert port.puts == []


def test_happy_path_put_then_turn() -> None:
    port = FakeIntentPayloadPort()
    req = _request()
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=_accepted_receipt(req),
    ) as turn:
        result = submit_composite_turn(
            SimpleNamespace(),
            req,
            mutation_enabled=True,
            port=port,
        )
    assert result["status"] == "accepted"
    assert result["payload_ref"].startswith("payload:sha256:")
    assert result["payload_digest"]
    assert result["command_id"]
    assert result["kind"] == "conversation.turn"
    assert "prompt" not in result
    assert len(port.puts) == 1
    put_body = port.puts[0]
    assert put_body["client_intent_id"] == req.client_action_id
    assert put_body["owner_id"] == "owner-local-root"
    assert put_body["workspace_id"] == "workspace:ws-local-main"
    turn.assert_called_once()
    action = turn.call_args.args[1]
    assert action.payload_ref == result["payload_ref"]
    assert action.payload_digest == result["payload_digest"]
    assert action.client_action_id == req.client_action_id


def test_put_conflict_maps_to_http_conflict() -> None:
    def boom(_req):  # type: ignore[no-untyped-def]
        raise IntentPayloadPortError(
            "intent_idempotency_conflict",
            "conflict",
            retryable=False,
        )

    port = FakeIntentPayloadPort(put_handler=boom)
    with pytest.raises(CompositeTurnSubmitError) as exc:
        submit_composite_turn(
            SimpleNamespace(),
            _request(),
            mutation_enabled=True,
            port=port,
        )
    assert exc.value.http_status == 409
    assert exc.value.code == "conflict"


def test_nonretryable_payload_port_failure_stays_nonretryable() -> None:
    def boom(_req):  # type: ignore[no-untyped-def]
        raise IntentPayloadPortError(
            "intent_key_policy_invalid",
            "operator repair required",
            retryable=False,
        )

    session = _managed_session()
    with (
        patch(
            "quant_system.hermes.composite_turn_submit.require_web_writable_session",
            return_value=session,
        ),
        pytest.raises(CompositeTurnSubmitError) as exc,
    ):
        submit_composite_turn(
            SimpleNamespace(),
            _request(),
            mutation_enabled=True,
            port=FakeIntentPayloadPort(put_handler=boom),
        )

    assert exc.value.http_status == 503
    assert exc.value.retryable is False


def test_put_ok_turn_raise_yields_outcome_unknown() -> None:
    port = FakeIntentPayloadPort()
    req = _request()
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        side_effect=RuntimeError("db blip"),
    ):
        # RuntimeError is not caught → should propagate? ADR says turn fail →
        # outcome_unknown. Wrap only known errors; unexpected should still
        # surface. Use SubmissionSagaError instead.
        pass

    from quant_system.hermes.submission_saga import SubmissionSagaError

    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        side_effect=SubmissionSagaError("unavailable", "pg down"),
    ):
        result = submit_composite_turn(
            SimpleNamespace(),
            req,
            mutation_enabled=True,
            port=port,
        )
    assert result["status"] == "outcome_unknown"
    assert result["payload_digest"]
    assert result["recovery_action"] == "follow_and_reconcile_original_action"
    assert len(port.puts) == 1


def test_put_ok_turn_unavailable_receipt_maps_outcome_unknown() -> None:
    port = FakeIntentPayloadPort()
    req = _request()
    unavailable = ActionReceipt(
        status="unavailable",
        client_action_id=req.client_action_id,
        action_digest="e" * 64,
        workspace_id=req.workspace_id,
        reason_code="workspace_authority_unavailable",
        mutation_enabled=True,
    )
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=unavailable,
    ):
        result = submit_composite_turn(
            SimpleNamespace(),
            req,
            mutation_enabled=True,
            port=port,
        )
    assert result["status"] == "outcome_unknown"
    assert result["reason_code"] == "workspace_authority_unavailable"


def test_identical_retry_after_accepted() -> None:
    port = FakeIntentPayloadPort()
    req = _request()
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=_accepted_receipt(req),
    ):
        first = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
        second = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
    assert first["payload_digest"] == second["payload_digest"]
    assert first["status"] == second["status"] == "accepted"
    assert len(port.puts) == 2  # both hit store; store is idempotent


def test_act_style_document_must_not_carry_prompt_field_in_composite_parser() -> None:
    # Guard: composite parser never accepts nested action.prompt aliases.
    with pytest.raises(CompositeTurnSubmitError):
        parse_submit_turn_body(
            {
                "workspace_id": PLATFORM_WORKSPACE_ID,
                "managed_session_ref": "session:s1",
                "client_action_id": "c1",
                "prompt": "hi",
                "action": {"prompt": "nope"},
            }
        )


# --- V8-M2 adversarial close (GAP-01/02/03) ---


def test_v8_m2_same_id_different_prompt_conflicts_zero_turn() -> None:
    """TC-V8-M1-02 / GAP-02: same client_action_id, different body → 409; turn never called."""
    port = FakeIntentPayloadPort()
    req_a = _request(client_action_id="intent-v8-dup", prompt="Reply with exactly: L2a-pong")
    req_b = _request(client_action_id="intent-v8-dup", prompt="Reply with exactly: OTHER")
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=_accepted_receipt(req_a),
    ) as turn:
        first = submit_composite_turn(
            SimpleNamespace(), req_a, mutation_enabled=True, port=port
        )
        assert first["status"] == "accepted"
        with pytest.raises(CompositeTurnSubmitError) as exc:
            submit_composite_turn(
                SimpleNamespace(), req_b, mutation_enabled=True, port=port
            )
    assert exc.value.http_status == 409
    assert exc.value.code == "conflict"
    # First put stored; second put attempted then conflicted — turn only once.
    assert turn.call_count == 1
    assert len(port.puts) == 2


def test_v8_m2_double_submit_same_body_stable_payload_binding() -> None:
    """TC-V8-M1-01 / GAP-01 PARTIAL (composite layer): same body → one intent binding.

    Proves FakeIntentPayloadPort single content-addressed binding + stable
    payload_ref/digest across retries. Does **not** alone prove ledger single
    command_id — that is covered by PG
    ``test_external_turn_conflicts_managed_turn_idempotent_and_conflict``
    (pytest.mark.pg) and BFF double-POST
    ``test_v8_m2_bff_double_post_same_body_stable_payload``.
    """
    port = FakeIntentPayloadPort()
    req = _request(client_action_id="intent-v8-dbl", prompt="Reply with exactly: L2a-pong")
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=_accepted_receipt(req),
    ) as turn:
        r1 = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
        r2 = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
    assert r1["status"] == r2["status"] == "accepted"
    assert r1["payload_digest"] == r2["payload_digest"]
    assert r1["payload_ref"] == r2["payload_ref"]
    assert r1["client_action_id"] == r2["client_action_id"] == req.client_action_id
    assert turn.call_count == 2
    # Fake store keeps a single binding for the client_intent_id.
    assert len(port._store) == 1  # type: ignore[arg-type]
    assert list(port._store.values())[0]["payload_digest"] == r1["payload_digest"]  # type: ignore[index]


def test_v8_m2_ack_loss_retry_recovers_same_payload_binding() -> None:
    """TC-V8-M1-03 / GAP-03: after put+accepted, lost BFF ack retry recovers same binding."""
    port = FakeIntentPayloadPort()
    req = _request(client_action_id="intent-v8-ack", prompt="Reply with exactly: L2a-pong")
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        return_value=_accepted_receipt(req),
    ):
        first = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
        # Simulate client never saw first HTTP body; retries identical request.
        recovered = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
    assert recovered["status"] == "accepted"
    assert recovered["payload_digest"] == first["payload_digest"]
    assert recovered["payload_ref"] == first["payload_ref"]
    assert recovered["command_id"] == first["command_id"]
    assert recovered["client_action_id"] == first["client_action_id"]


def test_v8_m2_outcome_unknown_then_retry_same_id() -> None:
    """GAP-03 branch: put ok + turn unavailable → outcome_unknown; retry may accept."""
    port = FakeIntentPayloadPort()
    req = _request(client_action_id="intent-v8-unk", prompt="Reply with exactly: L2a-pong")
    from quant_system.hermes.submission_saga import SubmissionSagaError

    calls = {"n": 0}

    def _turn(_settings, action, **_kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise SubmissionSagaError("unavailable", "pg blip")
        return _accepted_receipt(req)

    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
        side_effect=_turn,
    ):
        unknown = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
        assert unknown["status"] == "outcome_unknown"
        assert unknown["recovery_action"] == "follow_and_reconcile_original_action"
        accepted = submit_composite_turn(
            SimpleNamespace(), req, mutation_enabled=True, port=port
        )
    assert accepted["status"] == "accepted"
    assert accepted["payload_digest"] == unknown["payload_digest"]
    assert len(port._store) == 1  # type: ignore[arg-type]


def test_v8_m2_port_unavailable_fail_closed_no_turn() -> None:
    """TC-V8-M1-14 / GAP-07 partial: intent port down → 503; turn never called."""

    def boom(_req):  # type: ignore[no-untyped-def]
        raise IntentPayloadPortError(
            "intent_cli_unavailable",
            "hqa intent cli down",
            retryable=True,
        )

    port = FakeIntentPayloadPort(put_handler=boom)
    with patch(
        "quant_system.hermes.composite_turn_submit.submit_conversation_turn",
    ) as turn:
        with pytest.raises(CompositeTurnSubmitError) as exc:
            submit_composite_turn(
                SimpleNamespace(),
                _request(),
                mutation_enabled=True,
                port=port,
            )
    assert exc.value.http_status == 503
    assert exc.value.code == "unavailable"
    turn.assert_not_called()

