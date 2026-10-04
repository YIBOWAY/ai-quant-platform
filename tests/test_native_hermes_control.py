from datetime import UTC, datetime

import pytest

from quant_system.hermes import native_control
from quant_system.hermes.gateway_client import HermesRunControlError


class Client:
    def __init__(self):
        self.raw = {
            "run_id": "run_one",
            "status": "waiting_for_approval",
            "session_id": "web_one",
            "approval": {
                "request_id": "request_one",
                "timestamp": datetime.now(UTC).timestamp(),
                "command": "echo review",
            },
        }
        self.posts = []

    def _get_json(self, path):
        return self.raw

    def _post_json(self, path, body):
        self.posts.append((path, body))
        if path.endswith("/stop"):
            return {"status": "stopping"}
        return {"run_id": "run_one", "resolved": 1, "choice": body["choice"]}


def test_native_approval_binds_real_request_id_and_reports_accepted():
    client = Client()
    row = native_control.pending(client, ("run_one",))[0]
    assert row["validity_source"] == "platform_review_window"
    result = native_control.approve(
        client,
        "run_one",
        choice="once",
        challenge_id=row["approval_id"],
        action_digest=row["digest"],
        expected_status="pending",
        expected_expires_at=row["expires_at"],
    )
    assert client.posts[0][1] == {"choice": "once", "request_id": "request_one"}
    assert result.decision_status == "accepted"  # not a private durable commitment
    assert result.resolved == 1


def test_native_approval_rejects_changed_action_without_post():
    client = Client()
    row = native_control.pending(client, ("run_one",))[0]
    client.raw["approval"]["request_id"] = "request_two"
    with pytest.raises(HermesRunControlError):
        native_control.approve(
            client,
            "run_one",
            choice="once",
            challenge_id=row["approval_id"],
            action_digest=row["digest"],
            expected_status="pending",
            expected_expires_at=row["expires_at"],
        )
    assert client.posts == []


def test_native_stop_does_not_claim_executor_has_exited():
    client = Client()
    result = native_control.stop(client, "run_one")
    assert result.status == "running"
    client.raw["status"] = "cancelled"
    result = native_control.stop(client, "run_one")
    assert result.status == "stopped"
    assert len(client.posts) == 1
