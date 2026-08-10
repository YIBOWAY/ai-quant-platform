from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_system.agent.candidate_manifest import (
    CandidateIntegrityError,
    build_candidate_manifest,
    canonical_json_bytes,
)
from quant_system.agent.candidate_pool import CandidatePool
from quant_system.agent.promotion import (
    CandidateLoadError,
    load_approved_factor_candidate,
)
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

_VALID_FACTOR_SOURCE = '''
from quant_system.factors.base import BaseFactor


class SafeFactor(BaseFactor):
    factor_id = "safe_factor"
    factor_name = "Safe Factor"
    factor_version = "0.1.0-candidate"
    default_lookback = 20
    direction = "higher_is_better"
    description = "tamper test candidate"

    def _compute_values(self, frame):
        return frame["close"] * 0.0
'''



def _write_candidate(agent_root, candidate_id, source, approved):
    """Write a verified candidate under agent_root/agent/candidates."""
    cdir = Path(agent_root) / "agent" / "candidates" / candidate_id
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


def _load_exact_for_test(registry, *, agent_output_dir, candidate_id, digest):
    """Exercise the production exact-ID/digest loader in safety-focused tests."""
    return load_approved_factor_candidate(
        registry,
        agent_output_dir=agent_output_dir,
        candidate_id=candidate_id,
        expected_manifest_digest=digest,
    )


def test_exact_loader_refuses_pending_candidate(tmp_path):
    digest = _write_candidate(tmp_path, "cand-pending", _FACTOR_SRC, approved=False)
    registry = build_default_factor_registry()

    with pytest.raises(CandidateLoadError, match="not approved"):
        _load_exact_for_test(
            registry,
            agent_output_dir=tmp_path,
            candidate_id="cand-pending",
            digest=digest,
        )

    assert "wiring_test_factor" not in registry.factor_ids()


def test_exact_loader_uses_only_the_requested_approved_snapshot(tmp_path) -> None:
    from quant_system.agent import promotion

    digest = _write_candidate(
        tmp_path,
        "cand-requested",
        _FACTOR_SRC,
        approved=True,
    )
    _write_candidate(
        tmp_path,
        "cand-unrelated",
        "import subprocess\n" + _FACTOR_SRC.replace(
            "wiring_test_factor", "unrelated_factor"
        ),
        approved=True,
    )
    registry = build_default_factor_registry()

    binding = promotion.load_approved_factor_candidate(
        registry,
        agent_output_dir=tmp_path,
        candidate_id="cand-requested",
        expected_manifest_digest=digest,
    )

    assert binding.candidate_id == "cand-requested"
    assert binding.manifest_digest == digest
    assert binding.factor_id == "wiring_test_factor"
    assert "wiring_test_factor" in registry.factor_ids()
    assert "unrelated_factor" not in registry.factor_ids()


def test_exact_loader_refuses_a_stale_expected_digest_before_registration(
    tmp_path,
) -> None:
    from quant_system.agent import promotion
    from quant_system.agent.candidate_manifest import CandidateStaleError

    _write_candidate(tmp_path, "cand-stale", _FACTOR_SRC, approved=True)
    registry = build_default_factor_registry()

    with pytest.raises(CandidateStaleError, match="digest"):
        promotion.load_approved_factor_candidate(
            registry,
            agent_output_dir=tmp_path,
            candidate_id="cand-stale",
            expected_manifest_digest="0" * 64,
        )

    assert "wiring_test_factor" not in registry.factor_ids()


def test_exact_loader_rejects_builtin_factor_id_collision(tmp_path) -> None:
    from quant_system.agent import promotion

    digest = _write_candidate(
        tmp_path,
        "cand-builtin-collision",
        _FACTOR_SRC.replace("wiring_test_factor", "momentum"),
        approved=True,
    )
    registry = build_default_factor_registry()

    with pytest.raises(
        CandidateLoadError,
        match="factor_id 'momentum'.*builtin",
    ):
        promotion.load_approved_factor_candidate(
            registry,
            agent_output_dir=tmp_path,
            candidate_id="cand-builtin-collision",
            expected_manifest_digest=digest,
        )

    assert registry.origins()["momentum"] == "builtin"


