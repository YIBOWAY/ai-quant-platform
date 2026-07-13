from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import quant_system.agent.promote as promote_module
from quant_system.agent.candidate_manifest import (
    build_candidate_manifest,
    canonical_json_bytes,
)
from quant_system.agent.promote import PromotionError, promote_candidate
from quant_system.cli import app

runner = CliRunner()

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

_SECOND_FACTOR_SRC = '''
from quant_system.factors.base import BaseFactor


class AlphaScaffoldFactor(BaseFactor):
    factor_id = "alpha_scaffold_factor"
    factor_name = "Alpha Scaffold Factor"
    factor_version = "0.1.0-candidate"
    default_lookback = 10
    direction = "lower_is_better"
    description = "second test candidate"

    def _compute_values(self, frame):
        return frame["close"] * 0.0
'''

_EVIL_SRC = '''
import os
from quant_system.factors.base import BaseFactor


class EvilFactor(BaseFactor):
    factor_id = "evil_factor"
    factor_name = "Evil Factor"
    factor_version = "0.1.0-candidate"
    default_lookback = 20
    direction = "higher_is_better"
    description = "reads the filesystem"

    def _compute_values(self, frame):
        return frame["close"] * 0.0
'''

_NO_CLASS_SRC = "VALUE = 1\n"

_TWO_CLASSES_SRC = _FACTOR_SRC + '''

class SecondFactor(BaseFactor):
    factor_id = "second_factor"
    factor_name = "Second Factor"
    factor_version = "0.1.0-candidate"
    default_lookback = 5
    direction = "neutral"
    description = "duplicate class"

    def _compute_values(self, frame):
        return frame["close"] * 0.0
'''

_NON_STRING_ID_SRC = _FACTOR_SRC.replace('factor_id = "wiring_test_factor"', "factor_id = 123")

# A candidate whose factor_id collides with a builtin registry factor
# ("momentum"). Promoting it would make build_factor_registry() raise everywhere.
_COLLIDING_ID_SRC = _FACTOR_SRC.replace(
    'factor_id = "wiring_test_factor"', 'factor_id = "momentum"'
).replace("WiringTestFactor", "CollidingFactor")

# A candidate whose factor_id starts with an underscore. `_regenerate_init`
# skips `_*.py` modules, so such a factor would be written but silently never
# registered — reject it up front instead.
_UNDERSCORE_ID_SRC = _FACTOR_SRC.replace(
    'factor_id = "wiring_test_factor"', 'factor_id = "_hidden_factor"'
).replace("WiringTestFactor", "HiddenFactor")


def _write_candidate(root: Path, candidate_id: str, source: str, *, approved: bool = True) -> str:
    """Write verified candidate. root may be agent root or candidates dir.

    If root already ends with agent/candidates, write there; else use agent root layout.
    """
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


@pytest.fixture()
def dirs(tmp_path: Path) -> dict[str, Path]:
    return {
        "agent": tmp_path / "agent-output",
        "library": tmp_path / "library" / "promoted",
        "tests": tmp_path / "tests" / "factors",
    }


def _promote(candidate_id: str, dirs: dict[str, Path], **kwargs):
    return promote_candidate(
        candidate_id,
        agent_output_dir=dirs["agent"],
        library_dir=dirs["library"],
        tests_dir=dirs["tests"],
        **kwargs,
    )


