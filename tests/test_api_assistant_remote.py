from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import CSRF_HEADER_NAME, issue_bootstrap_token
from quant_system.api.server import create_app
from quant_system.config.settings import (
    HermesGatewaySettings,
    LocalMutationSettings,
    reload_settings,
)
from quant_system.execution.account_repository_factory import (
    build_paper_account_repository,
)
from quant_system.hermes.d34_job_authority import JobAuthorityError
from tests.test_assistant_remote import _record_strong_hang_candidate

ORIGIN = "http://127.0.0.1:3002"


class _ContractJobs:
    def __init__(self) -> None:
        self.commands: list[object] = []
        self.list_calls = 0

    def list(self, *, workspace_id: str, limit: int, state: str | None):
        self.list_calls += 1
        _ = workspace_id, state
        if not 1 <= limit <= 100:
            raise JobAuthorityError("d34_job_validation", "research job query is invalid")
        return [{"job_key": command.job_key, "state": "running"} for command in self.commands]

    def enqueue(self, command):
        self.commands.append(command)
        return {
            "job_id": "job-api-chat-research",
            "job_key": command.job_key,
        }


def _headers() -> dict[str, str]:
    return {
        "Origin": ORIGIN,
        "Sec-Fetch-Site": "same-origin",
        "Host": "testserver",
    }


