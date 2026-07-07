"""Deterministic Gate-3 promotion: approved candidate -> working-tree diff (D-20).

``promote_candidate`` turns a human-approved candidate factor into reviewable
source files under the promoted library. It is deliberately boring:

* **No LLM, no network, no git.** The output is plain files in the working
  tree; the human ``git diff`` review + commit IS Gate 3. This module must
  never spawn a process or import process/interpreter modules, and never
  touches ``.git`` (enforced by a static test).
* **Refuses loudly** unless every precondition holds: ``approved.lock`` present
  and no ``rejected.lock`` (:class:`~quant_system.agent.safety.SafetyGate`),
  the AST safety allowlist passes (:func:`~quant_system.agent.promotion._check_source`),
  the source defines exactly one ``BaseFactor`` subclass with a literal string
  ``factor_id``, and no promoted module of that name exists yet.
* **Never executes candidate code.** Discovery of the factor class and its
  ``factor_id`` is a static AST read.
"""

from __future__ import annotations

import ast
import keyword
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from quant_system.agent.promotion import CandidateLoadError, _check_source
from quant_system.agent.safety import SafetyGate

_PROMOTED_PACKAGE = "quant_system.factors.library.promoted"
# Must start with a letter: `_regenerate_init` skips `_*.py` modules, so a
# leading-underscore factor_id would be written but never registered (F5).
_SAFE_FACTOR_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_INIT_DOCSTRING = '''"""Code-reviewed, promoted factor library (Gate-3 output of D-20).

Each module under this package holds exactly one human-reviewed, git-committed
factor promoted from an approved candidate. This file is REGENERATED
deterministically by ``agent promote-candidate`` (sorted imports) -- do not
edit by hand. ``PROMOTED_FACTORS`` is the single source the registry factory
reads. It starts empty; promotions append.
"""'''


class PromotionError(RuntimeError):
    """The candidate cannot be promoted; nothing was written."""


class PromotionResult(BaseModel):
    factor_id: str
    module_path: Path
    test_path: Path
    init_path: Path


