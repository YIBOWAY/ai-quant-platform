"""Parallel invariants L2/L3/L5, checked by an AST scan of the v2 package.

* L2 — the family layer never constructs a writable ``TrialsLedger`` and never
  calls ``append``/``append_many``; the only writer in the package is
  ``append_verdict_v2``.
* L3 — the package references no sleeve creation, candidate admission, hang or
  allocation symbol.
* L5 — activation imports only the shared pure correlation calculation; v2
  grading, verdict persistence and authority switching stay behind the common
  quality/admission interfaces.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
_PACKAGE = _SRC / "quant_system" / "research" / "gate_v2"
_GRADING = _SRC / "quant_system" / "research" / "fingerprint_grading.py"

_FORBIDDEN_CALLS = {
    "create_sleeve",
    "record_verified_candidate",
    "hang_candidate",
    "_existing_hang_sleeve",
    "enable_strategy",
    "_project_activation_eligibility",
    "append_many",
    "record_event",
}
_FORBIDDEN_NAMES = {"TrialsLedger", "_HANG_ALLOCATION_CASH", "_HANG_ALLOCATION"}


def _trees() -> list[tuple[Path, ast.Module]]:
    paths = sorted(_PACKAGE.glob("*.py"))
    if _GRADING.exists():
        paths.append(_GRADING)
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))) for path in paths
    ]


def _called_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _referenced_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
    return names


def test_l2_no_ledger_append_anywhere_in_the_v2_package() -> None:
    for path, tree in _trees():
        called = _called_names(tree)
        if path.name == "verdict.py":
            # verdict.py owns the one legitimate writer; the ledger appenders are
            # still banned there.
            assert "append_many" not in called
            continue
        assert called.isdisjoint(_FORBIDDEN_CALLS), (path.name, called & _FORBIDDEN_CALLS)


def test_l2_no_writable_trials_ledger_is_constructed() -> None:
    for path, tree in _trees():
        assert "TrialsLedger" not in _referenced_names(tree), path.name


def test_l3_no_funding_or_activation_symbol_is_referenced() -> None:
    for path, tree in _trees():
        referenced = _referenced_names(tree)
        assert referenced.isdisjoint(_FORBIDDEN_NAMES), (path.name, referenced & _FORBIDDEN_NAMES)


def test_l3_the_only_writer_is_append_verdict_v2() -> None:
    from quant_system.research.gate_v2 import verdict

    source = Path(verdict.__file__).read_text(encoding="utf-8")
    assert "def append_verdict_v2" in source
    assert source.count("fcntl.flock") == 1


@pytest.mark.parametrize(
    "module",
    [
        "research/strategy_library.py",
        "research/strategy_library_cli.py",
        "research/strategy_definition.py",
    ],
)
def test_l4_v1_consumers_do_not_import_gate_v2(module: str) -> None:
    assert "gate_v2" not in (_SRC / "quant_system" / module).read_text(encoding="utf-8")


def test_l5_activation_imports_only_shared_pure_correlation() -> None:
    allowed = {
        "execution/assistant_remote.py": {
            ("quant_system.research.gate_v2.correlation_v2", "raw_concentration_v2"),
        },
        "research/strategy_validation_process.py": set(),
    }
    for module, expected in allowed.items():
        path = _SRC / "quant_system" / module
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "quant_system.research.gate_v2"
            ):
                imports.update((node.module, alias.name) for alias in node.names)
            elif isinstance(node, ast.Import):
                imports.update(
                    (alias.name, None) for alias in node.names
                    if alias.name.startswith("quant_system.research.gate_v2")
                )
        assert imports == expected, (module, imports)
        assert _called_names(tree).isdisjoint(
            {"evaluate_gate_v2", "grade_v2", "append_verdict_v2"}
        ), module


def test_family_module_never_appends(tmp_path: Path) -> None:
    from quant_system.research.gate_v2.family import project_family_v2

    result = project_family_v2(
        trials_rows=[], universe_digest="0" * 64, curve_resolver=lambda row: None
    )
    assert result["n_trials"] == 0
    assert result["members"] == []
    assert list(tmp_path.rglob("*")) == []