def _research_body(**overrides) -> dict[str, object]:
    remaining = dict(overrides)
    material = {
        "note": remaining.pop("note", "Research the supplied twenty-day reversal formula"),
        "formula": remaining.pop("formula", "Ref($close, 20) / $close - 1"),
        "universe": remaining.pop("universe", ["SPY", "QQQ"]),
    }
    material_digest = hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    body = {
        "material_digest": material_digest,
        "command_id": "command-api-chat",
        "platform_session_id": "platform-session-api-chat",
        "hermes_session_id": "hermes-session-api-chat",
        "hermes_run_id": "hermes-run-api-chat",
        **material,
        **remaining,
    }
    body.setdefault(
        "operation_id",
        hashlib.sha256(
            json.dumps(
                {
                    "contract": "hqa.chat_research_operation/v1",
                    "hermes_session_id": body["hermes_session_id"],
                    "material_digest": body["material_digest"],
                    "platform_session_id": body["platform_session_id"],
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    )
    return body


def _client(tmp_path: Path, monkeypatch, *, jobs=None) -> TestClient:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("QS_PAPER_ACCOUNT_DB_MODE", "file")
    settings = reload_settings()
    settings = settings.model_copy(
        update={
            "hermes_gateway": HermesGatewaySettings(enabled=False),
            "local_mutation": LocalMutationSettings(enabled=True, composer_open=True),
            "api_cors_origins": [ORIGIN],
        }
    )
    app = create_app(settings=settings, output_dir=tmp_path, bind_address="127.0.0.1")
    if jobs is not None:
        app.state.services["d34_job_authority"] = jobs
    client = TestClient(app)
    bootstrap = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": issue_bootstrap_token(tmp_path)},
        headers=_headers(),
    )
    assert bootstrap.status_code == 200, bootstrap.text
    client.app.state._assistant_remote_test_csrf = str(bootstrap.json()["csrf_token"])
    return client


def _mutation_headers(client: TestClient) -> dict[str, str]:
    return {
        **_headers(),
        CSRF_HEADER_NAME: client.app.state._assistant_remote_test_csrf,
    }


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@pytest.mark.parametrize(
    "path",
    [
        "/api/assistant/remote/dispatch",
        "/api/assistant/remote/intake",
        "/api/hermes/mandates",
        "/api/hermes/mandates/active",
        "/api/hermes/research/requests",
        "/api/hermes/research/jobs",
        "/api/hermes/d34/artifacts",
        "/api/hermes/canaries",
        "/api/hermes/d34/rollback",
    ],
)
def test_retired_remote_urls_are_absent_and_zero_write(
    tmp_path: Path,
    monkeypatch,
    path: str,
) -> None:
    jobs = _ContractJobs()
    client = _client(tmp_path, monkeypatch, jobs=jobs)
    before = _tree_digest(tmp_path)

    post = client.post(path, json={"objective": "retired"}, headers=_mutation_headers(client))
    get = client.get(path, headers=_headers())

    assert post.status_code in {404, 405}
    assert get.status_code in {404, 405}
    assert jobs.commands == []
    assert _tree_digest(tmp_path) == before


def test_book_get_is_projection_only_and_byte_stable(tmp_path: Path, monkeypatch) -> None:
    jobs = _ContractJobs()
    client = _client(tmp_path, monkeypatch, jobs=jobs)

    queued = client.post(
        "/api/assistant/remote/research",
        json=_research_body(),
        headers=_mutation_headers(client),
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["status"] == "queued"
    assert "hang_if_pass" not in jobs.commands[0].input_document

    book_path = tmp_path / "assistant_remote" / "book.json"
    before = book_path.read_bytes()
    list_calls = jobs.list_calls
    for _ in range(2):
        book = client.get("/api/assistant/remote/book", headers=_headers())
        assert book.status_code == 200, book.text
        assert book.json()["requests"][0]["status"] == "queued"
        assert "hang_if_pass" not in book.json()["requests"][0]
    assert jobs.list_calls == list_calls
    assert book_path.read_bytes() == before


def test_book_unavailable_is_typed_503_not_an_empty_or_running_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from quant_system.api.routes import assistant_remote as route_module

    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        route_module,
        "project_book",
        lambda _settings: (_ for _ in ()).throw(OSError("book unavailable")),
    )

    response = client.get("/api/assistant/remote/book", headers=_headers())

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "remote_book_unavailable"


def test_research_operation_replay_is_one_request_and_one_job(
    tmp_path: Path,
    monkeypatch,
) -> None:
    jobs = _ContractJobs()
    client = _client(tmp_path, monkeypatch, jobs=jobs)

    first = client.post(
        "/api/assistant/remote/research",
        json=_research_body(),
        headers=_mutation_headers(client),
    )
    second = client.post(
        "/api/assistant/remote/research",
        json=_research_body(),
        headers=_mutation_headers(client),
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["status"] == "queued"
    assert first.json()["terminal"] is False
    assert first.json()["outcome"] == "queued"
    assert first.json()["result_reply"] == {
        "status": "queued",
        "code": "research_queued",
        "message": "Research request queued.",
        "provenance": {
            "operation_id": first.json()["operation_id"],
            "material_digest": first.json()["material_digest"],
            "job_id": "job-api-chat-research",
            "job_key": f"assistant-remote:{first.json()['operation_id']}",
        },
    }
    assert len(jobs.commands) == 1
    book = client.get("/api/assistant/remote/book", headers=_headers()).json()
    assert len(book["requests"]) == 1
    assert "objective" not in book["requests"][0]
    assert "formula" not in book["requests"][0]
    assert "universe" not in book["requests"][0]
    book_path = tmp_path / "assistant_remote" / "book.json"
    before = book_path.read_bytes()

    projection = client.get(
        f"/api/assistant/remote/request/{first.json()['operation_id']}",
        headers=_headers(),
    )

    assert projection.status_code == 200
    assert projection.json() == first.json()
    assert book_path.read_bytes() == before


def test_research_operation_is_session_idempotent_across_command_attempts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    jobs = _ContractJobs()
    client = _client(tmp_path, monkeypatch, jobs=jobs)
    first_body = _research_body()
    second_body = _research_body(
        command_id="command-api-chat-2",
        hermes_run_id="hermes-run-api-chat-2",
    )

    first = client.post(
        "/api/assistant/remote/research",
        json=first_body,
        headers=_mutation_headers(client),
    )
    second = client.post(
        "/api/assistant/remote/research",
        json=second_body,
        headers=_mutation_headers(client),
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["operation_id"] == second.json()["operation_id"]
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["command_id"] == "command-api-chat-2"
    assert second.json()["hermes_run_id"] == "hermes-run-api-chat-2"
    assert len(jobs.commands) == 1
    assert jobs.commands[0].max_attempts == 1
    assert jobs.commands[0].input_document["research_only"] is True
    assert jobs.commands[0].input_document["paper_execution_allowed"] is False
    assert len(client.get("/api/assistant/remote/book", headers=_headers()).json()["requests"]) == 1


def test_research_operation_uses_fixed_resource_and_request_universe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    jobs = _ContractJobs()
    client = _client(tmp_path, monkeypatch, jobs=jobs)

    response = client.post(
        "/api/assistant/remote/research",
        json=_research_body(universe=["NVDA", "AAPL"]),
        headers=_mutation_headers(client),
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    command = jobs.commands[0]
    assert command.resource_envelope_id == "local-paper-research-v1"
    assert command.input_document["universe"] == ["NVDA", "AAPL"]
    assert "mandate_id" not in command.input_document
    assert "cycle_date" not in command.input_document


def test_research_operation_rejects_operation_id_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:

    operation_jobs = _ContractJobs()
    operation_client = _client(
        tmp_path,
        monkeypatch,
        jobs=operation_jobs,
    )
    operation_mismatch = operation_client.post(
        "/api/assistant/remote/research",
        json=_research_body(operation_id="f" * 64),
        headers=_mutation_headers(operation_client),
    )

    assert operation_mismatch.status_code == 409
    assert operation_mismatch.json()["detail"]["code"] == "research_operation_id_mismatch"
    assert operation_jobs.commands == []
    assert not (tmp_path / "assistant_remote" / "book.json").exists()


def test_remote_hang_insufficient_funds_is_typed_not_server_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    settings = reload_settings()
    repository = build_paper_account_repository(
        tmp_path / "api_runs",
        settings=settings,
    )
    repository.reset(initial_cash=5_000.0)
    candidate_id = "candidate-api-insufficient-hang-cash"
    _record_strong_hang_candidate(
        settings,
        tmp_path,
        candidate_id=candidate_id,
    )

    candidate = client.get(
        "/api/assistant/remote/book",
        headers=_headers(),
    ).json()["candidates"][0]

    response = client.post(
        "/api/assistant/remote/hang",
        json={
            "candidate_id": candidate_id,
            "expected_source_digest": candidate["source_digest"],
        },
        headers=_mutation_headers(client),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "hang_insufficient_funds",
        "message": "hang_insufficient_funds",
    }


@pytest.mark.parametrize(
    "error_code",
    [
        "hang_account_outcome_unknown",
        "hang_recovery_sleeve_outcome_unknown",
        "hang_sleeve_persist_failed",
    ],
)
def test_remote_hang_persistence_uncertainty_is_typed_503_without_retry(
    tmp_path: Path,
    monkeypatch,
    error_code: str,
) -> None:
    from quant_system.api.routes import assistant_remote as route_module
    from quant_system.execution.assistant_remote import AssistantRemoteError

    client = _client(tmp_path, monkeypatch)
    calls = 0

    def uncertain(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssistantRemoteError(error_code)

    monkeypatch.setattr(route_module, "hang_candidate", uncertain)

    response = client.post(
        "/api/assistant/remote/hang",
        json={
            "candidate_id": "candidate-unknown",
            "expected_source_digest": "a" * 64,
        },
        headers=_mutation_headers(client),
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": error_code,
        "message": "Hang outcome is unknown; refresh the book before any retry.",
        "outcome": "outcome_unknown",
        "retryable": False,
        "recovery_action": "refresh_remote_book",
    }
    assert calls == 1


def test_remote_hang_requires_expected_digest_and_forbids_extra_fields(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)

    missing = client.post(
        "/api/assistant/remote/hang",
        json={"candidate_id": "candidate-one"},
        headers=_headers(),
    )
    extra = client.post(
        "/api/assistant/remote/hang",
        json={
            "candidate_id": "candidate-one",
            "expected_source_digest": "a" * 64,
            "allocation_cash": 1,
        },
        headers=_headers(),
    )

    assert missing.status_code == 422
    assert extra.status_code == 422


def test_new_research_and_hang_mutations_require_owner_csrf_without_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    research_jobs = _ContractJobs()
    research_client = _client(
        tmp_path / "research",
        monkeypatch,
        jobs=research_jobs,
    )

    missing_research_csrf = research_client.post(
        "/api/assistant/remote/research",
        json=_research_body(),
        headers=_headers(),
    )
    invalid_research_csrf = research_client.post(
        "/api/assistant/remote/research",
        json=_research_body(),
        headers={**_headers(), CSRF_HEADER_NAME: "invalid"},
    )

    assert missing_research_csrf.status_code == 403
    assert invalid_research_csrf.status_code == 403
    assert research_jobs.commands == []
    assert not (tmp_path / "research" / "assistant_remote" / "book.json").exists()

    hang_client = _client(tmp_path / "hang", monkeypatch)
    hang_settings = reload_settings()
    candidate_id = "candidate-security-hang"
    _record_strong_hang_candidate(
        hang_settings,
        tmp_path / "hang",
        candidate_id=candidate_id,
    )
    candidate = hang_client.get(
        "/api/assistant/remote/book",
        headers=_headers(),
    ).json()["candidates"][0]
    book_path = tmp_path / "hang" / "assistant_remote" / "book.json"
    before = book_path.read_bytes()
    body = {
        "candidate_id": candidate_id,
        "expected_source_digest": candidate["source_digest"],
    }

    missing_hang_csrf = hang_client.post(
        "/api/assistant/remote/hang",
        json=body,
        headers=_headers(),
    )
    invalid_hang_csrf = hang_client.post(
        "/api/assistant/remote/hang",
        json=body,
        headers={**_headers(), CSRF_HEADER_NAME: "invalid"},
    )

    assert missing_hang_csrf.status_code == 403
    assert invalid_hang_csrf.status_code == 403
    assert book_path.read_bytes() == before
    assert not (tmp_path / "hang" / "api_runs").exists()