def test_happy_path_writes_module_init_and_test_scaffold(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-ok", _FACTOR_SRC)

    result = _promote("cand-ok", dirs, promotion_date="2026-01-02")

    assert result.factor_id == "wiring_test_factor"
    assert result.module_path == dirs["library"] / "wiring_test_factor.py"
    assert result.init_path == dirs["library"] / "__init__.py"
    assert result.test_path == dirs["tests"] / "test_wiring_test_factor.py"

    module_content = result.module_path.read_text(encoding="utf-8")
    # Provenance header, then the candidate source verbatim.
    assert "candidate_id: cand-ok" in module_content
    assert "approved.lock" in module_content
    assert "promoted_on: 2026-01-02" in module_content
    assert module_content.endswith(_FACTOR_SRC)

    init_content = result.init_path.read_text(encoding="utf-8")
    assert (
        "from quant_system.factors.library.promoted.wiring_test_factor "
        "import WiringTestFactor as wiring_test_factor_factor"
    ) in init_content
    assert "PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = (" in init_content
    assert "wiring_test_factor_factor," in init_content
    ast.parse(init_content)

    test_content = result.test_path.read_text(encoding="utf-8")
    assert (
        "from quant_system.factors.library.promoted.wiring_test_factor import WiringTestFactor"
    ) in test_content
    assert 'metadata.factor_id == "wiring_test_factor"' in test_content
    assert "compute" in test_content
    ast.parse(test_content)


def test_init_regeneration_is_sorted_across_promotions(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-w", _FACTOR_SRC)
    _write_candidate(dirs["agent"], "cand-a", _SECOND_FACTOR_SRC)

    _promote("cand-w", dirs)
    result = _promote("cand-a", dirs)

    init_content = result.init_path.read_text(encoding="utf-8")
    alpha_import = init_content.index("promoted.alpha_scaffold_factor import")
    wiring_import = init_content.index("promoted.wiring_test_factor import")
    assert alpha_import < wiring_import
    assert init_content.index("alpha_scaffold_factor_factor,") < init_content.index(
        "wiring_test_factor_factor,"
    )
    ast.parse(init_content)


def test_unapproved_candidate_refused_and_nothing_written(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-pending", _FACTOR_SRC, approved=False)

    with pytest.raises(PromotionError, match="approv"):
        _promote("cand-pending", dirs)
    assert not dirs["library"].exists() or not list(dirs["library"].iterdir())
    assert not dirs["tests"].exists() or not list(dirs["tests"].iterdir())


def test_rejected_lock_refuses_even_with_approved_lock(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-rejected", _FACTOR_SRC, approved=True)
    cdir = dirs["agent"] / "agent" / "candidates" / "cand-rejected"
    # Conflicting controls force legacy_unbound and never authorize.
    (cdir / "rejected.lock").write_text("{}", encoding="utf-8")

    with pytest.raises(PromotionError):
        _promote("cand-rejected", dirs)


def test_missing_candidate_source_refuses(dirs) -> None:
    # Verified metadata/manifest without the factor artifact.
    cdir = dirs["agent"] / "agent" / "candidates" / "cand-empty"
    cdir.mkdir(parents=True)
    metadata = {
        "candidate_id": "cand-empty",
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
    (cdir / "factor.py.candidate").write_text("# placeholder\n", encoding="utf-8")
    manifest, digest, _ = build_candidate_manifest(cdir)
    (cdir / "manifest.v1.json").write_bytes(
        canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    (cdir / "factor.py.candidate").unlink()
    # Without artifact, verification fails closed — promotion refuses.
    with pytest.raises(PromotionError):
        _promote("cand-empty", dirs)


def test_ast_violation_refuses_and_nothing_written(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-evil", _EVIL_SRC)

    with pytest.raises(PromotionError, match="cand-evil"):
        _promote("cand-evil", dirs)
    assert not dirs["library"].exists() or not list(dirs["library"].iterdir())


def test_zero_factor_classes_refuses(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-none", _NO_CLASS_SRC)

    with pytest.raises(PromotionError, match="exactly one"):
        _promote("cand-none", dirs)


def test_multiple_factor_classes_refuses(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-two", _TWO_CLASSES_SRC)

    with pytest.raises(PromotionError, match="exactly one"):
        _promote("cand-two", dirs)


def test_non_string_factor_id_refuses(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-badid", _NON_STRING_ID_SRC)

    with pytest.raises(PromotionError, match="factor_id"):
        _promote("cand-badid", dirs)


def test_registry_collision_refuses_and_nothing_written(dirs) -> None:
    # factor_id "momentum" is a builtin example. Promoting it would make the
    # shared build_factor_registry() raise at every call site once committed
    # (review finding F4). Refuse before any write.
    _write_candidate(dirs["agent"], "cand-collide", _COLLIDING_ID_SRC)

    with pytest.raises(PromotionError, match="already exists in the registry"):
        _promote("cand-collide", dirs)
    assert not dirs["library"].exists() or not list(dirs["library"].iterdir())
    assert not dirs["tests"].exists() or not list(dirs["tests"].iterdir())


def test_leading_underscore_factor_id_refuses(dirs) -> None:
    # `_regenerate_init` skips `_*.py`, so an underscore factor_id would be
    # written but never registered (review finding F5). Reject it.
    _write_candidate(dirs["agent"], "cand-underscore", _UNDERSCORE_ID_SRC)

    with pytest.raises(PromotionError, match="factor_id"):
        _promote("cand-underscore", dirs)
    assert not dirs["library"].exists() or not list(dirs["library"].iterdir())


def test_python_keyword_factor_id_refuses(dirs) -> None:
    # factor_id "import" passes the [A-Za-z][A-Za-z0-9_]* regex but is a Python
    # keyword; module filename import.py yields a SyntaxError in the regenerated
    # __init__.py that bricks build_factor_registry() platform-wide (adversarial
    # re-review MAJOR). Reject keywords in the same gate.
    keyword_src = _FACTOR_SRC.replace(
        'factor_id = "wiring_test_factor"', 'factor_id = "import"'
    ).replace("WiringTestFactor", "KeywordFactor")
    _write_candidate(dirs["agent"], "cand-keyword", keyword_src)

    with pytest.raises(PromotionError, match="keyword"):
        _promote("cand-keyword", dirs)
    assert not dirs["library"].exists() or not list(dirs["library"].iterdir())


def test_alpha101_collision_refuses(dirs) -> None:
    # F4's default registry omits alpha101, so a candidate id colliding with an
    # alpha101 factor slipped through and could brick the register-library path
    # (adversarial re-review MAJOR). The reserved-id set must include alpha101.
    from quant_system.factors.library.alpha101 import ALPHA101_FACTORS

    an_alpha_id = ALPHA101_FACTORS[0]().factor_id
    src = _FACTOR_SRC.replace(
        'factor_id = "wiring_test_factor"', f'factor_id = "{an_alpha_id}"'
    ).replace("WiringTestFactor", "CollidesAlphaFactor")
    _write_candidate(dirs["agent"], "cand-alpha", src)

    with pytest.raises(PromotionError, match="already exists in the registry"):
        _promote("cand-alpha", dirs)
    assert not dirs["library"].exists() or not list(dirs["library"].iterdir())


def test_init_write_is_atomic(dirs, monkeypatch) -> None:
    # _regenerate_init must not truncate __init__.py in place: a concurrent cold
    # import of the promoted package during the write window would read a 0-byte
    # / partial file and crash build_factor_registry() platform-wide (adversarial
    # re-review MAJOR). Prove the write goes through a rename, not truncate: the
    # real __init__.py path is never observed at 0 bytes mid-write. We approximate
    # by asserting no temp truncation — write once, then confirm the file parses.
    _write_candidate(dirs["agent"], "cand-a", _FACTOR_SRC)
    _write_candidate(dirs["agent"], "cand-b", _SECOND_FACTOR_SRC)

    _promote("cand-a", dirs)
    init_path = dirs["library"] / "__init__.py"
    inode_before = init_path.stat().st_ino

    _promote("cand-b", dirs)
    # An atomic rename swaps in a new inode; an in-place truncate keeps the inode.
    assert init_path.stat().st_ino != inode_before
    ast.parse(init_path.read_text(encoding="utf-8"))


def test_partial_failure_rolls_back_orphan_module(dirs, monkeypatch) -> None:
    # If _regenerate_init raises after the module .py is written, the module must
    # be rolled back so the working tree is left untouched (docstring contract)
    # and a corrective re-run is not blocked with a misleading "already promoted"
    # (adversarial re-review MINOR).
    _write_candidate(dirs["agent"], "cand-ok", _FACTOR_SRC)

    def _boom(_library_dir):
        raise RuntimeError("init regeneration failed")

    monkeypatch.setattr(promote_module, "_regenerate_init", _boom)

    with pytest.raises(RuntimeError, match="init regeneration failed"):
        _promote("cand-ok", dirs)

    # The half-written module must NOT persist; lock released; re-run unblocked.
    assert not (dirs["library"] / "wiring_test_factor.py").exists()
    assert not (dirs["library"] / ".promote.lock").exists()


def test_second_promotion_of_same_factor_refuses(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-ok", _FACTOR_SRC)
    _promote("cand-ok", dirs)

    with pytest.raises(PromotionError, match="already exists"):
        _promote("cand-ok", dirs)


def test_existing_target_module_refuses_before_any_write(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-ok", _FACTOR_SRC)
    dirs["library"].mkdir(parents=True)
    (dirs["library"] / "wiring_test_factor.py").write_text(_FACTOR_SRC, encoding="utf-8")

    with pytest.raises(PromotionError, match="already exists"):
        _promote("cand-ok", dirs)
    # Pre-existing module untouched, no init/test written.
    assert (dirs["library"] / "wiring_test_factor.py").read_text(encoding="utf-8") == _FACTOR_SRC
    assert not (dirs["library"] / "__init__.py").exists()
    assert not dirs["tests"].exists() or not list(dirs["tests"].iterdir())


def test_promote_module_never_touches_git_or_spawns_processes() -> None:
    source = Path(promote_module.__file__.replace(".pyc", ".py")).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "Popen" not in source
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({"subprocess", "git", "os", "sys"})


def test_cli_promote_candidate_prints_files_and_gate3_line(dirs, tmp_path: Path) -> None:
    agent_root = tmp_path / "agent-output"
    candidates_dir = agent_root / "agent" / "candidates"
    _write_candidate(candidates_dir, "cand-ok", _FACTOR_SRC)

    result = runner.invoke(
        app,
        [
            "agent",
            "promote-candidate",
            "--candidate-id",
            "cand-ok",
            "--agent-output-dir",
            str(agent_root),
            "--library-dir",
            str(dirs["library"]),
            "--tests-dir",
            str(dirs["tests"]),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "factor_id=wiring_test_factor" in result.output
    assert str(dirs["library"] / "wiring_test_factor.py") in result.output
    assert str(dirs["library"] / "__init__.py") in result.output
    assert str(dirs["tests"] / "test_wiring_test_factor.py") in result.output
    gate_lines = [line for line in result.output.splitlines() if line.startswith("GATE 3")]
    assert len(gate_lines) == 1
    assert "git diff --" in gate_lines[0]


def test_cli_promote_candidate_refusal_exits_nonzero(dirs, tmp_path: Path) -> None:
    agent_root = tmp_path / "agent-output"
    candidates_dir = agent_root / "agent" / "candidates"
    _write_candidate(candidates_dir, "cand-pending", _FACTOR_SRC, approved=False)

    result = runner.invoke(
        app,
        [
            "agent",
            "promote-candidate",
            "--candidate-id",
            "cand-pending",
            "--agent-output-dir",
            str(agent_root),
            "--library-dir",
            str(dirs["library"]),
            "--tests-dir",
            str(dirs["tests"]),
        ],
    )

    assert result.exit_code == 1
    assert "promotion_refused" in result.output


# --- Concurrency: promotion lockfile (review findings F2 BLOCKER / F3 MAJOR) ---
# Two concurrent promotions of DIFFERENT factors could both pass the
# module-exists check and then interleave their `_regenerate_init` glob+rewrite,
# dropping one factor from PROMOTED_FACTORS (silent data loss). A single
# advisory lock (`.promote.lock` in library_dir) serializes the whole
# check -> write-module -> regenerate-init critical section.


def test_promotion_refuses_when_lock_present(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-ok", _FACTOR_SRC)
    dirs["library"].mkdir(parents=True)
    (dirs["library"] / ".promote.lock").write_text("", encoding="utf-8")

    with pytest.raises(PromotionError, match="in progress"):
        _promote("cand-ok", dirs)

    # Nothing written past the pre-existing lock; the held lock is left intact
    # (this promotion did not own it, so it must not remove it).
    assert (dirs["library"] / ".promote.lock").exists()
    assert not (dirs["library"] / "wiring_test_factor.py").exists()
    assert not (dirs["library"] / "__init__.py").exists()


def test_promotion_lock_released_on_success(dirs) -> None:
    _write_candidate(dirs["agent"], "cand-ok", _FACTOR_SRC)
    _promote("cand-ok", dirs)
    assert not (dirs["library"] / ".promote.lock").exists()


def test_promotion_lock_released_on_refusal(dirs) -> None:
    # A refusal that happens after lock acquisition (target module already there)
    # must still release the lock via the finally cleanup.
    _write_candidate(dirs["agent"], "cand-ok", _FACTOR_SRC)
    dirs["library"].mkdir(parents=True)
    (dirs["library"] / "wiring_test_factor.py").write_text(_FACTOR_SRC, encoding="utf-8")

    with pytest.raises(PromotionError, match="already exists"):
        _promote("cand-ok", dirs)
    assert not (dirs["library"] / ".promote.lock").exists()


def test_promotion_serializes_write_and_init(dirs, monkeypatch) -> None:
    # Deterministic proof of serialization without threads: while cand-a holds
    # the lock across its write + _regenerate_init, a re-entrant promotion of
    # cand-b must be refused ("in progress"). If the critical section were not
    # locked, the re-entrant call would proceed and corrupt PROMOTED_FACTORS.
    _write_candidate(dirs["agent"], "cand-a", _FACTOR_SRC)
    _write_candidate(dirs["agent"], "cand-b", _SECOND_FACTOR_SRC)

    real_regenerate = promote_module._regenerate_init
    reentrant_error: dict[str, object] = {}

    def _spy(library_dir):
        # Called while cand-a's lock is held. A second promotion must bounce.
        try:
            _promote("cand-b", dirs)
        except PromotionError as exc:
            reentrant_error["exc"] = exc
        return real_regenerate(library_dir)

    monkeypatch.setattr(promote_module, "_regenerate_init", _spy)

    _promote("cand-a", dirs)

    assert "exc" in reentrant_error, "re-entrant promotion was not attempted"
    assert "in progress" in str(reentrant_error["exc"])
    # cand-a landed; cand-b was blocked and wrote nothing.
    assert (dirs["library"] / "wiring_test_factor.py").exists()
    assert not (dirs["library"] / "alpha_scaffold_factor.py").exists()
