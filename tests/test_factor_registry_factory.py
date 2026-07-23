from __future__ import annotations

import inspect
import json
from pathlib import Path

from fastapi.testclient import TestClient

from quant_system.agent import promotion
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
_PROMOTED_IDS = {
    factor_cls().factor_id for factor_cls in library.promoted.PROMOTED_FACTORS
}
_RESIDENT_IDS = _EXAMPLE_IDS | _PROMOTED_IDS

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
    assert set(registry.factor_ids()) == _RESIDENT_IDS


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


def test_registry_factory_has_no_candidate_execution_switch() -> None:
    parameters = inspect.signature(build_factor_registry).parameters

    assert "include_approved_candidates" not in parameters
    assert "agent_output_dir" not in parameters
    assert not hasattr(promotion, "load_approved_factor_candidates")


# --- origin provenance metadata (Task P2) --------------------------------


def test_registry_tracks_origin_per_registration_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        library.promoted, "PROMOTED_FACTORS", (_StubPromotedFactor,), raising=True
    )
    registry = build_factor_registry()

    origins = registry.origins()
    for example_id in _EXAMPLE_IDS:
        assert origins[example_id] == "builtin"
    assert origins["stub_promoted"] == "promoted"
    assert set(origins.values()) == {"builtin", "promoted"}


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
    assert set(origins) == _RESIDENT_IDS
    assert all(origins[factor_id] == "builtin" for factor_id in _EXAMPLE_IDS)
    assert all(origins[factor_id] == "promoted" for factor_id in _PROMOTED_IDS)
    assert "wiring_test_factor" not in origins


def test_factors_rejects_bulk_candidate_loading_even_when_approved(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    candidates_dir = agent / "agent" / "candidates"
    candidates_dir.mkdir(parents=True)
    _write_candidate(candidates_dir, "cand-approved", _CANDIDATE_SRC, approved=True)
    client = _api_client(tmp_path, agent)

    response = client.get("/api/factors", params={"include_candidates": "true"})

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "candidate_bulk_loading_disabled",
        "message": "Use an exact candidate ID and expected digest in the one-shot research CLI.",
    }


def test_factors_rejects_bulk_candidate_loading_for_pending_candidate(tmp_path) -> None:
    agent = tmp_path / "agent-output"
    candidates_dir = agent / "agent" / "candidates"
    candidates_dir.mkdir(parents=True)
    _write_candidate(candidates_dir, "cand-pending", _CANDIDATE_SRC, approved=False)
    client = _api_client(tmp_path, agent)

    response = client.get("/api/factors", params={"include_candidates": "true"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "candidate_bulk_loading_disabled"


def test_factors_bulk_candidate_query_never_executes_injected_candidate(tmp_path) -> None:
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
    response = client.get("/api/factors?include_candidates=true")

    assert response.status_code == 400
    assert not (general / "agent").exists()
