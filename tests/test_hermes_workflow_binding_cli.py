from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.hermes import connector_cli
from quant_system.hermes.workflow_binding import (
    EnsureBoundCommandResult,
    HermesWorkflowBinding,
    workflow_binding_to_dict,
)

runner = CliRunner()


def _prepared_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "workflow_saga_id": "hqs_0123456789abcdef01234567",
        "owner_user_id": "00000000-0000-0000-0000-000000000001",
        "platform_session_id": "platform-session-cli",
        "client_request_id": "request-cli-001",
        "command_kind": "research_chat",
        "canonical_request_digest": "1" * 64,
        "payload_ref": f"hqa-payload:sha256:{'2' * 64}",
        "payload_digest": "2" * 64,
        "payload_expires_at": "2099-01-02T03:04:05.123456Z",
        "provider_policy_digest": "3" * 64,
        "task_id": "hqt_0123456789abcdef01234567",
        "task_version": 4,
        "attempt_id": "hqa_0123456789abcdef01234567",
        "attempt_number": 2,
        "prepared_event_id": "hqe_0123456789abcdef01234567",
        "prepared_event_digest": "4" * 64,
        "plan_schema_version": 1,
        "plan_version": 3,
        "plan_digest": "5" * 64,
        "workflow_preparation_digest": "6" * 64,
    }


def _binding() -> HermesWorkflowBinding:
    prepared = _prepared_payload()
    return HermesWorkflowBinding(
        command_id=UUID("10000000-0000-0000-0000-000000000001"),
        command_version=1,
        preparation_schema_version=str(prepared["schema_version"]),
        workflow_saga_id=str(prepared["workflow_saga_id"]),
        owner_user_id=UUID(str(prepared["owner_user_id"])),
        platform_session_id=str(prepared["platform_session_id"]),
        client_request_id=str(prepared["client_request_id"]),
        command_kind=str(prepared["command_kind"]),
        canonical_request_digest=str(prepared["canonical_request_digest"]),
        payload_ref=str(prepared["payload_ref"]),
        payload_digest=str(prepared["payload_digest"]),
        payload_expires_at=datetime(2099, 1, 2, 3, 4, 5, 123456, tzinfo=UTC),
        provider_policy_digest=str(prepared["provider_policy_digest"]),
        task_id=str(prepared["task_id"]),
        task_version=int(prepared["task_version"]),
        attempt_id=str(prepared["attempt_id"]),
        attempt_number=int(prepared["attempt_number"]),
        prepared_event_id=str(prepared["prepared_event_id"]),
        prepared_event_digest=str(prepared["prepared_event_digest"]),
        plan_schema_version=int(prepared["plan_schema_version"]),
        plan_version=int(prepared["plan_version"]),
        plan_digest=str(prepared["plan_digest"]),
        workflow_preparation_digest=str(prepared["workflow_preparation_digest"]),
        binding_schema_version=1,
        binding_digest="7" * 64,
        created_at=datetime(2026, 7, 16, 1, 2, 3, 456789, tzinfo=UTC),
    )


def test_workflow_binding_ensure_reads_only_strict_metadata_from_stdin(
    monkeypatch,
) -> None:
    seen = []
    binding = _binding()

    def ensure(_settings, prepared):
        seen.append(prepared)
        return EnsureBoundCommandResult(
            command_id=binding.command_id,
            command_state="queued",
            command_version=1,
            binding=binding,
            created=True,
        )

    monkeypatch.setattr(connector_cli, "load_settings", lambda: object())
    monkeypatch.setattr(connector_cli, "ensure_bound_command", ensure)

    result = runner.invoke(
        app,
        ["hermes", "workflow-binding", "ensure"],
        input=json.dumps(_prepared_payload()),
    )

    assert result.exit_code == 0
    assert len(seen) == 1
    assert seen[0].payload_expires_at == datetime(2099, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)
    payload = json.loads(result.stdout)
    assert payload == {
        "binding": {
            "attempt_id": "hqa_0123456789abcdef01234567",
            "attempt_number": 2,
            "binding_digest": "7" * 64,
            "binding_schema_version": 1,
            "canonical_request_digest": "1" * 64,
            "client_request_id": "request-cli-001",
            "command_id": "10000000-0000-0000-0000-000000000001",
            "command_kind": "research_chat",
            "command_version": 1,
            "created_at": "2026-07-16T01:02:03.456789Z",
            "owner_user_id": "00000000-0000-0000-0000-000000000001",
            "payload_digest": "2" * 64,
            "payload_expires_at": "2099-01-02T03:04:05.123456Z",
            "payload_ref": f"hqa-payload:sha256:{'2' * 64}",
            "plan_digest": "5" * 64,
            "plan_schema_version": 1,
            "plan_version": 3,
            "platform_session_id": "platform-session-cli",
            "preparation_schema_version": "1.0",
            "prepared_event_digest": "4" * 64,
            "prepared_event_id": "hqe_0123456789abcdef01234567",
            "provider_policy_digest": "3" * 64,
            "task_id": "hqt_0123456789abcdef01234567",
            "task_version": 4,
            "workflow_preparation_digest": "6" * 64,
            "workflow_saga_id": "hqs_0123456789abcdef01234567",
        },
        "command_id": "10000000-0000-0000-0000-000000000001",
        "command_state": "queued",
        "command_version": 1,
        "created": True,
    }
    assert "prompt" not in result.stdout
    assert "secret" not in result.stdout


