import sys
from pathlib import Path

from fastapi.testclient import TestClient

import quant_system.api.routes.agent as agent_routes
from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.llm.stub import StubLLMClient
from quant_system.api.server import create_app


def _agent_app(tmp_path, *, agent=None, general=None):
    agent_root = agent if agent is not None else tmp_path / "agent-output"
    general_root = general if general is not None else tmp_path / "general"
    return agent_root, TestClient(
        create_app(output_dir=general_root, agent_output_dir=agent_root)
    )


def test_agent_api_uses_injected_agent_output_dir_not_general_data_dir(tmp_path) -> None:
    general = tmp_path / "general"
    agent = tmp_path / "agent-output"
    artifact = CandidatePool(agent).write_candidate(
        task_id="task-root-contract",
        goal="root contract",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# candidate\n",
    )

    client = TestClient(create_app(output_dir=general, agent_output_dir=agent))
    payload = client.get("/api/agent/candidates").json()

    assert [item["candidate_id"] for item in payload["candidates"]] == [
        artifact.candidate_id
    ]
    assert not (general / "agent" / "candidates").exists()


def test_agent_task_writes_candidate_and_audit_only_to_injected_agent_root(
    tmp_path, monkeypatch
) -> None:
    general = tmp_path / "general"
    agent = tmp_path / "agent-output"
    monkeypatch.setattr(agent_routes, "build_llm_client", lambda _settings: StubLLMClient())
    client = TestClient(create_app(output_dir=general, agent_output_dir=agent))

    response = client.post(
        "/api/agent/tasks",
        json={
            "task_type": "propose-factor",
            "goal": "root contract",
            "universe": ["SPY"],
        },
    )

    assert response.status_code == 200
    assert list((agent / "agent" / "candidates").glob("*/metadata.json"))
    assert list((agent / "agent" / "audit").glob("*.jsonl"))
    assert not (general / "agent").exists()


def test_agent_candidate_list_detail_and_review_do_not_import_source(tmp_path) -> None:
    agent, client = _agent_app(tmp_path)
    pool = CandidatePool(agent)
    artifact = pool.write_candidate(
        task_id="task-001",
        goal="malicious candidate",
        artifact_type="factor",
        filename="factor.py.candidate",
        content='import os\nos.system("echo should-not-run")\n',
    )
    before_modules = set(sys.modules)

    list_response = client.get("/api/agent/candidates", params={"status": "pending"})
    assert list_response.status_code == 200
    assert artifact.candidate_id in {
        item["candidate_id"] for item in list_response.json()["candidates"]
    }

    detail_response = client.get(f"/api/agent/candidates/{artifact.candidate_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert 'os.system("echo should-not-run")' in detail["source_preview"]
    assert set(sys.modules) == before_modules

    review_response = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={"decision": "approve", "note": "manual review only"},
    )
    assert review_response.status_code == 200
    assert Path(agent, "agent", "candidates", artifact.candidate_id, "approved.lock").exists()
    assert set(sys.modules) == before_modules


def test_agent_tasks_propose_factor(tmp_path) -> None:
    _, client = _agent_app(tmp_path)

    response = client.post(
        "/api/agent/tasks",
        json={
            "task_type": "propose-factor",
            "goal": "low-vol momentum",
            "universe": ["SPY", "QQQ"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"]
    assert payload["metadata"]["safety"]["auto_promotion"] is False


def test_agent_task_rejects_unknown_type(tmp_path) -> None:
    _, client = _agent_app(tmp_path)

    response = client.post("/api/agent/tasks", json={"task_type": "submit-order"})

    assert response.status_code == 422
    assert response.json()["safety"]["live_trading_enabled"] is False


def test_agent_candidate_detail_rejects_path_traversal(tmp_path) -> None:
    _, client = _agent_app(tmp_path)

    response = client.get("/api/agent/candidates/..%2Foutside")

    assert response.status_code == 404
    assert response.json()["safety"]["dry_run"] is True


def test_agent_candidate_review_404_uses_standard_detail(tmp_path) -> None:
    _, client = _agent_app(tmp_path)

    response = client.post(
        "/api/agent/candidates/missing-candidate/review",
        json={"decision": "reject", "note": "not found"},
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "not_found"
    assert detail["resource"] == "agent_candidate"
    assert detail["id"] == "missing-candidate"


def test_agent_candidates_list_returns_latest_first(tmp_path) -> None:
    agent, client = _agent_app(tmp_path)
    pool = CandidatePool(agent)
    first = pool.write_candidate(
        task_id="task-001",
        goal="first",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# first\n",
    )
    second = pool.write_candidate(
        task_id="task-002",
        goal="second",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# second\n",
    )

    response = client.get("/api/agent/candidates")

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidates"][0]["candidate_id"] == second.candidate_id
    assert payload["candidates"][1]["candidate_id"] == first.candidate_id
