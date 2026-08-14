from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import HermesGatewaySettings, Settings, reload_settings
from quant_system.hermes.d34_job_authority import JobAuthorityError
from quant_system.hermes.d34_mandate_authority import MandateAuthorityError

ORIGIN = "http://127.0.0.1:3002"


class _ContractJobs:
    def __init__(self) -> None:
        self.commands: list[object] = []

    def list(self, *, workspace_id: str, limit: int, state: str | None):
        _ = workspace_id, state
        if not 1 <= limit <= 100:
            raise JobAuthorityError(
                "d34_job_validation", "research job query is invalid"
            )
        return [
            {"job_key": command.job_key, "state": "running"}
            for command in self.commands
        ]

    def enqueue(self, command):
        self.commands.append(command)
        return command


class _ActiveMandates:
    def get_active(self, *, workspace_id: str):
        now = datetime(2026, 8, 14, tzinfo=UTC)
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


def _headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "Host": "testserver",
    }


def _client(tmp_path: Path, monkeypatch, *, jobs=None, mandates=None) -> TestClient:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    settings = reload_settings()
    settings = settings.model_copy(
        update={
            "hermes_gateway": HermesGatewaySettings(enabled=False),
            "api_cors_origins": [ORIGIN],
        }
    )
    app = create_app(settings=settings, output_dir=tmp_path, bind_address="127.0.0.1")
    if mandates is not None:
        app.state.services["d34_mandate_authority"] = mandates
    if jobs is not None:
        app.state.services["d34_job_authority"] = jobs
    return TestClient(app)


def test_book_reconcile_uses_job_authority_list_limit(tmp_path: Path, monkeypatch) -> None:
    jobs = _ContractJobs()
    client = _client(tmp_path, monkeypatch, jobs=jobs, mandates=_ActiveMandates())

    dispatched = client.post(
        "/api/assistant/remote/dispatch",
        json={"objective": "扩宇宙：横截面动量重验", "hang_if_pass": False},
        headers=_headers(),
    )
    assert dispatched.status_code == 200, dispatched.text
    assert dispatched.json()["mode"] == "d34_job"

    book = client.get("/api/assistant/remote/book", headers=_headers())
    assert book.status_code == 200, book.text
    assert book.json()["requests"][0]["status"] == "running"


def test_dispatch_does_not_arm_worker_hang_if_pass(tmp_path: Path, monkeypatch) -> None:
    jobs = _ContractJobs()
    client = _client(tmp_path, monkeypatch, jobs=jobs, mandates=_ActiveMandates())

    response = client.post(
        "/api/assistant/remote/dispatch",
        json={"objective": "扩宇宙：横截面动量重验", "hang_if_pass": True},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["hang_if_pass"] is True
    assert len(jobs.commands) == 1
    assert jobs.commands[0].input_document["hang_if_pass"] is False


def test_dispatch_mandate_unavailable_is_not_book_only(tmp_path: Path, monkeypatch) -> None:
    class _DownMandates:
        def get_active(self, *, workspace_id: str):
            raise MandateAuthorityError(
                "d34_mandate_unavailable", "D-34 mandate authority is unavailable"
            )

    client = _client(tmp_path, monkeypatch, jobs=_ContractJobs(), mandates=_DownMandates())
    response = client.post(
        "/api/assistant/remote/dispatch",
        json={"objective": "扩宇宙：横截面动量重验"},
        headers=_headers(),
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "d34_mandate_unavailable"


def test_dispatch_without_mandate_stays_book_only(tmp_path: Path, monkeypatch) -> None:
    class _EmptyMandates:
        def get_active(self, *, workspace_id: str):
            return None

    client = _client(tmp_path, monkeypatch, jobs=_ContractJobs(), mandates=_EmptyMandates())
    response = client.post(
        "/api/assistant/remote/dispatch",
        json={"objective": "book-only opinion request"},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "book_only"
    assert response.json()["job_key"] is None
