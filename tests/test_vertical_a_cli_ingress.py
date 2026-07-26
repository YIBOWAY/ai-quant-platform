from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from quant_system.hermes import vertical_a_cli
from quant_system.hermes.submission_saga import ActionReceipt

_CONTEXT = {
    "HERMES_PLATFORM_COMMAND_ID": "10000000-0000-4000-8000-000000000077",
    "HERMES_PLATFORM_SESSION_ID": "wm_browser_session",
    "HERMES_PLATFORM_RUN_ID": "run-browser-options",
    "HERMES_PLATFORM_MANAGED_SESSION_ID": "web_" + ("a" * 40),
}


def _request() -> dict[str, object]:
    return {
        "ticker": "AAPL",
        "expiry": "2099-12-18",
        "strike": 200,
        "goal_note": "Inspect this exact AAPL put using Futu read-only data.",
    }


def _context(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _CONTEXT.items():
        monkeypatch.setenv(name, value)


class _Workspace:
    def __init__(self, receipt: ActionReceipt) -> None:
        self.receipt = receipt
        self.actions: list[object] = []

    def act(self, _actor: str, action: object) -> ActionReceipt:
        self.actions.append(action)
        return self.receipt


def _seed_receipt(*, completed: bool = False) -> ActionReceipt:
    return ActionReceipt(
        status="accepted" if completed else "reconciling",
        client_action_id="vertical-a-nl-placeholder",
        action_digest="a" * 64,
        workspace_id="ws-local-main",
        domain_request_id="vreq-ingress-1",
        domain_request_status="completed" if completed else "awaiting_run",
        domain_admission_id="admission-ingress-1",
        domain_admission_digest="b" * 64,
        result_id="varesult-ingress-1" if completed else None,
        mutation_enabled=True,
    )


def test_execute_from_hermes_binds_natural_language_tool_to_exact_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _context(monkeypatch)
    workspace = _Workspace(_seed_receipt())
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        vertical_a_cli,
        "load_settings",
        lambda: SimpleNamespace(local_mutation=SimpleNamespace(enabled=True)),
    )
    monkeypatch.setattr(
        vertical_a_cli,
        "PlatformAgentWorkspace",
        lambda *_args, **_kwargs: workspace,
    )

    def execute(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "capture_digest": "c" * 64,
            "claim_id": "vaclaim-ingress-1",
            "command_id": _CONTEXT["HERMES_PLATFORM_COMMAND_ID"],
            "domain_request_id": "vreq-ingress-1",
            "provider_receipt_id": "vaprovider-ingress-1",
            "result_id": "varesult-ingress-1",
            "run_ref": "run:run-browser-options",
            "session_ref": "session:wm_browser_session",
            "status": "completed",
        }

    monkeypatch.setattr(vertical_a_cli, "execute_request", execute)

    result = vertical_a_cli.execute_from_hermes_request(_request())

    assert result["contract"] == "agent-v0.2-options-research/v1"
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert result["ingress_command_id"] == _CONTEXT["HERMES_PLATFORM_COMMAND_ID"]
    assert result["replayed"] is False
    assert observed == {
        "request_id": "vreq-ingress-1",
        "expected_action_digest": "a" * 64,
        "expected_admission_id": "admission-ingress-1",
        "expected_admission_digest": "b" * 64,
        "session_ref": "session:wm_browser_session",
        "run_ref": "run:run-browser-options",
        "worker_id": "hqa-hermes-options-tool",
    }
    assert len(workspace.actions) == 1
    action = workspace.actions[0]
    assert action.ticker == "AAPL"
    assert action.provider_mode == "live_futu_ro"
    assert action.include_provider_evidence is True
    assert action.auth_envelope["max_calls"] == 1
    assert action.auth_envelope["tickers"] == ["AAPL"]


def test_execute_from_hermes_replays_completed_without_second_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _context(monkeypatch)
    workspace = _Workspace(_seed_receipt(completed=True))
    monkeypatch.setattr(
        vertical_a_cli,
        "load_settings",
        lambda: SimpleNamespace(local_mutation=SimpleNamespace(enabled=True)),
    )
    monkeypatch.setattr(
        vertical_a_cli,
        "PlatformAgentWorkspace",
        lambda *_args, **_kwargs: workspace,
    )
    monkeypatch.setattr(
        vertical_a_cli,
        "execute_request",
        lambda **_kwargs: pytest.fail("completed replay must not call Futu again"),
    )

    result = vertical_a_cli.execute_from_hermes_request(_request())

    assert result["status"] == "completed"
    assert result["replayed"] is True
    assert result["result_id"] == "varesult-ingress-1"


@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "AAPL", "expiry": "2099-12-18", "strike": 200},
        {**_request(), "unexpected": True},
        {**_request(), "ticker": "../AAPL"},
        {**_request(), "expiry": "2099-02-30"},
        {**_request(), "strike": float("nan")},
        {**_request(), "goal_note": ""},
    ],
)
def test_execute_from_hermes_rejects_ambiguous_or_nonfinite_requests(
    payload: dict[str, object],
) -> None:
    with pytest.raises(vertical_a_cli.VerticalAIngressError) as caught:
        vertical_a_cli.execute_from_hermes_request(payload)

    assert caught.value.code == "vertical_a_request_invalid"


def test_execute_from_hermes_requires_all_exact_managed_run_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _context(monkeypatch)
    monkeypatch.delenv("HERMES_PLATFORM_RUN_ID")

    with pytest.raises(vertical_a_cli.VerticalAIngressError) as caught:
        vertical_a_cli.execute_from_hermes_request(_request())

    assert caught.value.code == "vertical_a_managed_run_context_missing"


def test_cli_emits_one_closed_json_error_without_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in _CONTEXT:
        monkeypatch.delenv(name, raising=False)

    result = CliRunner().invoke(
        vertical_a_cli.app,
        ["execute-from-hermes"],
        input=json.dumps(_request()),
    )

    assert result.exit_code == 2
    payload = json.loads(result.stderr)
    assert payload == {
        "contract": "agent-v0.2-options-research/v1",
        "error_code": "vertical_a_managed_run_context_missing",
        "message": "an exact managed Hermes Run context is required",
        "ok": False,
        "status": "unavailable",
    }