def test_exact_loader_rejects_collision_before_executing_candidate_source(
    tmp_path, capsys
) -> None:
    from quant_system.agent import promotion

    source = (
        'print("candidate-source-executed")\n'
        + _FACTOR_SRC.replace("wiring_test_factor", "momentum")
    )
    digest = _write_candidate(
        tmp_path,
        "cand-pre-exec-collision",
        source,
        approved=True,
    )

    with pytest.raises(CandidateLoadError, match="factor_id 'momentum'.*builtin"):
        promotion.load_approved_factor_candidate(
            build_default_factor_registry(),
            agent_output_dir=tmp_path,
            candidate_id="cand-pre-exec-collision",
            expected_manifest_digest=digest,
        )

    assert "candidate-source-executed" not in capsys.readouterr().out


def test_exact_loader_rejects_factor_id_owned_by_another_candidate(tmp_path) -> None:
    from quant_system.agent import promotion

    requested_digest = _write_candidate(
        tmp_path,
        "cand-requested-owner",
        _FACTOR_SRC,
        approved=True,
    )
    _write_candidate(
        tmp_path,
        "cand-other-owner",
        _FACTOR_SRC.replace("WiringTestFactor", "OtherCandidateFactor"),
        approved=True,
    )
    registry = build_default_factor_registry()

    with pytest.raises(
        CandidateLoadError,
        match="wiring_test_factor.*cand-other-owner",
    ):
        promotion.load_approved_factor_candidate(
            registry,
            agent_output_dir=tmp_path,
            candidate_id="cand-requested-owner",
            expected_manifest_digest=requested_digest,
        )

    assert "wiring_test_factor" not in registry.factor_ids()


def test_review_bundle_comes_from_one_verified_candidate_snapshot(tmp_path) -> None:
    from quant_system.agent import promotion

    digest = _write_candidate(
        tmp_path,
        "cand-review-bundle",
        _FACTOR_SRC,
        approved=False,
    )

    bundle = promotion.inspect_factor_candidate(
        agent_output_dir=tmp_path,
        candidate_id="cand-review-bundle",
        expected_manifest_digest=digest,
    )

    assert bundle.candidate_id == "cand-review-bundle"
    assert bundle.manifest_digest == digest
    assert bundle.factor_id == "wiring_test_factor"
    assert bundle.source == _FACTOR_SRC
    assert bundle.source_path == (
        tmp_path
        / "agent"
        / "candidates"
        / "cand-review-bundle"
        / "factor.py.candidate"
    )
    assert bundle.approval_binding == "pending"


def test_loader_refuses_source_changed_after_digest_bound_approval(tmp_path) -> None:
    pool = CandidatePool(tmp_path)
    artifact = pool.write_candidate(
        task_id="tamper-task",
        goal="tamper",
        artifact_type="factor",
        filename="factor.py.candidate",
        content=_VALID_FACTOR_SOURCE,
    )
    pool.review(
        candidate_id=artifact.candidate_id,
        decision="approve",
        note="approved exact bytes",
        expected_manifest_digest=artifact.manifest_digest,
        expected_status="pending",
    )
    artifact.path.write_text(
        _VALID_FACTOR_SOURCE.replace("safe_factor", "changed_factor"),
        encoding="utf-8",
    )

    registry = build_default_factor_registry()
    with pytest.raises(CandidateIntegrityError):
        _load_exact_for_test(
            registry,
            agent_output_dir=tmp_path,
            candidate_id=artifact.candidate_id,
            digest=artifact.manifest_digest,
        )
    assert "changed_factor" not in registry.factor_ids()
    assert "safe_factor" not in registry.factor_ids()


