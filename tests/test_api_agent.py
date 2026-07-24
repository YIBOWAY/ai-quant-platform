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
    return agent_root, TestClient(create_app(output_dir=general_root, agent_output_dir=agent_root))


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

    assert [item["candidate_id"] for item in payload["candidates"]] == [artifact.candidate_id]
    assert not (general / "agent" / "candidates").exists()


def test_agent_candidate_repository_root_failure_is_503_not_empty(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    pool = CandidatePool(agent)
    pool.candidates_dir.parent.mkdir(parents=True)
    external = tmp_path / "external-candidates"
    external.mkdir()
    pool.candidates_dir.symlink_to(external, target_is_directory=True)
    client = TestClient(create_app(agent_output_dir=agent))

    response = client.get("/api/agent/candidates")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "candidate_repository_unavailable",
        "resource": "agent_candidates",
    }


def test_agent_dangling_candidate_root_is_503_not_empty(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    pool = CandidatePool(agent)
    pool.candidates_dir.parent.mkdir(parents=True)
    pool.candidates_dir.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    client = TestClient(create_app(agent_output_dir=agent))

    response = client.get("/api/agent/candidates")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "candidate_repository_unavailable"


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
    items = list_response.json()["candidates"]
    assert artifact.candidate_id in {item["candidate_id"] for item in items}
    listed = next(item for item in items if item["candidate_id"] == artifact.candidate_id)
    assert listed["integrity_state"] == "verified"
    assert listed["manifest_digest"] == artifact.manifest_digest

    detail_response = client.get(f"/api/agent/candidates/{artifact.candidate_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert 'os.system("echo should-not-run")' in detail["source_preview"]
    assert detail["manifest_digest"] == artifact.manifest_digest
    assert set(sys.modules) == before_modules

    review_response = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "approve",
            "note": "manual review only",
            "expected_manifest_digest": artifact.manifest_digest,
            "expected_status": "pending",
        },
    )
    assert review_response.status_code == 200
    assert Path(agent, "agent", "candidates", artifact.candidate_id, "approved.lock").exists()
    assert set(sys.modules) == before_modules


def test_agent_candidate_detail_excludes_unbound_legacy_symlink_evidence(
    tmp_path,
) -> None:
    agent, client = _agent_app(tmp_path)
    pool = CandidatePool(agent)
    artifact = pool.write_candidate(
        task_id="task-safe-detail",
        goal="safe evidence only",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# safe\n",
    )
    outside_review = tmp_path / "outside-review.jsonl"
    outside_review.write_text("LOCAL_SECRET_PROOF\n", encoding="utf-8")
    (artifact.path.parent / "reviews.jsonl").symlink_to(outside_review)

    outside_audit = tmp_path / "outside-audit.jsonl"
    outside_audit.write_text(
        f'{{"candidate_id":"{artifact.candidate_id}","secret":"AUDIT_SECRET"}}\n',
        encoding="utf-8",
    )
    audit_dir = agent / "agent" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "linked.jsonl").symlink_to(outside_audit)

    response = client.get(f"/api/agent/candidates/{artifact.candidate_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["audit"] == []
    assert payload["reviews"] == []
    assert "LOCAL_SECRET_PROOF" not in response.text
    assert "AUDIT_SECRET" not in response.text


def test_agent_candidate_detail_bounds_source_preview_on_the_server(tmp_path) -> None:
    agent, client = _agent_app(tmp_path)
    artifact = CandidatePool(agent).write_candidate(
        task_id="task-bounded-preview",
        goal="bounded preview",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="x" * 65_537,
    )

    response = client.get(f"/api/agent/candidates/{artifact.candidate_id}")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["source_preview"]) == 65_536
    assert payload["evidence_truncated"] is True


def test_agent_candidate_list_uses_a_bounded_repository_scan(tmp_path, monkeypatch) -> None:
    seen: list[int | None] = []

    def bounded_list(_self, *, max_entries=None):
        seen.append(max_entries)
        return []

    monkeypatch.setattr(CandidatePool, "list_for_read", bounded_list)
    _, client = _agent_app(tmp_path)

    response = client.get("/api/agent/candidates")

    assert response.status_code == 200
    assert seen == [200]


def test_agent_review_missing_expected_status_and_stale_second_decision(tmp_path) -> None:
    agent, client = _agent_app(tmp_path)
    artifact = CandidatePool(agent).write_candidate(
        task_id="task-cas",
        goal="cas",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# cas\n",
    )
    # Missing expected_manifest_digest is validation error.
    missing_digest = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "approve",
            "note": "no digest",
            "expected_status": "pending",
        },
    )
    assert missing_digest.status_code == 422

    # Missing expected_status is validation error (no default to pending).
    missing_status = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "approve",
            "note": "no status",
            "expected_manifest_digest": artifact.manifest_digest,
        },
    )
    assert missing_status.status_code == 422

    first = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "approve",
            "note": "first",
            "expected_manifest_digest": artifact.manifest_digest,
            "expected_status": "pending",
        },
    )
    assert first.status_code == 200
    lock_path = Path(agent, "agent", "candidates", artifact.candidate_id, "approved.lock")
    first_lock_bytes = lock_path.read_bytes()
    second = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "reject",
            "note": "second",
            "expected_manifest_digest": artifact.manifest_digest,
            "expected_status": "pending",
        },
    )
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert detail["code"] == "candidate_review_state_stale"
    assert detail["resource"] == "agent_candidate"
    assert detail["id"] == artifact.candidate_id
    assert lock_path.read_bytes() == first_lock_bytes
    assert not (Path(agent, "agent", "candidates", artifact.candidate_id, "rejected.lock")).exists()