def test_workflow_binding_ensure_rejects_unknown_prompt_without_calling_storage(
    monkeypatch,
) -> None:
    called = False

    def ensure(*_args, **_kwargs):
        nonlocal called
        called = True

    payload = _prepared_payload()
    payload["prompt"] = "must never cross this interface"
    monkeypatch.setattr(connector_cli, "ensure_bound_command", ensure)

    result = runner.invoke(
        app,
        ["hermes", "workflow-binding", "ensure"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout) == {"error_code": "workflow_binding_validation_failed"}
    assert called is False
    assert "must never" not in result.stdout


@pytest.mark.parametrize(
    "receipt",
    [
        '{"schema_version":"1.0","schema_version":"1.0"}',
        json.dumps({**_prepared_payload(), "task_version": None}).replace(
            '"task_version": null',
            '"task_version": NaN',
        ),
        json.dumps(
            {
                **_prepared_payload(),
                "payload_expires_at": "2099-01-02T03:04:05.123Z",
            }
        ),
    ],
    ids=("duplicate-key", "non-finite-number", "noncanonical-timestamp"),
)
def test_workflow_binding_ensure_rejects_ambiguous_json_without_storage(
    monkeypatch,
    receipt: str,
) -> None:
    called = False

    def ensure(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(connector_cli, "ensure_bound_command", ensure)

    result = runner.invoke(
        app,
        ["hermes", "workflow-binding", "ensure"],
        input=receipt,
    )

    assert result.exit_code == 2
    assert json.loads(result.stdout) == {"error_code": "workflow_binding_validation_failed"}
    assert called is False


def test_prepared_receipt_reader_rejects_invalid_utf8(monkeypatch) -> None:
    stdin = SimpleNamespace(buffer=BytesIO(b"\xff"))
    monkeypatch.setattr(connector_cli.sys, "stdin", stdin)

    with pytest.raises(connector_cli.WorkflowBindingInputError):
        connector_cli._read_prepared_workflow_command()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_version", 9_223_372_036_854_775_808),
        ("attempt_number", 2_147_483_648),
        ("plan_version", 9_223_372_036_854_775_808),
        ("task_version", 1.0),
        ("attempt_number", True),
    ],
)
def test_workflow_binding_ensure_rejects_invalid_postgres_integer_without_storage(
    monkeypatch,
    field: str,
    value: object,
) -> None:
    called = False

    def ensure(*_args, **_kwargs):
        nonlocal called
        called = True

    payload = _prepared_payload()
    payload[field] = value
    monkeypatch.setattr(connector_cli, "ensure_bound_command", ensure)

    result = runner.invoke(
        app,
        ["hermes", "workflow-binding", "ensure"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 2
    assert result.stdout.strip().splitlines() == [
        '{"error_code":"workflow_binding_validation_failed"}'
    ]
    assert "Traceback" not in result.output
    assert result.stderr == ""
    assert called is False


def test_workflow_binding_ensure_maps_huge_json_integer_to_one_generic_envelope(
    monkeypatch,
) -> None:
    called = False

    def ensure(*_args, **_kwargs):
        nonlocal called
        called = True

    payload = json.dumps(_prepared_payload())
    payload = payload.replace('"task_version": 4', '"task_version": ' + "9" * 5_000)
    monkeypatch.setattr(connector_cli, "ensure_bound_command", ensure)

    result = runner.invoke(
        app,
        ["hermes", "workflow-binding", "ensure"],
        input=payload,
    )

    assert result.exit_code == 2
    assert result.stdout.strip().splitlines() == [
        '{"error_code":"workflow_binding_validation_failed"}'
    ]
    assert "Traceback" not in result.output
    assert result.stderr == ""
    assert called is False


def test_workflow_binding_show_is_saga_scoped_and_metadata_only(monkeypatch) -> None:
    binding = _binding()
    seen = []
    monkeypatch.setattr(connector_cli, "load_settings", lambda: object())

    def get_binding(_settings, workflow_saga_id):
        seen.append(workflow_saga_id)
        return binding

    monkeypatch.setattr(
        connector_cli,
        "get_workflow_binding_by_saga",
        get_binding,
    )

    result = runner.invoke(
        app,
        [
            "hermes",
            "workflow-binding",
            "show",
            "--workflow-saga-id",
            binding.workflow_saga_id,
        ],
    )

    assert result.exit_code == 0
    assert seen == [binding.workflow_saga_id]
    payload = json.loads(result.stdout)
    assert payload["binding"]["binding_digest"] == binding.binding_digest
    assert payload["binding"]["payload_ref"].startswith("hqa-payload:sha256:")
    assert "prompt" not in result.stdout
    assert "secret" not in result.stdout


def test_workflow_binding_inventory_streams_strict_ndjson_without_reading_stdin(
    monkeypatch,
) -> None:
    binding = workflow_binding_to_dict(_binding())
    records = [
        {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_header",
            "binding_schema_version": 1,
        },
        {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_item",
            "ordinal": 1,
            "binding": binding,
        },
        {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_trailer",
            "count": 1,
            "bindings_sha256": "8" * 64,
        },
    ]
    seen_settings = []

    def inventory(settings):
        seen_settings.append(settings)
        yield from records

    monkeypatch.setattr(connector_cli, "load_settings", lambda: "settings")
    monkeypatch.setattr(connector_cli, "iter_workflow_binding_inventory", inventory)
    monkeypatch.setattr(
        connector_cli,
        "_read_prepared_workflow_command",
        lambda: pytest.fail("inventory must not read stdin"),
    )

    result = runner.invoke(
        app,
        ["hermes", "workflow-binding", "inventory"],
        input="prompt=must-not-be-read provider=grok model=secret\n",
    )

    assert result.exit_code == 0
    assert seen_settings == ["settings"]
    assert [json.loads(line) for line in result.stdout.splitlines()] == records
    assert result.stderr == ""
    assert "must-not-be-read" not in result.output
    assert "provider=grok" not in result.output
    assert "model=secret" not in result.output


def test_workflow_binding_inventory_partial_stream_has_no_success_trailer_on_error(
    monkeypatch,
) -> None:
    def inventory(_settings):
        yield {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_header",
            "binding_schema_version": 1,
        }
        raise connector_cli.HermesCommandLedgerUnavailable(
            "postgresql://user:secret@db.example/private"
        )

    monkeypatch.setattr(connector_cli, "load_settings", lambda: object())
    monkeypatch.setattr(connector_cli, "iter_workflow_binding_inventory", inventory)

    result = runner.invoke(app, ["hermes", "workflow-binding", "inventory"])

    assert result.exit_code == 1
    assert [json.loads(line) for line in result.stdout.splitlines()] == [
        {
            "schema_version": "1.0",
            "kind": "workflow_binding_inventory_header",
            "binding_schema_version": 1,
        }
    ]
    assert json.loads(result.stderr) == {"error_code": "workflow_binding_inventory_unavailable"}
    assert "workflow_binding_inventory_trailer" not in result.output
    assert "postgresql" not in result.output
    assert "secret" not in result.output


def test_workflow_binding_inventory_rejects_extra_arguments_before_storage(
    monkeypatch,
) -> None:
    called = False

    def inventory(_settings):
        nonlocal called
        called = True
        return iter(())

    monkeypatch.setattr(connector_cli, "iter_workflow_binding_inventory", inventory)

    result = runner.invoke(
        app,
        ["hermes", "workflow-binding", "inventory", "--limit", "1"],
    )

    assert result.exit_code == 2
    assert called is False
