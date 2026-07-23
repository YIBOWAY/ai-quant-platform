"""Plan-V6-Token-Stream-M1: body-free transcript hints on follow/SSE."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)
from quant_system.hermes.transcript_observe import (
    assert_hint_has_no_body,
    default_transcript_observe_journal,
    hints_from_command_events,
    phase_from_command_state,
    project_transcript_hint,
    reset_default_transcript_observe_journal,
    revision_for,
)

ORIGIN = "http://127.0.0.1:3001"
WORKSPACE_ID = "ws-v6-token-stream-m1"


@pytest.fixture(autouse=True)
def _reset_journal() -> None:
    reset_default_transcript_observe_journal()
    yield
    reset_default_transcript_observe_journal()


def _settings() -> Settings:
    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        api_cors_origins=[ORIGIN, "http://127.0.0.1:3000", "http://localhost:3001"],
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=_settings(),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    return TestClient(app)


def _browser_headers(*, origin: str = ORIGIN, site: str = "same-origin") -> dict[str, str]:
    return {
        "Origin": origin,
        "Sec-Fetch-Site": site,
        "Host": "testserver",
    }


def _bootstrap(client: TestClient, tmp_path: Path) -> None:
    token = issue_bootstrap_token(tmp_path)
    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text


# TC-TS-01 / phase helpers
def test_phase_from_command_state_mapping() -> None:
    assert phase_from_command_state("queued") == "waiting"
    assert phase_from_command_state("leased") == "waiting"
    assert phase_from_command_state("delivered") == "waiting"
    assert phase_from_command_state("outcome_unknown") == "waiting"
    assert phase_from_command_state("succeeded") == "final"
    assert phase_from_command_state("failed") == "final"
    assert phase_from_command_state(None) is None
    assert phase_from_command_state("") is None


# TC-TS-02 payload shape + no body
def test_project_hint_forbids_bodies() -> None:
    hint = project_transcript_hint(
        workspace_id=WORKSPACE_ID,
        hermes_session_id="run_abc123",
        command_id="cmd-1",
        phase="waiting",
        revision="r1",
        mutation_enabled=False,
    )
    assert hint["hermes_session_id"] == "run_abc123"
    assert hint["phase"] == "waiting"
    assert hint["transport"] == "spine-refetch"
    assert "content" not in hint
    assert "text" not in hint
    assert "tokens" not in hint
    assert "messages" not in hint
    assert "delta" not in hint
    assert_hint_has_no_body(hint)
    assert "not_provider_token_passthrough" in hint["limitations"]
    assert "messages_bff_is_text_authority" in hint["limitations"]


def test_project_hint_accepts_hermes_web_id_and_rejects_platform_wm_id() -> None:
    hint = project_transcript_hint(
        workspace_id=WORKSPACE_ID,
        hermes_session_id="web_abc",
        command_id=None,
        phase="waiting",
        revision="r1",
    )
    assert hint["hermes_session_id"] == "web_abc"

    with pytest.raises(ValueError):
        project_transcript_hint(
            workspace_id=WORKSPACE_ID,
            hermes_session_id="wm_abc",
            command_id=None,
            phase="waiting",
            revision="r1",
        )


# TC-TS-04 derive from command events
def test_hints_from_command_events() -> None:
    events = [
        {
            "command_id": "c1",
            "state": "leased",
            "hermes_session_id": "web_sess1",
            "command_version": 2,
        },
        {
            "command_id": "c1",
            "state": "delivered",
            "hermes_session_id": "web_sess1",
            "command_version": 3,
        },
        {
            "command_id": "c2",
            "state": "queued",
            "hermes_session_id": "wm_bad",
        },
        {
            "command_id": "c3",
            "state": "queued",
            # no hermes_session_id
        },
    ]
    hints = hints_from_command_events(
        workspace_id=WORKSPACE_ID, events=events, mutation_enabled=False
    )
    assert len(hints) == 2
    assert hints[0]["phase"] == "waiting"
    assert hints[1]["phase"] == "waiting"
    for h in hints:
        assert "content" not in h
        assert h["hermes_session_id"] == "web_sess1"


def test_journal_dedupes_same_revision() -> None:
    j = default_transcript_observe_journal()
    h = project_transcript_hint(
        workspace_id=WORKSPACE_ID,
        hermes_session_id="run_x",
        command_id="c",
        phase="waiting",
        revision="rev-1",
    )
    first = j.take_hints_if_changed(WORKSPACE_ID, [h])
    assert first is not None and len(first) == 1
    second = j.take_hints_if_changed(WORKSPACE_ID, [h])
    assert second is None
    h2 = dict(h)
    h2["revision"] = "rev-2"
    h2["phase"] = "final"
    third = j.take_hints_if_changed(WORKSPACE_ID, [h2])
    assert third is not None and third[0]["phase"] == "final"


def test_revision_stable() -> None:
    r1 = revision_for(
        hermes_session_id="run_a",
        command_id="c",
        state="queued",
        command_version=1,
    )
    r2 = revision_for(
        hermes_session_id="run_a",
        command_id="c",
        state="queued",
        command_version=1,
    )
    r3 = revision_for(
        hermes_session_id="run_a",
        command_id="c",
        state="delivered",
        command_version=2,
    )
    assert r1 == r2
    assert r1 != r3


# TC-TS-01/02/03 SSE
def test_follow_stream_ready_scope_includes_transcript_hints(tmp_path: Path) -> None:
    client = _client(tmp_path)
    denied = client.get(
        f"/api/workspace/{WORKSPACE_ID}/follow/stream?after_cursor=0&max_ticks=1&poll_seconds=0",
        headers=_browser_headers(),
    )
    assert denied.status_code == 401

    _bootstrap(client, tmp_path)
    response = client.get(
        f"/api/workspace/{WORKSPACE_ID}/follow/stream"
        f"?after_cursor=0&max_ticks=1&poll_seconds=0",
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "event: ready" in body
    assert "transcript_hints" in body
    assert "command_lifecycle" in body
    # No assistant body channel
    assert "assistant_token" not in body
    assert '"content":' not in body or "event: transcript" not in body
    # Parse ready frame
    ready_data = None
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "event: ready":
            data_line = lines[i + 1]
            assert data_line.startswith("data: ")
            ready_data = json.loads(data_line[len("data: ") :])
            break
    assert ready_data is not None
    assert "transcript_hints" in str(ready_data.get("scope", ""))
    # If transcript events present, assert no body keys
    chunks = body.split("event: ")
    for chunk in chunks:
        if chunk.startswith("transcript"):
            data_line = [ln for ln in chunk.splitlines() if ln.startswith("data: ")][0]
            payload = json.loads(data_line[len("data: ") :])
            for banned in ("content", "text", "tokens", "delta", "messages"):
                assert banned not in payload


def test_mutation_off_observe_still_streams(tmp_path: Path) -> None:
    """TC-TS-16: mutation-off observe path still works; zero new act kinds."""
    client = _client(tmp_path)
    _bootstrap(client, tmp_path)
    response = client.get(
        f"/api/workspace/{WORKSPACE_ID}/follow/stream"
        f"?after_cursor=0&max_ticks=1&poll_seconds=0",
        headers=_browser_headers(),
    )
    assert response.status_code == 200
    assert "mutation_enabled" in response.text

def test_follow_stream_emits_transcript_hint_no_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SSE emits a body-free hint when follow carries a Hermes Session id."""
    from quant_system.hermes import agent_workspace as aw

    class _FakePage:
        def to_public_dict(self) -> dict:
            return {
                "workspace_id": WORKSPACE_ID,
                "events": [
                    {
                        "event_id": 1,
                        "command_id": "cmd-stream-1",
                        "state": "leased",
                        "hermes_session_id": "run_stream_seed_1",
                        "command_version": 2,
                        "type": "command.leased",
                    }
                ],
                "next_cursor": 1,
                "resync_required": False,
                "mutation_enabled": False,
                "approvals": [],
                "gates": [],
                "results": [],
                "tasks": [],
                "attempts": [],
                "runs": [],
                "authority_health": {},
            }

    def _fake_follow(self, actor, workspace_ref, after=0):  # noqa: ANN001
        return _FakePage()

    monkeypatch.setattr(aw.PlatformAgentWorkspace, "follow", _fake_follow)

    client = _client(tmp_path)
    _bootstrap(client, tmp_path)
    response = client.get(
        f"/api/workspace/{WORKSPACE_ID}/follow/stream"
        f"?after_cursor=0&max_ticks=1&poll_seconds=0",
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "event: transcript" in body
    # Parse every transcript frame and hard-ban body keys
    frames = body.split("event: ")
    transcript_count = 0
    for chunk in frames:
        if not chunk.startswith("transcript"):
            continue
        transcript_count += 1
        data_line = next(ln for ln in chunk.splitlines() if ln.startswith("data: "))
        payload = json.loads(data_line[len("data: "):])
        for banned in (
            "content",
            "text",
            "tokens",
            "delta",
            "messages",
            "message",
            "body",
            "assistant",
            "payload",
        ):
            assert banned not in payload
        assert payload.get("hermes_session_id") == "run_stream_seed_1"
        assert payload.get("phase") == "waiting"
        assert payload.get("transport") == "spine-refetch"
        assert "not_provider_token_passthrough" in (payload.get("limitations") or [])
    assert transcript_count >= 1