def test_candidate_review_returns_409_for_stale_digest(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="api-stale",
        goal="stale",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# candidate\n",
    )
    client = TestClient(create_app(agent_output_dir=tmp_path))
    response = client.post(
        f"/api/agent/candidates/{artifact.candidate_id}/review",
        json={
            "decision": "approve",
            "note": "reviewed",
            "expected_manifest_digest": "0" * 64,
            "expected_status": "pending",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_revision_stale"
    assert not (artifact.path.parent / "approved.lock").exists()


def test_agent_list_isolates_corrupt_and_migration_required(tmp_path) -> None:
    agent, client = _agent_app(tmp_path)
    pool = CandidatePool(agent)
    good = pool.write_candidate(
        task_id="task-good",
        goal="good",
        artifact_type="factor",
        filename="factor.py.candidate",
        content="# good\n",
    )
    legacy_dir = pool.candidates_dir / "legacy-pending"
    legacy_dir.mkdir(parents=True)
    import json

    (legacy_dir / "metadata.json").write_text(
        json.dumps(
            {
                "candidate_id": "legacy-pending",
                "task_id": "t",
                "artifact_type": "factor",
                "goal": "legacy",
                "universe": ["SPY"],
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "files": ["factor.py.candidate"],
                "safety": {
                    "auto_promotion": False,
                    "requires_human_review": True,
                    "review_status": "pending",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (legacy_dir / "factor.py.candidate").write_text("# legacy\n", encoding="utf-8")
    broken = pool.candidates_dir / "broken"
    broken.mkdir()
    (broken / "metadata.json").write_text("{not-json", encoding="utf-8")

    payload = client.get("/api/agent/candidates").json()["candidates"]
    by_id = {item["candidate_id"]: item for item in payload}
    assert by_id[good.candidate_id]["integrity_state"] == "verified"
    assert by_id["legacy-pending"]["integrity_state"] == "migration_required"
    assert by_id["legacy-pending"]["manifest_digest"] is None
    assert by_id["broken"]["integrity_state"] == "corrupt"
    assert by_id["broken"]["status"] is None

    mig = client.post(
        "/api/agent/candidates/legacy-pending/review",
        json={
            "decision": "approve",
            "note": "migrate?",
            "expected_manifest_digest": by_id["legacy-pending"]["observed_manifest_digest"],
            "expected_status": "pending",
        },
    )
    assert mig.status_code == 409
    assert mig.json()["detail"]["code"] == "candidate_migration_required"

    # Migration detail remains readable with observed digest + source preview;
    # approval stays disabled. Corrupt has no source/digest.
    legacy_detail = client.get("/api/agent/candidates/legacy-pending").json()
    assert legacy_detail["integrity_state"] == "migration_required"
    assert legacy_detail["manifest_digest"] is None
    assert len(legacy_detail["observed_manifest_digest"]) == 64
    assert legacy_detail["approval_enabled"] is False
    assert "# legacy" in (legacy_detail.get("source_preview") or "")

    broken_detail = client.get("/api/agent/candidates/broken").json()
    assert broken_detail["integrity_state"] == "corrupt"
    assert broken_detail["source_preview"] is None
    assert broken_detail["manifest_digest"] is None
    assert broken_detail["observed_manifest_digest"] is None
    assert broken_detail["approval_enabled"] is False


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
    assert payload["manifest_digest"]


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
        json={
            "decision": "reject",
            "note": "not found",
            "expected_manifest_digest": "0" * 64,
            "expected_status": "pending",
        },
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "not_found"
    assert detail["resource"] == "agent_candidate"
    assert detail["id"] == "missing-candidate"


def test_unversioned_candidate_is_readable_but_review_is_disabled(tmp_path) -> None:
    import json

    candidates = tmp_path / "agent" / "candidates"
    candidates.mkdir(parents=True)
    legacy = candidates / "legacy-pending"
    legacy.mkdir()
    (legacy / "metadata.json").write_text(
        json.dumps(
            {
                "candidate_id": "legacy-pending",
                "task_id": "t",
                "artifact_type": "factor",
                "goal": "legacy",
                "universe": ["SPY"],
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "files": ["factor.py.candidate"],
                "safety": {
                    "auto_promotion": False,
                    "requires_human_review": True,
                    "review_status": "pending",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (legacy / "factor.py.candidate").write_text("# candidate\n", encoding="utf-8")
    client = TestClient(create_app(agent_output_dir=tmp_path))

    item = client.get("/api/agent/candidates").json()["candidates"][0]

    assert item["integrity_state"] == "migration_required"
    assert item["manifest_digest"] is None
    assert len(item["observed_manifest_digest"]) == 64
    assert item["approval_enabled"] is False
    response = client.post(
        "/api/agent/candidates/legacy-pending/review",
        json={
            "decision": "approve",
            "note": "must migrate first",
            "expected_manifest_digest": item["observed_manifest_digest"],
            "expected_status": "pending",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_migration_required"


def test_agent_review_corrupt_candidate_is_409_integrity_failed(tmp_path) -> None:
    agent, client = _agent_app(tmp_path)
    broken = Path(agent) / "agent" / "candidates" / "broken-id"
    broken.mkdir(parents=True)
    (broken / "metadata.json").write_text("{not-json", encoding="utf-8")
    before = {p: p.read_bytes() for p in broken.rglob("*") if p.is_file()}

    response = client.post(
        "/api/agent/candidates/broken-id/review",
        json={
            "decision": "approve",
            "note": "corrupt target",
            "expected_manifest_digest": "0" * 64,
            "expected_status": "pending",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "candidate_integrity_failed"
    after = {p: p.read_bytes() for p in broken.rglob("*") if p.is_file()}
    assert after == before
    assert not (broken / "approved.lock").exists()


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
