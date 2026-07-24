from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.command_ledger import (
    HermesCommandLedgerUnavailable,
    HermesCommandValidationError,
)
from quant_system.hermes.workflow_binding import (
    PreparedWorkflowCommand,
    ensure_bound_command,
    workflow_binding_digest,
    workflow_binding_schema_version,
    workflow_preparation_digest,
)

ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
COMMAND_ID = UUID("10000000-0000-0000-0000-000000000001")


def _prepared(**overrides: object) -> PreparedWorkflowCommand:
    values: dict[str, object] = {
        "schema_version": "1.0",
        "workflow_saga_id": "hqs_0123456789abcdef01234567",
        "owner_user_id": ROOT_USER_ID,
        "platform_session_id": "platform-session-3c1",
        "client_request_id": "req-3c1-001",
        "command_kind": "research_chat",
        "canonical_request_digest": "a" * 64,
        "payload_ref": f"hqa-payload:sha256:{'b' * 64}",
        "payload_digest": "b" * 64,
        "payload_expires_at": datetime(2099, 7, 17, 4, 5, 6, 123456, tzinfo=UTC),
        "provider_policy_digest": "c" * 64,
        "task_id": "hqt_0123456789abcdef01234567",
        "task_version": 3,
        "attempt_id": "hqa_0123456789abcdef01234567",
        "attempt_number": 2,
        "prepared_event_id": "hqe_0123456789abcdef01234567",
        "prepared_event_digest": "d" * 64,
        "plan_schema_version": 1,
        "plan_version": 4,
        "plan_digest": "e" * 64,
        "workflow_preparation_digest": "0" * 64,
    }
    values.update(overrides)
    return PreparedWorkflowCommand(**values)  # type: ignore[arg-type]


def _canonical_preparation(prepared: PreparedWorkflowCommand) -> dict[str, object]:
    return {
        "attempt_id": prepared.attempt_id,
        "attempt_number": prepared.attempt_number,
        "canonical_request_digest": prepared.canonical_request_digest,
        "client_request_id": prepared.client_request_id,
        "command_kind": prepared.command_kind,
        "owner_user_id": str(prepared.owner_user_id),
        "payload_digest": prepared.payload_digest,
        "payload_expires_at": "2099-07-17T04:05:06.123456Z",
        "payload_ref": prepared.payload_ref,
        "plan_digest": prepared.plan_digest,
        "plan_schema_version": prepared.plan_schema_version,
        "plan_version": prepared.plan_version,
        "platform_session_id": prepared.platform_session_id,
        "prepared_event_digest": prepared.prepared_event_digest,
        "prepared_event_id": prepared.prepared_event_id,
        "provider_policy_digest": prepared.provider_policy_digest,
        "schema_version": prepared.schema_version,
        "task_id": prepared.task_id,
        "task_version": prepared.task_version,
        "workflow_saga_id": prepared.workflow_saga_id,
    }


