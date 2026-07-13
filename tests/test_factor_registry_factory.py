from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.agent.candidate_manifest import (
    build_candidate_manifest,
    canonical_json_bytes,
)
from quant_system.api.server import create_app
from quant_system.factors import library
from quant_system.factors.base import BaseFactor
from quant_system.factors.registry import (
    build_default_factor_registry,
    build_factor_registry,
)

_EXAMPLE_IDS = {"momentum", "volatility", "liquidity", "rsi", "macd"}

_CANDIDATE_SRC = '''
from quant_system.factors.base import BaseFactor


class WiringTestFactor(BaseFactor):
    factor_id = "wiring_test_factor"
    factor_name = "Wiring Test Factor"
    factor_version = "0.1.0-candidate"
    default_lookback = 20
    direction = "higher_is_better"
    description = "test candidate"

    def _compute_values(self, frame):
        return frame["close"] * 0.0
'''


class _StubPromotedFactor(BaseFactor):
    factor_id = "stub_promoted"
    factor_name = "Stub Promoted"
    factor_version = "1.0.0"
    default_lookback = 10
    direction = "higher_is_better"
    description = "stub promoted factor"

    def _compute_values(self, frame):
        return frame["close"] * 0.0


def _write_candidate(root, candidate_id, source, *, approved):
    """Write verified candidate under agent root or candidates dir."""
    root = Path(root)
    if root.name == "candidates" and root.parent.name == "agent":
        cdir = root / candidate_id
    else:
        cdir = root / "agent" / "candidates" / candidate_id
    cdir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "candidate_id": candidate_id,
        "task_id": "task",
        "artifact_type": "factor",
        "goal": "goal",
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
    }
    (cdir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    (cdir / "factor.py.candidate").write_text(source, encoding="utf-8")
    manifest, digest, _ = build_candidate_manifest(cdir)
    (cdir / "manifest.v1.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    if approved:
        lock = {
            "schema_version": "1.0",
            "candidate_id": candidate_id,
            "decision": "approve",
            "manifest_digest": digest,
            "note": "test approval",
            "reviewer": "manual",
            "created_at": "2026-01-01T00:00:00Z",
        }
        (cdir / "approved.lock").write_bytes(canonical_json_bytes(lock))
    return digest


def test_factory_default_is_examples_plus_promoted() -> None:
    registry = build_factor_registry()
    assert set(registry.factor_ids()) == _EXAMPLE_IDS


def test_build_default_is_thin_alias() -> None:
    assert set(build_default_factor_registry().factor_ids()) == set(
        build_factor_registry().factor_ids()
    )


def test_promoted_library_factors_are_registered(monkeypatch) -> None:
    monkeypatch.setattr(
        library.promoted, "PROMOTED_FACTORS", (_StubPromotedFactor,), raising=True
    )
    registry = build_factor_registry()
    assert "stub_promoted" in registry.factor_ids()

    registry_without = build_factor_registry(include_promoted=False)
    assert "stub_promoted" not in registry_without.factor_ids()
    assert set(registry_without.factor_ids()) == _EXAMPLE_IDS


def test_approved_candidates_only_when_requested(tmp_path) -> None:
    _write_candidate(tmp_path, "cand-approved", _CANDIDATE_SRC, approved=True)

    without = build_factor_registry(agent_output_dir=tmp_path)
    assert "wiring_test_factor" not in without.factor_ids()

    with_candidates = build_factor_registry(
        include_approved_candidates=True, agent_output_dir=tmp_path
    )
    assert "wiring_test_factor" in with_candidates.factor_ids()
    assert with_candidates.create("wiring_test_factor") is not None


def test_pending_candidate_is_not_loaded(tmp_path) -> None:
    _write_candidate(tmp_path, "cand-pending", _CANDIDATE_SRC, approved=False)

    registry = build_factor_registry(
        include_approved_candidates=True, agent_output_dir=tmp_path
    )
    assert "wiring_test_factor" not in registry.factor_ids()


def test_factory_refuses_tampered_approved_candidate(tmp_path) -> None:
    from quant_system.agent.candidate_manifest import CandidateIntegrityError
    from quant_system.agent.candidate_pool import CandidatePool

    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="factory-tamper",
        goal="factory-tamper",
        artifact_type="factor",
        filename="factor.py.candidate",
        content=_CANDIDATE_SRC,
    )
    pool.review(
        candidate_id=artifact.candidate_id,
        decision="approve",
        note="approved exact bytes",
        expected_manifest_digest=artifact.manifest_digest,
        expected_status="pending",
    )
    artifact.path.write_text(
        _CANDIDATE_SRC.replace("wiring_test_factor", "tampered_factor"),
        encoding="utf-8",
    )

    with pytest.raises(CandidateIntegrityError):
        build_factor_registry(
            include_approved_candidates=True, agent_output_dir=tmp_path
        )


def test_approved_candidates_requested_without_dir_is_safe(tmp_path) -> None:
    # No candidates_dir supplied: must not raise and must not load anything.
    registry = build_factor_registry(
        include_approved_candidates=True, agent_output_dir=tmp_path / "missing"
    )
    assert set(registry.factor_ids()) == _EXAMPLE_IDS


# --- origin provenance metadata (Task P2) --------------------------------


def test_registry_tracks_origin_per_registration_pass(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        library.promoted, "PROMOTED_FACTORS", (_StubPromotedFactor,), raising=True
    )
    _write_candidate(tmp_path, "cand-approved", _CANDIDATE_SRC, approved=True)

    registry = build_factor_registry(
        include_approved_candidates=True, agent_output_dir=tmp_path
    )

    origins = registry.origins()
    for example_id in _EXAMPLE_IDS:
        assert origins[example_id] == "builtin"
    assert origins["stub_promoted"] == "promoted"
    assert origins["wiring_test_factor"] == "candidate"


def test_default_registry_has_no_candidate_origins() -> None:
    registry = build_factor_registry()
    assert set(registry.origins().values()) <= {"builtin", "promoted"}


# --- API /factors provenance (Task P2) -----------------------------------


def _api_client(tmp_path, agent_output_dir):
    # Inject the agent root through create_app; QS_DATA_DIR/output_dir must not
    # relocate the candidate pool.
    return TestClient(
        create_app(
            output_dir=tmp_path / "api",
            agent_output_dir=agent_output_dir,
        )
    )


def test_factors_default_call_has_no_candidate_origin(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    candidates_dir = agent / "agent" / "candidates"
    candidates_dir.mkdir(parents=True)
    _write_candidate(candidates_dir, "cand-approved", _CANDIDATE_SRC, approved=True)
    client = _api_client(tmp_path, agent)

    response = client.get("/api/factors")

    assert response.status_code == 200
    factors = response.json()["factors"]
    origins = {item["factor_id"]: item["origin"] for item in factors}
    assert set(origins) == _EXAMPLE_IDS
    assert all(origin == "builtin" for origin in origins.values())
    assert "wiring_test_factor" not in origins


def test_factors_include_candidates_lists_approved_candidate(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    candidates_dir = agent / "agent" / "candidates"
    candidates_dir.mkdir(parents=True)
    _write_candidate(candidates_dir, "cand-approved", _CANDIDATE_SRC, approved=True)
    client = _api_client(tmp_path, agent)

    response = client.get("/api/factors", params={"include_candidates": "true"})

    assert response.status_code == 200
    origins = {item["factor_id"]: item["origin"] for item in response.json()["factors"]}
    assert origins["wiring_test_factor"] == "candidate"
    for example_id in _EXAMPLE_IDS:
        assert origins[example_id] == "builtin"


def test_factors_include_candidates_excludes_pending_candidate(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    candidates_dir = agent / "agent" / "candidates"
    candidates_dir.mkdir(parents=True)
    _write_candidate(candidates_dir, "cand-pending", _CANDIDATE_SRC, approved=False)
    client = _api_client(tmp_path, agent)

    response = client.get("/api/factors", params={"include_candidates": "true"})

    assert response.status_code == 200
    factor_ids = {item["factor_id"] for item in response.json()["factors"]}
    assert "wiring_test_factor" not in factor_ids
    assert factor_ids == _EXAMPLE_IDS


def test_factors_candidate_catalog_uses_create_app_agent_root(tmp_path) -> None:
    general = tmp_path / "general"
    agent = tmp_path / "agent-output"
    candidates_dir = agent / "agent" / "candidates"
    candidates_dir.mkdir(parents=True)
    _write_candidate(
        candidates_dir,
        "cand-approved",
        _CANDIDATE_SRC,
        approved=True,
    )

    client = TestClient(create_app(output_dir=general, agent_output_dir=agent))
    payload = client.get("/api/factors?include_candidates=true").json()

    assert "wiring_test_factor" in {
        item["factor_id"] for item in payload["factors"]
    }
    assert not (general / "agent").exists()