def promote_candidate(
    candidate_id: str,
    *,
    candidates_dir: Path,
    library_dir: Path,
    tests_dir: Path,
    promotion_date: str | None = None,
) -> PromotionResult:
    """Write the promotion diff for one approved candidate; never touch git.

    All preconditions are checked before the first write, so a refusal leaves
    the working tree untouched. ``promotion_date`` is injectable so tests stay
    deterministic; it defaults to today (UTC).
    """
    candidates_dir = Path(candidates_dir)
    library_dir = Path(library_dir)
    tests_dir = Path(tests_dir)

    # 1. Human approval gate (approved.lock present, no rejected.lock).
    if not SafetyGate(candidates_dir).allow_promotion(candidate_id):
        raise PromotionError(
            f"candidate {candidate_id!r} is not approved for promotion "
            "(approved.lock missing or rejected.lock present); "
            "run `agent review --decision approve` first"
        )

    source_path = candidates_dir / candidate_id / "factor.py.candidate"
    if not source_path.exists():
        raise PromotionError(f"candidate {candidate_id!r} has no factor.py.candidate")
    source = source_path.read_text(encoding="utf-8")

    # 2. Static AST safety allowlist (same check as the research-time loader).
    try:
        _check_source(source, candidate_id)
    except CandidateLoadError as exc:
        raise PromotionError(str(exc)) from exc

    # 3. Static discovery of the single factor class -- no exec.
    class_name, factor_id = _extract_factor_class(source, candidate_id)

    # 4. Registry-collision refusal (review finding F4 + adversarial re-review):
    # a promoted module whose factor_id shadows any registrable factor would make
    # a `build_factor_registry()`/`register_*_library()` call raise at its call
    # site once the diff is committed. The default registry omits alpha101 (it is
    # layered on only at specific call sites), so the reserved set must union
    # every registrable library, not just the default registry. Lazy imports
    # avoid a circular import (registry -> promotion -> FactorRegistry).
    from quant_system.factors.library.alpha101 import ALPHA101_FACTORS
    from quant_system.factors.registry import build_factor_registry

    existing_ids = set(build_factor_registry(include_promoted=True).factor_ids())
    existing_ids |= {factor_cls().factor_id for factor_cls in ALPHA101_FACTORS}
    if factor_id in existing_ids:
        raise PromotionError(
            f"factor_id {factor_id!r} already exists in the registry "
            "(builtin, promoted, or a registrable library); choose a distinct factor_id"
        )

    module_path = library_dir / f"{factor_id}.py"
    test_path = tests_dir / f"test_{factor_id}.py"

    promoted_on = promotion_date or datetime.now(UTC).date().isoformat()
    approval_note = candidates_dir / candidate_id / "approved.lock"

    # 5. Serialize the check -> write -> regenerate-init critical section with an
    # advisory lock (review findings F2/F3). Two concurrent promotions must not
    # both pass the module-exists check and then interleave their
    # `_regenerate_init` glob+rewrite, which would drop a factor from
    # PROMOTED_FACTORS. `touch(exist_ok=False)` is an atomic exclusive create;
    # the finally clause releases only the lock this call created.
    library_dir.mkdir(parents=True, exist_ok=True)
    lock_path = library_dir / ".promote.lock"
    try:
        lock_path.touch(exist_ok=False)
    except FileExistsError as exc:
        raise PromotionError(
            f"a promotion is in progress ({lock_path} exists); if no promotion "
            "is running, remove the stale lock file and retry"
        ) from exc

    try:
        if module_path.exists():
            raise PromotionError(
                f"promoted module {module_path} already exists; "
                f"factor {factor_id!r} was already promoted"
            )
        if test_path.exists():
            raise PromotionError(f"test scaffold {test_path} already exists")

        # All checks passed -- write the three files (Gate-3 diff). Exclusive
        # create ("x") is a hard backstop against writing over an existing file
        # even if a check above were bypassed. If any step after the module write
        # fails, roll the module back so a refusal leaves the working tree
        # untouched (docstring contract) and a re-run is not falsely blocked.
        _write_new(
            module_path,
            _provenance_header(
                candidate_id=candidate_id,
                approval_note=approval_note,
                promoted_on=promoted_on,
            )
            + source,
        )
        try:
            init_path = _regenerate_init(library_dir)

            tests_dir.mkdir(parents=True, exist_ok=True)
            _write_new(
                test_path,
                _test_scaffold(class_name=class_name, factor_id=factor_id),
            )
        except BaseException:
            module_path.unlink(missing_ok=True)
            raise
    finally:
        lock_path.unlink(missing_ok=True)

    return PromotionResult(
        factor_id=factor_id,
        module_path=module_path,
        test_path=test_path,
        init_path=init_path,
    )


def _write_new(path: Path, content: str) -> None:
    """Write ``content`` to ``path``, refusing to overwrite an existing file."""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)


def _extract_factor_class(source: str, context: str) -> tuple[str, str]:
    """Statically find the single ``BaseFactor`` subclass and its ``factor_id``."""
    tree = ast.parse(source)
    factor_classes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _has_base_factor_base(node)
    ]
    if len(factor_classes) != 1:
        raise PromotionError(
            f"candidate {context!r} must define exactly one BaseFactor subclass, "
            f"found {len(factor_classes)}"
        )
    class_def = factor_classes[0]
    factor_id = _extract_factor_id(class_def)
    if factor_id is None:
        raise PromotionError(
            f"candidate {context!r} class {class_def.name!r} must assign a literal "
            "string factor_id in its class body"
        )
    if _SAFE_FACTOR_ID.fullmatch(factor_id) is None:
        raise PromotionError(
            f"candidate {context!r} factor_id {factor_id!r} is not a safe module name"
        )
    # A factor_id that is a Python keyword passes the regex but yields an
    # unimportable module filename (e.g. import.py -> `from ...promoted.import
    # import ...` is a SyntaxError), which would brick build_factor_registry()
    # platform-wide (adversarial re-review). Reject hard and soft keywords.
    if keyword.iskeyword(factor_id) or keyword.issoftkeyword(factor_id):
        raise PromotionError(
            f"candidate {context!r} factor_id {factor_id!r} is a Python keyword "
            "and cannot be a module name"
        )
    return class_def.name, factor_id