def _sha256(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_workflow_digests_use_the_exact_cross_repo_contract_without_runtime_clocks() -> None:
    draft = _prepared()
    expected_preparation = _sha256(_canonical_preparation(draft))
    prepared = replace(draft, workflow_preparation_digest=expected_preparation)
    expected_binding_payload = {
        **_canonical_preparation(prepared),
        "command_id": str(COMMAND_ID),
        "workflow_preparation_digest": expected_preparation,
    }

    assert workflow_preparation_digest(prepared) == expected_preparation
    assert workflow_binding_digest(prepared, command_id=COMMAND_ID) == _sha256(
        expected_binding_payload
    )
    assert "created_at" not in expected_binding_payload
    assert "updated_at" not in expected_binding_payload


def test_workflow_digests_match_the_fixed_hqa_shared_vector() -> None:
    """Lock the independently generated HQA receipt contract across repositories."""

    prepared = PreparedWorkflowCommand(
        schema_version="1.0",
        workflow_saga_id="hqs_de554cbf6ce04ba776f0ac23",
        owner_user_id=ROOT_USER_ID,
        platform_session_id="session-local-1",
        client_request_id="request-local-1",
        command_kind="research_chat",
        canonical_request_digest=(
            "5690c62bccf502b89822de5c1ab08891c4299d61a1e409934adc4dda88c5b1b4"
        ),
        payload_ref=(
            "hqa-payload:sha256:da7e1a86dd3756884399fd16bbf8152403d6e16be773973599b171d810982c02"
        ),
        payload_digest=("da7e1a86dd3756884399fd16bbf8152403d6e16be773973599b171d810982c02"),
        payload_expires_at=datetime(2026, 8, 15, 1, 2, 3, tzinfo=UTC),
        provider_policy_digest=("8cabaa4cd77aa8992c20063eb3a014daf63131eb20cf1e653c5ef9d2d05ae74c"),
        task_id="hqt_46a7a7f1a4ad8fe4f973847e",
        task_version=1,
        attempt_id="hqa_1df259c2e63e76466265ab2c",
        attempt_number=1,
        prepared_event_id="hqe_b80da4da153eb01c4e56683b",
        prepared_event_digest=("b80da4da153eb01c4e56683bd09b903eb695d87cf42d235f460a550936a41c52"),
        plan_schema_version=1,
        plan_version=1,
        plan_digest=("75671fd286766c741c0abecbcff8050243fe5949020ae6b709e48a895c2eec8d"),
        workflow_preparation_digest=(
            "0b1cc9b95c2cbdecc9f052c30c68b42e626d6214745d50c96aac779c8a2716a1"
        ),
    )

    assert workflow_preparation_digest(prepared) == (
        "0b1cc9b95c2cbdecc9f052c30c68b42e626d6214745d50c96aac779c8a2716a1"
    )
    assert workflow_binding_digest(prepared, command_id=COMMAND_ID) == (
        "baaea27ea6173ed18a52c1eedfd99f0161576ed0f4b954efe3d61077b1d3c8d0"
    )


def test_workflow_binding_digest_changes_when_any_exact_fact_changes() -> None:
    draft = _prepared()
    prepared = replace(
        draft,
        workflow_preparation_digest=workflow_preparation_digest(draft),
    )
    baseline = workflow_binding_digest(prepared, command_id=COMMAND_ID)

    changed_plan = replace(prepared, plan_version=prepared.plan_version + 1)
    changed_plan = replace(
        changed_plan,
        workflow_preparation_digest=workflow_preparation_digest(changed_plan),
    )

    assert workflow_binding_digest(changed_plan, command_id=COMMAND_ID) != baseline
    assert (
        workflow_binding_digest(
            prepared,
            command_id=UUID("10000000-0000-0000-0000-000000000002"),
        )
        != baseline
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": "2.0"},
        {"workflow_saga_id": "not-a-saga"},
        {"owner_user_id": UUID("00000000-0000-0000-0000-000000000002")},
        {"command_kind": "approval"},
        {"payload_ref": f"hqa-payload:sha256:{'f' * 64}"},
        {"provider_policy_digest": ""},
        {"task_version": 0},
        {"task_version": 1.0},
        {"task_version": True},
        {"task_version": 9_223_372_036_854_775_808},
        {"attempt_number": 0},
        {"attempt_number": 2_147_483_648},
        {"plan_schema_version": 2},
        {"plan_schema_version": True},
        {"plan_version": 0},
        {"plan_version": 9_223_372_036_854_775_808},
        {"schema_version": 1},
        {"owner_user_id": str(ROOT_USER_ID)},
    ],
)
def test_invalid_prepared_receipt_fails_before_database_access(
    overrides: dict[str, object],
) -> None:
    draft = _prepared(**overrides)
    prepared = replace(
        draft,
        workflow_preparation_digest=workflow_preparation_digest(draft),
    )
    settings = Settings(database=DatabaseSettings(enabled=False, url=None))

    with pytest.raises(HermesCommandValidationError):
        ensure_bound_command(settings, prepared)


def test_prepared_receipt_rejects_non_datetime_expiry_before_digest_or_database() -> None:
    draft = _prepared()
    prepared = replace(
        draft,
        workflow_preparation_digest=workflow_preparation_digest(draft),
        payload_expires_at="2099-07-17T04:05:06.123456Z",  # type: ignore[arg-type]
    )

    with pytest.raises(HermesCommandValidationError, match="exact datetime"):
        ensure_bound_command(
            Settings(database=DatabaseSettings(enabled=False, url=None)),
            prepared,
        )


def test_preparation_digest_mismatch_fails_before_database_access() -> None:
    settings = Settings(database=DatabaseSettings(enabled=False, url=None))

    with pytest.raises(HermesCommandValidationError, match="workflow_preparation_digest"):
        ensure_bound_command(settings, _prepared(workflow_preparation_digest="f" * 64))


def test_valid_prepared_receipt_has_no_non_postgres_fallback() -> None:
    draft = _prepared()
    prepared = replace(
        draft,
        workflow_preparation_digest=workflow_preparation_digest(draft),
    )
    settings = Settings(database=DatabaseSettings(enabled=False, url=None))

    with pytest.raises(HermesCommandLedgerUnavailable):
        ensure_bound_command(settings, prepared)
    assert workflow_binding_schema_version(settings) is None
