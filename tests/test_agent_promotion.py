from __future__ import annotations

import pytest

from quant_system.agent.promotion import CandidateLoadError, load_approved_factor_candidates
from quant_system.factors.registry import build_default_factor_registry

_FACTOR_SRC = '''
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


def _write_candidate(root, candidate_id, source, approved):
    cdir = root / candidate_id
    cdir.mkdir(parents=True)
    (cdir / "factor.py.candidate").write_text(source, encoding="utf-8")
    (cdir / "metadata.json").write_text("{}", encoding="utf-8")
    if approved:
        (cdir / "approved.lock").write_text("{}", encoding="utf-8")


def test_loads_only_approved_candidates(tmp_path):
    _write_candidate(tmp_path, "cand-approved", _FACTOR_SRC, approved=True)
    _write_candidate(tmp_path, "cand-pending", _FACTOR_SRC.replace("wiring_test_factor", "other_id"), approved=False)
    registry = build_default_factor_registry()
    loaded = load_approved_factor_candidates(registry, candidates_dir=tmp_path)
    assert loaded == ["wiring_test_factor"]
    assert registry.create("wiring_test_factor") is not None
    with pytest.raises(KeyError):
        registry.create("other_id")


def test_duplicate_registration_is_skipped_idempotently(tmp_path):
    _write_candidate(tmp_path, "cand-a", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path) == ["wiring_test_factor"]
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path) == []


def test_forbidden_import_raises(tmp_path):
    bad = "import subprocess\n" + _FACTOR_SRC
    _write_candidate(tmp_path, "cand-bad", bad, approved=True)
    registry = build_default_factor_registry()
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(registry, candidates_dir=tmp_path)


def test_missing_dir_returns_empty(tmp_path):
    registry = build_default_factor_registry()
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path / "nope") == []


def test_run_experiment_accepts_candidate_factor_registry(tmp_path):
    from quant_system.experiments.config import load_experiment_config
    from quant_system.experiments.runner import run_experiment
    import json

    _write_candidate(tmp_path / "cands", "cand-a", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()
    load_approved_factor_candidates(registry, candidates_dir=tmp_path / "cands")

    config_payload = {
        "experiment_name": "candidate-e2e",
        "symbols": ["SPY", "QQQ"],
        "start": "2024-01-02",
        "end": "2024-03-15",
        "factor_blend": {"factors": [{"factor_id": "wiring_test_factor"}, {"factor_id": "momentum"}]},
    }
    config_file = tmp_path / "exp.json"
    config_file.write_text(json.dumps(config_payload), encoding="utf-8")

    result = run_experiment(
        load_experiment_config(config_file),
        output_dir=tmp_path / "out",
        factor_registry=registry,
    )
    assert result.run_count >= 1
    assert result.agent_summary_path.exists()