def test_loader_skips_legacy_unbound_approval_without_compiling(tmp_path) -> None:
    # Legacy empty approved.lock never authorizes one-shot research load.
    cdir = tmp_path / "agent" / "candidates" / "cand-legacy"
    cdir.mkdir(parents=True)
    metadata = {
        "candidate_id": "cand-legacy",
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
    (cdir / "factor.py.candidate").write_text(_VALID_FACTOR_SOURCE, encoding="utf-8")
    manifest, digest, _ = build_candidate_manifest(cdir)
    (cdir / "manifest.v1.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    (cdir / "approved.lock").write_text("{}", encoding="utf-8")

    registry = build_default_factor_registry()
    with pytest.raises(CandidateLoadError, match="not approved"):
        _load_exact_for_test(
            registry,
            agent_output_dir=tmp_path,
            candidate_id="cand-legacy",
            digest=digest,
        )
    assert "safe_factor" not in registry.factor_ids()


def test_forbidden_import_raises(tmp_path):
    bad = "import subprocess\n" + _FACTOR_SRC
    digest = _write_candidate(tmp_path, "cand-bad", bad, approved=True)
    registry = build_default_factor_registry()
    with pytest.raises(CandidateLoadError):
        _load_exact_for_test(
            registry,
            agent_output_dir=tmp_path,
            candidate_id="cand-bad",
            digest=digest,
        )


# --- Static-check robustness (adversarial review findings #1/#2/#4) ---
# The substring blocklist was trivially bypassed via importlib/__import__/eval
# and exec() ran in a {} namespace that CPython populates with full __builtins__.
# These tests pin the hardened behavior: an AST-based allowlist blocks ALL
# import/eval mechanisms regardless of obfuscation, and the exec namespace no
# longer exposes __import__ via builtins.

def _approved(tmp_path, cid, src):
    return _write_candidate(tmp_path, cid, src, approved=True)


def _load_approved_source(tmp_path, candidate_id, source, *, registry=None):
    digest = _approved(tmp_path, candidate_id, source)
    return _load_exact_for_test(
        registry or build_default_factor_registry(),
        agent_output_dir=tmp_path,
        candidate_id=candidate_id,
        digest=digest,
    )


def test_importlib_bypass_is_blocked(tmp_path):
    bad = "import importlib\n" + _FACTOR_SRC
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-importlib", bad)


def test_dunder_import_bypass_is_blocked(tmp_path):
    # class-body __import__ at load time — no 'import' keyword at all
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    _proof = __import__('subprocess')\n    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-dunder", bad)


def test_eval_exec_compile_bypass_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    _x = eval('1+1')\n    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-eval", bad)


def test_string_concat_import_is_blocked(tmp_path):
    # whitespace obfuscation: double-space between import and module
    bad = "import  subprocess\n" + _FACTOR_SRC
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-ws", bad)


def test_builtins_access_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    _b = __builtins__\n    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-builtins", bad)


def test_legitimate_httpx_import_not_false_positive(tmp_path):
    # finding #4: substring 'import http' matched 'import httpx'. AST import-name
    # check must allow numpy/pandas/quant_system and reject only disallowed modules.
    src = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import numpy as np\nfrom quant_system.factors.base import BaseFactor",
    )
    binding = _load_approved_source(tmp_path, "cand-numpy", src)
    assert binding.factor_id == "wiring_test_factor"


def test_future_annotations_import_is_allowed_for_generated_factor(tmp_path):
    src = "from __future__ import annotations\n" + _FACTOR_SRC
    binding = _load_approved_source(tmp_path, "cand-future-annotations", src)
    assert binding.factor_id == "wiring_test_factor"


def test_disallowed_module_import_is_blocked(tmp_path):
    # a non-allowlisted module (e.g. 'requests') is rejected even though it is
    # a clean, non-obfuscated import statement.
    bad = "import requests\n" + _FACTOR_SRC
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-requests", bad)


def test_quant_system_reexport_import_is_blocked(tmp_path):
    bad = "from quant_system.cli import os\n" + _FACTOR_SRC
    with pytest.raises(CandidateLoadError, match="quant_system.cli"):
        _load_approved_source(tmp_path, "cand-reexport", bad)


# --- Dunder-gadget hardening (review finding F1 BLOCKER) ---
# The Name/Attribute-only denylist let `type(x).__getattribute__(x, "__class__")`
# — a dunder-METHOD call whose argument is a dunder STRING CONSTANT — walk to
# object.__subclasses__() and reach subprocess.Popen at promoted-module import
# time, defeating both the AST layer and the emptied-builtins exec layer. The
# hardened check rejects (a) any attribute whose name is a dunder except
# __init__, and (b) any string constant that names a dunder.


def test_dunder_getattribute_gadget_is_blocked(tmp_path):
    # The exact confirmed bypass: dunder-method attribute call with a dunder
    # string-constant argument. Neither node type tripped the old denylist.
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        '    _p = type(BaseFactor).__getattribute__(BaseFactor, "__class__")\n'
        "    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-gadget", bad)