def _has_base_factor_base(class_def: ast.ClassDef) -> bool:
    for base in class_def.bases:
        if isinstance(base, ast.Name) and base.id == "BaseFactor":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseFactor":
            return True
    return False


def _extract_factor_id(class_def: ast.ClassDef) -> str | None:
    for stmt in class_def.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "factor_id":
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                return None
    return None


def _provenance_header(*, candidate_id: str, approval_note: Path, promoted_on: str) -> str:
    return (
        "# Promoted factor -- generated by `agent promote-candidate` (Gate 3, D-20).\n"
        f"# candidate_id: {candidate_id}\n"
        f"# approval_note: {approval_note}\n"
        f"# promoted_on: {promoted_on}\n"
        "# source: verbatim copy of factor.py.candidate at promotion time.\n"
    )


def _regenerate_init(library_dir: Path) -> Path:
    """Rewrite ``__init__.py`` from the on-disk promoted modules, sorted."""
    entries: list[tuple[str, str]] = []  # (module_name, class_name)
    for path in sorted(library_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        class_name, factor_id = _extract_factor_class(
            path.read_text(encoding="utf-8"), path.name
        )
        if factor_id != path.stem:
            raise PromotionError(
                f"promoted module {path} declares factor_id {factor_id!r}, "
                "which does not match its filename"
            )
        entries.append((path.stem, class_name))

    lines: list[str] = [
        _INIT_DOCSTRING,
        "",
        "from __future__ import annotations",
        "",
        "from quant_system.factors.base import BaseFactor",
    ]
    if entries:
        lines.append("")
        for module_name, class_name in entries:
            lines.append(
                f"from {_PROMOTED_PACKAGE}.{module_name} "
                f"import {class_name} as {module_name}_factor"
            )
        lines.extend(["", "PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = ("])
        lines.extend(f"    {module_name}_factor," for module_name, _ in entries)
        lines.append(")")
    else:
        lines.extend(["", "PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = ()"])
    lines.extend(["", '__all__ = ["PROMOTED_FACTORS"]', ""])

    init_path = library_dir / "__init__.py"
    # Atomic write: a concurrent cold import of the promoted package (any
    # build_factor_registry() call site) must never observe a truncated/0-byte
    # __init__.py. write_text truncates in place; instead write a temp file in
    # the same directory and Path.replace (atomic rename on POSIX) it into place
    # so readers always see the complete old or complete new file (adversarial
    # re-review). Path.replace keeps this module dependency-free (pathlib only).
    tmp_path = library_dir / "__init__.py.tmp"
    tmp_path.write_text("\n".join(lines), encoding="utf-8")
    tmp_path.replace(init_path)
    return init_path


def _test_scaffold(*, class_name: str, factor_id: str) -> str:
    return f'''"""Scaffold test for promoted factor {factor_id!r} (generated at Gate 3).

Extend with factor-specific assertions during the git-diff review.
"""

from __future__ import annotations

import pandas as pd

from {_PROMOTED_PACKAGE}.{factor_id} import {class_name}


def _synthetic_ohlcv(rows: int = 80) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    close = 100.0 + 0.5 * pd.Series(range(rows), dtype="float64")
    return pd.DataFrame(
        {{
            "symbol": ["TEST"] * rows,
            "timestamp": timestamps,
            "close": close,
            "volume": [1_000_000.0] * rows,
        }}
    )


def test_{factor_id}_metadata() -> None:
    factor = {class_name}()
    metadata = factor.metadata
    assert metadata.factor_id == "{factor_id}"
    assert metadata.factor_name
    assert metadata.factor_version
    assert metadata.lookback > 0
    assert metadata.description


def test_{factor_id}_computes_on_synthetic_ohlcv() -> None:
    factor = {class_name}()
    result = factor.compute(_synthetic_ohlcv())
    assert not result.empty
    assert set(result["factor_id"]) == {{"{factor_id}"}}
    assert result["value"].notna().all()
'''
