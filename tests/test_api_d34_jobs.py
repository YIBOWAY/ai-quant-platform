from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import (
    CSRF_HEADER_NAME,
    issue_bootstrap_token,
)
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    Settings,
)

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


class _AskJobs:
    def __init__(self) -> None:
        self.commands: list[object] = []

    def list(self, *, workspace_id: str, limit: int, state: str | None):
        _ = workspace_id, limit, state
        return []

    def enqueue(self, command):
        self.commands.append(command)
        return command


class _AskMandates:
    def get_active(self, *, workspace_id: str):
        now = datetime(2026, 8, 11, tzinfo=UTC)
        return {
            "mandate_id": "mandate-test-1",
            "workspace_id": workspace_id,
            "status": "active",
            "universe": ["SPY", "QQQ"],
            "max_iterations": 3,
            "max_experiments_per_iteration": 3,
            "llm_budget_usd": Decimal("100.00"),
            "paper_execution_allowed": True,
            "policy_digest": "a" * 64,
            "expires_at": now + timedelta(days=30),
        }


def test_owner_asks_research_without_binding_a_cycle_worker(tmp_path: Path) -> None:
    settings = Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN, "http://127.0.0.1:3000", "http://localhost:3001"],
    )
    app = create_app(settings=settings, output_dir=tmp_path, bind_address="127.0.0.1")
    jobs = _AskJobs()
    app.state.services["d34_mandate_authority"] = _AskMandates()
    app.state.services["d34_job_authority"] = jobs
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    assert bootstrap.status_code == 200, bootstrap.text
    csrf = str(bootstrap.json()["csrf_token"])

    response = client.post(
        "/api/hermes/research/requests",
        json={
            "workspace_id": "default",
            "objective": "Find a twenty-day reversal",
        },
        headers={**_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contract"] == "hqa.d34_research_request/v1"
    assert body["status"] == "queued"
    assert body["code"] == "d34_research_requested"
    assert body["job_key"].startswith("request:")
    assert len(jobs.commands) == 1
    document = jobs.commands[0].input_document
    assert document["trigger"] == "owner_request"
    assert document["objective"] == "Find a twenty-day reversal"
    assert "snapshot_id" not in document


def test_owner_cannot_ask_research_without_an_active_mandate(tmp_path: Path) -> None:
    settings = Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN, "http://127.0.0.1:3000", "http://localhost:3001"],
    )
    app = create_app(settings=settings, output_dir=tmp_path, bind_address="127.0.0.1")
    app.state.services["d34_mandate_authority"] = type(
        "_Empty", (), {"get_active": staticmethod(lambda **_kwargs: None)}
    )()
    app.state.services["d34_job_authority"] = _AskJobs()
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    csrf = str(bootstrap.json()["csrf_token"])

    response = client.post(
        "/api/hermes/research/requests",
        json={"workspace_id": "default", "objective": "Find a twenty-day reversal"},
        headers={**_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "no_active_mandate"
