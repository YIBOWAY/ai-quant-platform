import json
from pathlib import Path

import httpx
import pytest

from quant_system.hermes.native_run_port import NativeHermesRunPort, NativeReceipts
from quant_system.hermes.run_lifecycle_port import HermesRunCliSettings, HermesRunPortError

CAPS = {
    "object": "hermes.api_server.capabilities",
    "features": {
        "run_submission": True,
        "run_status": True,
        "run_stop": True,
        "session_resources": True,
        "runs_idempotency": {"supported": True, "durable": True, "retention_seconds": 86400},
    },
}


def port(tmp_path, handler):
    return NativeHermesRunPort(
        cli_settings=HermesRunCliSettings(Path("/unused"), tmp_path, "http://127.0.0.1:8652", None),
        input_resolver=lambda request: "test",
        state_path=tmp_path / "native.sqlite3",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_native_capabilities_are_not_fabricated_private_probes(tmp_path):
    p = port(tmp_path, lambda r: httpx.Response(200, json=CAPS))
    receipt = p.require_compatible_capabilities()
    assert receipt.hermes_contract_version == 0
    assert "durable" not in p.capabilities()


def test_memory_only_idempotency_is_not_ready(tmp_path):
    caps = json.loads(json.dumps(CAPS))
    caps["features"]["runs_idempotency"]["durable"] = False
    p = port(tmp_path, lambda r: httpx.Response(200, json=caps))
    with pytest.raises(HermesRunPortError, match="requirements unavailable"):
        p.require_compatible_capabilities()


def test_project_receipt_prevents_second_post_after_native_retention(tmp_path):
    posts = []

    def handler(r):
        if r.method == "GET":
            return httpx.Response(200, json=CAPS)
        posts.append(r)
        return httpx.Response(202, json={"run_id": "run_1", "replayed": False})

    p = port(tmp_path, handler)
    request = {
        "idempotency_key": "test-1",
        "request_body": {"session_id": "web_test", "input": "hi"},
    }
    first = p._invoke("submit", request)
    with p.receipts.connect() as db:
        db.execute("UPDATE requests SET first_sent=0")
    second = p._invoke("submit", request)
    assert len(posts) == 1
    assert first["created"] is True and second["created"] is False
    assert first["run_id"] == second["run_id"]


def test_changed_request_and_expired_unknown_acceptance_are_rejected(tmp_path):
    receipts = NativeReceipts(tmp_path / "native.sqlite3")
    body = {"session_id": "web_s", "input": "a"}
    receipts.reserve("key", body, 86400)
    with pytest.raises(HermesRunPortError):
        receipts.reserve("key", {**body, "input": "b"}, 86400)
    with receipts.connect() as db:
        db.execute("UPDATE requests SET first_sent=0")
    with pytest.raises(HermesRunPortError) as err:
        receipts.reserve("key", body, 86400)
    assert err.value.code == "native_replay_window_expired"


@pytest.mark.parametrize(
    ("upstream", "project"),
    [
        ("completed", "succeeded"),
        ("interrupted", "cancelled"),
        ("stopping", "running"),
        ("failed", "failed"),
    ],
)
def test_terminal_evidence_is_native_status_not_invented_replay(tmp_path, upstream, project):
    p = port(
        tmp_path,
        lambda r: httpx.Response(
            200,
            json={
                "object": "hermes.run",
                "run_id": "run_1",
                "session_id": "web_s",
                "status": upstream,
            },
        ),
    )
    observation = p.observe(hermes_session_id="web_s", hermes_run_id="run_1")
    assert observation.status == project
    assert observation.replay_complete is False
    assert observation.terminal_evidence_source == (
        "native_status" if observation.is_terminal else "event_replay"
    )


def test_wrong_session_does_not_complete_command(tmp_path):
    p = port(
        tmp_path,
        lambda r: httpx.Response(
            200, json={"run_id": "run_1", "session_id": "other", "status": "completed"}
        ),
    )
    observation = p.observe(hermes_session_id="web_s", hermes_run_id="run_1")
    assert observation.status == "outcome_unknown"
    assert observation.evidence_digest is None


def test_definite_rejection_does_not_permanently_block_session(tmp_path):
    def handler(r):
        return (
            httpx.Response(200, json=CAPS)
            if r.method == "GET"
            else httpx.Response(400, json={"error": "bad request"})
        )

    p = port(tmp_path, handler)
    with pytest.raises(HermesRunPortError):
        p._invoke(
            "submit",
            {
                "idempotency_key": "rejected",
                "request_body": {"session_id": "web_s", "input": "bad"},
            },
        )
    assert p.receipts.reserve("next", {"session_id": "web_s", "input": "valid"}, 86400) == {
        "run_id": None
    }


def test_ambiguous_transport_failure_keeps_session_blocked(tmp_path):
    receipts = NativeReceipts(tmp_path / "native.sqlite3")
    receipts.reserve("first", {"session_id": "web_s", "input": "first"}, 86400)
    with pytest.raises(HermesRunPortError) as error:
        receipts.reserve("next", {"session_id": "web_s", "input": "next"}, 86400)
    assert error.value.code == "session_busy"
