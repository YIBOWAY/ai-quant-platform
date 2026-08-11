from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import HermesGatewaySettings, Settings

ORIGIN = "http://127.0.0.1:3001"


class _Jobs:
    def list(self, *, workspace_id: str, limit: int, state: str | None):
        assert workspace_id == "default"
        assert limit == 20
        assert state is None
        now = datetime(2026, 8, 11, tzinfo=UTC)
        return [
            {
                "contract": "hqa.d34_experiment_job/v1",
                "job_id": "job-test-1",
                "mandate_id": "mandate-test-1",
                "workspace_id": "default",
                "job_key": "mandate-test-1:cycle:1",
                "state": "running",
                "attempt_count": 1,
                "max_attempts": 3,
                "input_digest": "a" * 64,
                "lease_owner": "launchagent-local",
                "lease_expires_at": now,
                "heartbeat_at": now,
                "budget_reserved_usd": "10.000000",
                "budget_spent_usd": "0.000000",
                "created_at": now,
                "updated_at": now,
                "version": 2,
                "outcome_code": None,
            }
        ]


def _headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "Host": "testserver",
    }


def test_owner_reads_durable_d34_research_jobs(tmp_path: Path) -> None:
    settings = Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        api_cors_origins=[ORIGIN],
    )
    app = create_app(settings=settings, output_dir=tmp_path, bind_address="127.0.0.1")
    app.state.services["d34_job_authority"] = _Jobs()
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    assert bootstrap.status_code == 200

    response = client.get(
        "/api/hermes/research/jobs?workspace_id=default",
        headers=_headers(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["contract"] == "hqa.d34_experiment_job-list/v1"
    assert response.json()["items"][0]["state"] == "running"
    assert response.json()["items"][0]["lease_owner"] == "launchagent-local"