def test_dunder_attribute_access_is_blocked(tmp_path):
    # __globals__ was not in the original denylist; the generic dunder-attribute
    # rule must reject it (and __code__, __closure__, etc.) without enumeration.
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    _g = (lambda: 0).__globals__\n    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-globals", bad)


def test_dunder_string_constant_is_blocked(tmp_path):
    # A bare dunder string constant is the raw material for getattr/gadget walks;
    # reject it even when it is not (yet) passed anywhere interesting.
    bad = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        '    _name = "__subclasses__"\n    def _compute_values(self, frame):',
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-dunderstr", bad)


def test_super_init_still_allowed(tmp_path):
    # The __init__ exception must survive: a factor that chains its constructor
    # via super().__init__(...) is legitimate and must still load.
    src = _FACTOR_SRC.replace(
        "    def _compute_values(self, frame):",
        "    def __init__(self, *, lookback=None):\n"
        "        super().__init__(lookback=lookback)\n"
        "    def _compute_values(self, frame):",
    )
    binding = _load_approved_source(tmp_path, "cand-superinit", src)
    assert binding.factor_id == "wiring_test_factor"


def test_attrgetter_string_indirection_is_blocked(tmp_path):
    # operator.attrgetter turns a runtime-built string into an arbitrary
    # attribute fetch, bridging string CONCATENATION (which dodges the
    # dunder-constant rule) to a gadget attribute. operator is an allowed import
    # root, so the attribute-fetch-by-name primitives themselves must be denied.
    bad = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import operator\nfrom quant_system.factors.base import BaseFactor",
    ).replace(
        "    def _compute_values(self, frame):",
        '    _g = operator.attrgetter("__glob" + "als__")\n'
        "    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-attrgetter", bad)


def test_methodcaller_string_indirection_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "from operator import methodcaller\nfrom quant_system.factors.base import BaseFactor",
    ).replace(
        "    def _compute_values(self, frame):",
        '    _m = methodcaller("__reduce" + "__")\n'
        "    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-methodcaller", bad)


# --- Re-export RCE class (adversarial re-review: BLOCKER + MAJOR) ---
# numpy/pandas are allowed import roots but re-export os/subprocess as PLAIN
# (non-dunder) attributes, so `np.ctypeslib.os.system(...)` reached a shell at
# class-body eval time, and `pd.read_pickle(...)`/`pd.read_csv(...)` are
# arbitrary-code / arbitrary-file-read primitives — all through legitimate
# allowed roots. The AST check now rejects (a) any attribute-chain part that
# names a dangerous stdlib module and (b) deserialization / file-IO reader
# methods, so such an attack must look obviously weird for the human Gate-2.


def test_numpy_os_reexport_chain_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import numpy as np\nfrom quant_system.factors.base import BaseFactor",
    ).replace(
        "    def _compute_values(self, frame):",
        '    _x = np.ctypeslib.os\n    def _compute_values(self, frame):',
    )
    with pytest.raises(CandidateLoadError, match="os"):
        _load_approved_source(tmp_path, "cand-npos", bad)


def test_pandas_subprocess_reexport_chain_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import pandas as pd\nfrom quant_system.factors.base import BaseFactor",
    ).replace(
        "    def _compute_values(self, frame):",
        "    _x = pd.compat.os\n    def _compute_values(self, frame):",
    )
    with pytest.raises(CandidateLoadError):
        _load_approved_source(tmp_path, "cand-pdos", bad)


