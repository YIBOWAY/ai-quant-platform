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
    _write_candidate(
        tmp_path,
        "cand-pending",
        _FACTOR_SRC.replace("wiring_test_factor", "other_id"),
        approved=False,
    )
    registry = build_default_factor_registry()
    loaded = load_approved_factor_candidates(registry, candidates_dir=tmp_path)
    assert loaded == ["wiring_test_factor"]
    assert registry.create("wiring_test_factor") is not None
    with pytest.raises(KeyError):
        registry.create("other_id")


def test_duplicate_registration_is_skipped_idempotently(tmp_path):
    _write_candidate(tmp_path, "cand-a", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path) == [
        "wiring_test_factor"
    ]
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path) == []


def test_forbidden_import_raises(tmp_path):
    bad = "import subprocess\n" + _FACTOR_SRC
    _write_candidate(tmp_path, "cand-bad", bad, approved=True)
    registry = build_default_factor_registry()
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(registry, candidates_dir=tmp_path)


# --- Static-check robustness (adversarial review findings #1/#2/#4) ---
# The substring blocklist was trivially bypassed via importlib/__import__/eval
# and exec() ran in a {} namespace that CPython populates with full __builtins__.
# These tests pin the hardened behavior: an AST-based allowlist blocks ALL
# import/eval mechanisms regardless of obfuscation, and the exec namespace no
# longer exposes __import__ via builtins.

def _approved(tmp_path, cid, src):
    _write_candidate(tmp_path, cid, src, approved=True)


def test_importlib_bypass_is_blocked(tmp_path):
    bad = "import importlib\n" + _FACTOR_SRC
    _approved(tmp_path, "cand-importlib", bad)
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(build_default_factor_registry(), candidates_dir=tmp_path)


def test_dunder_import_bypass_is_blocked(tmp_path):
    # class-body __import__ at load time — no 'import' keyword at all
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    _proof = __import__('subprocess')\n    def _compute_values(self, frame):",
    )
    _approved(tmp_path, "cand-dunder", bad)
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(build_default_factor_registry(), candidates_dir=tmp_path)


def test_eval_exec_compile_bypass_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    _x = eval('1+1')\n    def _compute_values(self, frame):",
    )
    _approved(tmp_path, "cand-eval", bad)
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(build_default_factor_registry(), candidates_dir=tmp_path)


def test_string_concat_import_is_blocked(tmp_path):
    # whitespace obfuscation: double-space between import and module
    bad = "import  subprocess\n" + _FACTOR_SRC
    _approved(tmp_path, "cand-ws", bad)
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(build_default_factor_registry(), candidates_dir=tmp_path)


def test_builtins_access_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    _b = __builtins__\n    def _compute_values(self, frame):",
    )
    _approved(tmp_path, "cand-builtins", bad)
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(build_default_factor_registry(), candidates_dir=tmp_path)


def test_legitimate_httpx_import_not_false_positive(tmp_path):
    # finding #4: substring 'import http' matched 'import httpx'. AST import-name
    # check must allow numpy/pandas/quant_system and reject only disallowed modules.
    src = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import numpy as np\nfrom quant_system.factors.base import BaseFactor",
    )
    _approved(tmp_path, "cand-numpy", src)
    loaded = load_approved_factor_candidates(
        build_default_factor_registry(),
        candidates_dir=tmp_path,
    )
    assert loaded == ["wiring_test_factor"]


def test_disallowed_module_import_is_blocked(tmp_path):
    # a non-allowlisted module (e.g. 'requests') is rejected even though it is
    # a clean, non-obfuscated import statement.
    bad = "import requests\n" + _FACTOR_SRC
    _approved(tmp_path, "cand-requests", bad)
    with pytest.raises(CandidateLoadError):
        load_approved_factor_candidates(build_default_factor_registry(), candidates_dir=tmp_path)


def test_quant_system_reexport_import_is_blocked(tmp_path):
    bad = "from quant_system.cli import os\n" + _FACTOR_SRC
    _approved(tmp_path, "cand-reexport", bad)
    with pytest.raises(CandidateLoadError, match="quant_system.cli"):
        load_approved_factor_candidates(build_default_factor_registry(), candidates_dir=tmp_path)


def test_missing_dir_returns_empty(tmp_path):
    registry = build_default_factor_registry()
    assert load_approved_factor_candidates(registry, candidates_dir=tmp_path / "nope") == []


def test_run_experiment_accepts_candidate_factor_registry(tmp_path):
    import json

    from quant_system.experiments.config import load_experiment_config
    from quant_system.experiments.runner import run_experiment

    _write_candidate(tmp_path / "cands", "cand-a", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()
    load_approved_factor_candidates(registry, candidates_dir=tmp_path / "cands")

    config_payload = {
        "experiment_name": "candidate-e2e",
        "symbols": ["SPY", "QQQ"],
        "start": "2024-01-02",
        "end": "2024-03-15",
        "factor_blend": {
            "factors": [{"factor_id": "wiring_test_factor"}, {"factor_id": "momentum"}]
        },
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


def test_run_experiment_threads_candidate_registry_through_walk_forward(tmp_path):
    # Coverage lock for the walk-forward path: _run_walk_forward_combination must
    # thread factor_registry into _run_single_backtest -> _create_factors. If the
    # candidate-only factor_id 'wiring_test_factor' is not resolved via the passed
    # registry, build_default_factor_registry() raises KeyError for it and the
    # experiment crashes. A green run here proves the threading is intact on the
    # walk-forward branch (not just the plain backtest branch).
    import json

    from quant_system.experiments.config import load_experiment_config
    from quant_system.experiments.runner import run_experiment

    _write_candidate(tmp_path / "cands", "cand-a", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()
    load_approved_factor_candidates(registry, candidates_dir=tmp_path / "cands")

    config_payload = {
        "experiment_name": "candidate-walkforward",
        "symbols": ["SPY", "QQQ"],
        "start": "2024-01-02",
        "end": "2024-06-15",
        "factor_blend": {
            "factors": [{"factor_id": "wiring_test_factor"}, {"factor_id": "momentum"}]
        },
        "walk_forward": {"enabled": True, "train_bars": 40, "validation_bars": 15, "step_bars": 15},
    }
    config_file = tmp_path / "exp.json"
    config_file.write_text(json.dumps(config_payload), encoding="utf-8")

    result = run_experiment(
        load_experiment_config(config_file),
        output_dir=tmp_path / "out",
        factor_registry=registry,
    )
    assert result.run_count >= 1
    assert result.folds_path.exists()
