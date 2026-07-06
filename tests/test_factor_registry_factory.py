from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import quant_system.api.routes.factors as factors_route
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
    cdir = root / candidate_id
    cdir.mkdir(parents=True)
    (cdir / "factor.py.candidate").write_text(source, encoding="utf-8")
    (cdir / "metadata.json").write_text("{}", encoding="utf-8")
    if approved:
        (cdir / "approved.lock").write_text("{}", encoding="utf-8")


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

    without = build_factor_registry(candidates_dir=tmp_path)
    assert "wiring_test_factor" not in without.factor_ids()

    with_candidates = build_factor_registry(
        include_approved_candidates=True, candidates_dir=tmp_path
    )
    assert "wiring_test_factor" in with_candidates.factor_ids()
    assert with_candidates.create("wiring_test_factor") is not None


def test_pending_candidate_is_not_loaded(tmp_path) -> None:
    _write_candidate(tmp_path, "cand-pending", _CANDIDATE_SRC, approved=False)

    registry = build_factor_registry(
        include_approved_candidates=True, candidates_dir=tmp_path
    )
    assert "wiring_test_factor" not in registry.factor_ids()


def test_approved_candidates_requested_without_dir_is_safe(tmp_path) -> None:
    # No candidates_dir supplied: must not raise and must not load anything.
    registry = build_factor_registry(
        include_approved_candidates=True, candidates_dir=tmp_path / "missing"
    )
    assert set(registry.factor_ids()) == _EXAMPLE_IDS


# --- origin provenance metadata (Task P2) --------------------------------


def test_registry_tracks_origin_per_registration_pass(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        library.promoted, "PROMOTED_FACTORS", (_StubPromotedFactor,), raising=True
    )
    _write_candidate(tmp_path, "cand-approved", _CANDIDATE_SRC, approved=True)

    registry = build_factor_registry(
        include_approved_candidates=True, candidates_dir=tmp_path
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


def _api_client(tmp_path, monkeypatch, candidates_dir):
    # Point the route's candidate lookup at an isolated tmp dir instead of the
    # on-disk data/agent_run/agent/candidates default.
    monkeypatch.setattr(
        factors_route, "AGENT_CANDIDATES_DIR", candidates_dir, raising=True
    )
    return TestClient(create_app(output_dir=tmp_path / "api"))


def test_factors_default_call_has_no_candidate_origin(tmp_path, monkeypatch) -> None:
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    _write_candidate(candidates_dir, "cand-approved", _CANDIDATE_SRC, approved=True)
    client = _api_client(tmp_path, monkeypatch, candidates_dir)

    response = client.get("/api/factors")

    assert response.status_code == 200
    factors = response.json()["factors"]
    origins = {item["factor_id"]: item["origin"] for item in factors}
    assert set(origins) == _EXAMPLE_IDS
    assert all(origin == "builtin" for origin in origins.values())
    assert "wiring_test_factor" not in origins


def test_factors_include_candidates_lists_approved_candidate(
    tmp_path, monkeypatch
) -> None:
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    _write_candidate(candidates_dir, "cand-approved", _CANDIDATE_SRC, approved=True)
    client = _api_client(tmp_path, monkeypatch, candidates_dir)

    response = client.get("/api/factors", params={"include_candidates": "true"})

    assert response.status_code == 200
    origins = {item["factor_id"]: item["origin"] for item in response.json()["factors"]}
    assert origins["wiring_test_factor"] == "candidate"
    for example_id in _EXAMPLE_IDS:
        assert origins[example_id] == "builtin"


def test_factors_include_candidates_excludes_pending_candidate(
    tmp_path, monkeypatch
) -> None:
    candidates_dir = tmp_path / "candidates"
    candidates_dir.mkdir()
    _write_candidate(candidates_dir, "cand-pending", _CANDIDATE_SRC, approved=False)
    client = _api_client(tmp_path, monkeypatch, candidates_dir)

    response = client.get("/api/factors", params={"include_candidates": "true"})

    assert response.status_code == 200
    factor_ids = {item["factor_id"] for item in response.json()["factors"]}
    assert "wiring_test_factor" not in factor_ids
    assert factor_ids == _EXAMPLE_IDS
