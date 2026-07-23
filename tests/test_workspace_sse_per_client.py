"""Regression coverage for connection-local workspace SSE projection delivery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.routes import workspace as workspace_routes
from quant_system.api.safety.local_session import issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes.approval_observe import (
    reset_default_approval_observe_journal,
)
from quant_system.hermes.gate_observe import reset_default_gate_observe_journal
from quant_system.hermes.result_observe import reset_default_result_observe_journal
from quant_system.hermes.transcript_observe import (
    reset_default_transcript_observe_journal,
)
from quant_system.hermes.vertical_observe import (
    reset_default_vertical_observe_journal,
)

ORIGIN = "http://127.0.0.1:3001"
WORKSPACE_ID = "workspace-sse-two-clients"


@pytest.fixture(autouse=True)
def _reset_process_journals() -> None:
    resets = (
        reset_default_approval_observe_journal,
        reset_default_gate_observe_journal,
        reset_default_result_observe_journal,
        reset_default_vertical_observe_journal,
        reset_default_transcript_observe_journal,
    )
    for reset in resets:
        reset()
    yield
    for reset in resets:
        reset()


def _settings() -> Settings:
    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        api_cors_origins=[ORIGIN],
    )


def _headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "Host": "testserver",
    }


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=_settings(),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    assert bootstrap.status_code == 200, bootstrap.text
    return client


class _ProjectionPage:
    def to_public_dict(self) -> dict[str, object]:
        return {
            "workspace_id": WORKSPACE_ID,
            "events": [
                {
                    "event_id": 1,
                    "command_id": "command-two-clients",
                    "state": "leased",
                    "hermes_session_id": "web.two-clients",
                    "command_version": 1,
                    "type": "command.leased",
                }
            ],
            "next_cursor": 1,
            "resync_required": False,
            "mutation_enabled": False,
            "approvals": [
                {
                    "approval_id": "approval-two-clients",
                    "status": "pending",
                }
            ],
            "gates": [
                {
                    "gate_id": "gate-two-clients",
                    "gate_kind": "gate_1",
                    "status": "pending",
                    "expected_digest": "a" * 64,
                }
            ],
            "results": [
                {
                    "result_id": "result-two-clients",
                    "kind": "factor",
                    "status": "ready",
                    "sample_or_real": "real",
                    "payload_digest": "b" * 64,
                }
            ],
            "tasks": ["task-two-clients"],
            "attempts": ["attempt-two-clients"],
            "runs": ["run-two-clients"],
            "authority_health": {
                "command_approval": "ready",
                "gate_1": "ready",
                "gate_2": "ready",
                "gate_3": "ready",
                "result": "ready",
                "task": "ready",
                "attempt": "ready",
                "run": "ready",
            },
        }


class _ProjectionWorkspace:
    def follow(self, *_args: object, **_kwargs: object) -> _ProjectionPage:
        return _ProjectionPage()


def _event_payloads(body: str, event_name: str) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for frame in body.split("\n\n"):
        lines = frame.splitlines()
        if f"event: {event_name}" not in lines:
            continue
        data = next(line for line in lines if line.startswith("data: "))
        payloads.append(json.loads(data.removeprefix("data: ")))
    return payloads


def test_each_sse_client_receives_all_projection_updates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One subscriber must not consume fingerprints needed by another."""
    monkeypatch.setattr(
        workspace_routes,
        "_workspace",
        lambda _settings: _ProjectionWorkspace(),
    )
    client = _client(tmp_path)
    url = (
        f"/api/workspace/{WORKSPACE_ID}/follow/stream"
        "?after_cursor=0&max_ticks=1&poll_seconds=0"
    )

    first = client.get(url, headers=_headers())
    second = client.get(url, headers=_headers())

    assert first.status_code == second.status_code == 200
    for response in (first, second):
        assert _event_payloads(response.text, "approvals")[0]["approvals"] == [
            {
                "approval_id": "approval-two-clients",
                "status": "pending",
            }
        ]
        assert _event_payloads(response.text, "gates")[0]["gates"][0][
            "gate_id"
        ] == "gate-two-clients"
        assert _event_payloads(response.text, "results")[0]["results"][0][
            "result_id"
        ] == "result-two-clients"
        assert _event_payloads(response.text, "vertical")[0]["tasks"] == [
            "task-two-clients"
        ]
        transcript = _event_payloads(response.text, "transcript")[0]
        assert transcript["hermes_session_id"] == "web.two-clients"
        for forbidden in (
            "assistant",
            "body",
            "content",
            "delta",
            "message",
            "messages",
            "payload",
            "text",
            "tokens",
        ):
            assert forbidden not in transcript
