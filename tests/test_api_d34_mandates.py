from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


class _MandateAuthority:
    def __init__(self) -> None:
        self.active: dict[str, object] | None = None

    def create(self, command: object) -> dict[str, object]:
        now = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
        body = command.model_dump()
        self.active = {
            "contract": "hqa.mandate/v1",
            "mandate_id": "mandate-test-1",
            "owner_user_id": str(body["owner_user_id"]),
            "workspace_id": body["workspace_id"],
            "status": "active",
            "universe": body["universe"],
            "hypotheses_per_cycle": body["hypotheses_per_cycle"],
            "max_iterations": body["max_iterations"],
            "max_experiments_per_iteration": body["max_experiments_per_iteration"],
            "max_concurrent_jobs": body["max_concurrent_jobs"],
            "llm_budget_usd": body["llm_budget_usd"],
            "llm_warning_fraction": body["llm_warning_fraction"],
            "paper_execution_allowed": body["paper_execution_allowed"],
            "policy_digest": "a" * 64,
            "created_at": now,
            "starts_at": now,
            "expires_at": now + timedelta(days=30),
            "updated_at": now,
            "version": 1,
        }
        return self.active

    def get_active(self, *, workspace_id: str) -> dict[str, object] | None:
        if self.active is None or self.active["workspace_id"] != workspace_id:
            return None
        return self.active

    def list(self, *, workspace_id: str, limit: int) -> list[dict[str, object]]:
        _ = limit
        if self.active is None or self.active["workspace_id"] != workspace_id:
            return []
        return [self.active]

    def transition(
        self,
        *,
        mandate_id: str,
        action: str,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        assert self.active is not None
        assert self.active["mandate_id"] == mandate_id
        assert self.active["version"] == expected_version
        assert reason
        self.active["status"] = {
            "pause": "paused",
            "resume": "active",
            "revoke": "revoked",
        }[action]
        self.active["version"] = expected_version + 1
        return self.active

    def renew(
        self,
        *,
        mandate_id: str,
        duration_days: int,
        expected_version: int,
        reason: str,
    ) -> dict[str, object]:
        assert self.active is not None
        assert self.active["mandate_id"] == mandate_id
        assert self.active["version"] == expected_version
        assert duration_days == 30
        assert reason
        expires_at = self.active["expires_at"]
        assert isinstance(expires_at, datetime)
        self.active["expires_at"] = expires_at + timedelta(days=duration_days)
        self.active["version"] = expected_version + 1
        return self.active


def _headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "Host": "testserver",
    }


def _client(tmp_path: Path) -> tuple[TestClient, str]:
    settings = Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=True, composer_open=True),
        api_cors_origins=[ORIGIN, "http://127.0.0.1:3000", "http://localhost:3001"],
    )
    app = create_app(
        settings=settings,
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    app.state.services["d34_mandate_authority"] = _MandateAuthority()
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    assert bootstrap.status_code == 200, bootstrap.text
    return client, str(bootstrap.json()["csrf_token"])


def test_owner_creates_and_reads_active_d34_mandate(tmp_path: Path) -> None:
    client, csrf = _client(tmp_path)
    response = client.post(
        "/api/hermes/mandates",
        json={
            "workspace_id": "default",
            "duration_days": 30,
            "universe": ["SPY", "QQQ", "IWM", "DIA"],
            "hypotheses_per_cycle": 1,
            "max_iterations": 3,
            "max_experiments_per_iteration": 3,
            "max_concurrent_jobs": 1,
            "llm_budget_usd": "100.00",
            "llm_warning_fraction": "0.80",
            "paper_execution_allowed": True,
        },
        headers={**_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert response.status_code == 201, response.text
    mandate = response.json()
    assert mandate["contract"] == "hqa.mandate/v1"
    assert mandate["status"] == "active"
    assert mandate["paper_execution_allowed"] is True
    assert mandate["universe"] == ["SPY", "QQQ", "IWM", "DIA"]
    assert mandate["llm_budget_usd"] == "100.00"

    active = client.get(
        "/api/hermes/mandates/active?workspace_id=default",
        headers=_headers(),
    )
    assert active.status_code == 200, active.text
    assert active.json() == mandate


def test_owner_pauses_resumes_and_revokes_mandate_with_cas(tmp_path: Path) -> None:
    client, csrf = _client(tmp_path)
    created = client.post(
        "/api/hermes/mandates",
        json={"workspace_id": "default"},
        headers={**_headers(), CSRF_HEADER_NAME: csrf},
    )
    assert created.status_code == 201, created.text
    mandate_id = created.json()["mandate_id"]
    headers = {**_headers(), CSRF_HEADER_NAME: csrf}

    paused = client.post(
        f"/api/hermes/mandates/{mandate_id}/pause",
        json={"expected_version": 1, "reason": "owner pause"},
        headers=headers,
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"
    assert paused.json()["version"] == 2

    resumed = client.post(
        f"/api/hermes/mandates/{mandate_id}/resume",
        json={"expected_version": 2, "reason": "continue research"},
        headers=headers,
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "active"

    revoked = client.post(
        f"/api/hermes/mandates/{mandate_id}/revoke",
        json={"expected_version": 3, "reason": "mandate completed"},
        headers=headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    listing = client.get(
        "/api/hermes/mandates?workspace_id=default",
        headers=_headers(),
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"][0]["status"] == "revoked"


def test_owner_renews_mandate_without_recreating_policy(tmp_path: Path) -> None:
    client, csrf = _client(tmp_path)
    created = client.post(
        "/api/hermes/mandates",
        json={"workspace_id": "default", "duration_days": 30},
        headers={**_headers(), CSRF_HEADER_NAME: csrf},
    ).json()

    renewed = client.post(
        f"/api/hermes/mandates/{created['mandate_id']}/renew",
        json={"duration_days": 30, "expected_version": 1, "reason": "next cycle"},
        headers={**_headers(), CSRF_HEADER_NAME: csrf},
    )

    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["version"] == 2
    assert renewed.json()["policy_digest"] == created["policy_digest"]
    assert renewed.json()["expires_at"] > created["expires_at"]