def test_pandas_read_pickle_is_blocked(tmp_path):
    # read_pickle is a pickle-deserialization RCE primitive; reject the reader
    # method name regardless of the object it is called on.
    bad = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import pandas as pd\nfrom quant_system.factors.base import BaseFactor",
    ).replace(
        "    def _compute_values(self, frame):",
        '    _x = pd.read_pickle("/etc/passwd")\n    def _compute_values(self, frame):',
    )
    with pytest.raises(CandidateLoadError, match="read_pickle"):
        _load_approved_source(tmp_path, "cand-readpickle", bad)


def test_pandas_read_csv_is_blocked(tmp_path):
    bad = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import pandas as pd\nfrom quant_system.factors.base import BaseFactor",
    ).replace(
        "    def _compute_values(self, frame):",
        '    _x = pd.read_csv("/etc/passwd")\n    def _compute_values(self, frame):',
    )
    with pytest.raises(CandidateLoadError, match="read_csv"):
        _load_approved_source(tmp_path, "cand-readcsv", bad)


def test_legitimate_numpy_pandas_math_still_loads(tmp_path):
    # Guard against over-blocking: ordinary factor math on numpy/pandas must
    # still load. Uses the real allowed vocabulary (rolling/mean/pct_change).
    src = _FACTOR_SRC.replace(
        "from quant_system.factors.base import BaseFactor",
        "import numpy as np\nimport pandas as pd\nfrom quant_system.factors.base import BaseFactor",
    ).replace(
        "        return frame[\"close\"] * 0.0",
        (
            "        return frame[\"close\"].pct_change()"
            ".rolling(self.lookback).mean() * np.float64(1.0)"
        ),
    )
    binding = _load_approved_source(tmp_path, "cand-legitmath", src)
    assert binding.factor_id == "wiring_test_factor"


def test_run_experiment_accepts_candidate_factor_registry(tmp_path):
    import json

    from quant_system.experiments.config import load_experiment_config
    from quant_system.experiments.runner import run_experiment

    digest = _write_candidate(
        tmp_path / "cands", "cand-a", _FACTOR_SRC, approved=True
    )
    registry = build_default_factor_registry()
    _load_exact_for_test(
        registry,
        agent_output_dir=tmp_path / "cands",
        candidate_id="cand-a",
        digest=digest,
    )

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

    digest = _write_candidate(
        tmp_path / "cands", "cand-a", _FACTOR_SRC, approved=True
    )
    registry = build_default_factor_registry()
    _load_exact_for_test(
        registry,
        agent_output_dir=tmp_path / "cands",
        candidate_id="cand-a",
        digest=digest,
    )

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


def test_load_approved_factor_with_property_metadata_override(tmp_path) -> None:
    """Stub/propose sources use @property; safe builtins must expose property."""
    from quant_system.agent import promotion

    src = """from quant_system.factors.base import BaseFactor, FactorMetadata


class PropertyFactor(BaseFactor):
    factor_id = "property_override_factor"
    factor_name = "Property Override Factor"
    factor_version = "0.1.0-candidate"
    default_lookback = 20
    direction = "higher_is_better"
    description = "uses property decorator"

    @property
    def metadata(self) -> FactorMetadata:
        return FactorMetadata(
            factor_id=self.factor_id,
            factor_name=self.factor_name,
            factor_version=self.factor_version,
            description=self.description,
            lookback=self.lookback,
            direction=self.direction,
        )

    def _compute_values(self, frame):
        return frame["close"] * 0.0
"""
    digest = _write_candidate(tmp_path, "cand-property", src, approved=True)
    registry = build_default_factor_registry()
    binding = promotion.load_approved_factor_candidate(
        registry,
        agent_output_dir=tmp_path,
        candidate_id="cand-property",
        expected_manifest_digest=digest,
    )
    assert binding.factor_id == "property_override_factor"
    assert "property_override_factor" in registry.factor_ids()
    assert "property" in promotion._make_safe_builtins()
