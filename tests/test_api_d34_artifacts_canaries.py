from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import CSRF_HEADER_NAME, issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)

ORIGIN = "http://127.0.0.1:3001"


class _Registry:
    def list_artifacts(self, *, workspace_id: str, limit: int):
        assert (workspace_id, limit) == ("default", 20)
        return [
            {
                "contract": "hqa.d34_artifact/v1",
                "artifact_id": "artifact-test-1",
                "mandate_id": "mandate-test-1",
                "workspace_id": "default",
                "status": "canary_active",
                "qualification_scope": "paper_only",
                "policy_digest": "a" * 64,
                "snapshot_digest": "b" * 64,
                "candidate_code_digest": "c" * 64,
                "qlib_config_digest": "d" * 64,
                "rdagent_commit": "1" * 40,
                "qlib_commit": "2" * 40,
                "docker_image_digest": "sha256:" + "3" * 64,
                "qlib_receipt_digest": "4" * 64,
                "platform_receipt_digest": "5" * 64,
                "comparison_digest": "6" * 64,
                "policy_decision_id": "decision-test-1",
                "created_at": datetime(2026, 8, 11, tzinfo=UTC),
                "updated_at": datetime(2026, 8, 11, tzinfo=UTC),
                "version": 2,
            }
        ]

    def list_canaries(self, *, workspace_id: str, limit: int):
        assert (workspace_id, limit) == ("default", 20)
        return [
            {
                "contract": "hqa.d34_canary/v1",
                "canary_id": "canary-test-1",
                "artifact_id": "artifact-test-1",
                "mandate_id": "mandate-test-1",
                "workspace_id": "default",
                "sleeve_id": "sleeve-d34-test-1",
                "status": "running",
                "allocated_cash": "1000.00",
                "nav_fraction": "0.010000",
                "daily_pnl": "0.00",
                "drawdown_fraction": "0.000000",
                "created_at": datetime(2026, 8, 11, tzinfo=UTC),
                "updated_at": datetime(2026, 8, 11, tzinfo=UTC),
                "version": 1,
            }
        ]


class _Controller:
    def __init__(self) -> None:
        self.calls = []

    def transition(self, *, canary_id, action, expected_version, reason):
        self.calls.append((canary_id, action, expected_version, reason))
        return {
            "contract": "hqa.d34_canary/v1",
            "canary_id": canary_id,
            "artifact_id": "artifact-test-1",
            "mandate_id": "mandate-test-1",
            "workspace_id": "default",
            "sleeve_id": "sleeve-d34-test-1",
            "status": "paused" if action == "pause" else "demoted",
            "allocated_cash": "1000.00",
            "nav_fraction": "0.010000",
            "daily_pnl": "0.00",
            "drawdown_fraction": "0.000000",
            "created_at": datetime(2026, 8, 11, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 11, tzinfo=UTC),
            "version": expected_version + 1,
        }

    def rollback_all(self, *, workspace_id, reason):
        self.calls.append((workspace_id, "rollback", None, reason))
        return {"transitioned": 1, "canary_ids": ["canary-test-1"]}

def _headers() -> dict[str, str]:
    return {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin", "Host": "testserver"}


def test_owner_reads_d34_artifacts_and_real_canaries(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            hermes_gateway=HermesGatewaySettings(enabled=False), api_cors_origins=[ORIGIN]
        ),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    app.state.services["d34_registry_authority"] = _Registry()
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    assert bootstrap.status_code == 200

    artifacts = client.get("/api/hermes/d34/artifacts?workspace_id=default", headers=_headers())
    canaries = client.get("/api/hermes/canaries?workspace_id=default", headers=_headers())

    assert artifacts.status_code == 200, artifacts.text
    assert artifacts.json()["items"][0]["qualification_scope"] == "paper_only"
    assert artifacts.json()["items"][0]["comparison_digest"] == "6" * 64
    assert canaries.status_code == 200, canaries.text
    assert canaries.json()["items"][0]["sleeve_id"] == "sleeve-d34-test-1"
    assert canaries.json()["items"][0]["status"] == "running"


def test_owner_pauses_demotes_and_rolls_back_d34_canaries(tmp_path: Path) -> None:
    app = create_app(
        settings=Settings(
            hermes_gateway=HermesGatewaySettings(enabled=False),
            local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
            api_cors_origins=[ORIGIN],
        ),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    controller = _Controller()
    app.state.services["d34_canary_controller"] = controller
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    csrf = str(bootstrap.json()["csrf_token"])
    headers = {**_headers(), CSRF_HEADER_NAME: csrf}

    paused = client.post(
        "/api/hermes/canaries/canary-test-1/pause",
        json={"expected_version": 1, "reason": "owner pause"},
        headers=headers,
    )
    demoted = client.post(
        "/api/hermes/canaries/canary-test-1/demote",
        json={"expected_version": 2, "reason": "quality degraded"},
        headers=headers,
    )
    rolled_back = client.post(
        "/api/hermes/d34/rollback",
        json={"workspace_id": "default", "reason": "return to D-33"},
        headers=headers,
    )

    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["status"] == "demoted"
    assert rolled_back.status_code == 200, rolled_back.text
    assert {
        key: value
        for key, value in rolled_back.json().items()
        if key != "safety"
    } == {
        "contract": "hqa.d34_rollback/v1",
        "transitioned": 1,
        "canary_ids": ["canary-test-1"],
    }
    assert controller.calls == [
        ("canary-test-1", "pause", 1, "owner pause"),
        ("canary-test-1", "demote", 2, "quality degraded"),
        ("default", "rollback", None, "return to D-33"),
    ]
