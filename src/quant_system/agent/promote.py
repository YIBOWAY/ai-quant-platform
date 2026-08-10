"""Internal Gate-3 materializer: verified snapshot -> three scoped files (D-20).

``promote_candidate`` is **not** a public CLI entry point. The public Gate 3
command is ``quant-system agent promote-candidate``, which delegates to
:mod:`quant_system.agent.promotion_workspace` and materializes only inside an
isolated detached review worktree. This module stays deliberately boring:

* **No LLM, no network, no git.** The output is plain files under caller-chosen
  library/tests roots; the human ``git diff`` review + commit IS Gate 3. This
  module must never spawn a process or import process/interpreter modules, and
  never touches ``.git`` (enforced by a static test).
* **No candidate filesystem I/O.** Callers re-verify immediately before
  invoking this materializer and pass a :class:`VerifiedCandidateSnapshot`
  plus the expected manifest digest. Only ``snapshot.artifact_bytes`` is used.
* **Refuses loudly** unless every precondition holds: digest match,
  ``approval_binding == "approved"``, the AST safety allowlist passes
  (:func:`~quant_system.agent.promotion._check_source`), the source defines
  exactly one ``BaseFactor`` subclass with a literal string ``factor_id``,
  and no promoted module of that name exists yet.
* **Never executes candidate code.** Discovery of the factor class and its
  ``factor_id`` is a static AST read.
"""

from __future__ import annotations

import ast
import keyword
import re
from pathlib import Path

from pydantic import BaseModel

from quant_system.agent.candidate_manifest import VerifiedCandidateSnapshot
from quant_system.agent.models import ReviewRecord
from quant_system.agent.promotion import CandidateLoadError, _check_source

_PROMOTED_PACKAGE = "quant_system.factors.library.promoted"
# Must start with a letter: `_regenerate_init` skips `_*.py` modules, so a
# leading-underscore factor_id would be written but never registered (F5).
_SAFE_FACTOR_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_ISO_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

_INIT_DOCSTRING = '''"""Code-reviewed, promoted factor library (Gate-3 output of D-20).

Each module under this package holds exactly one human-reviewed, git-committed
factor promoted from an approved candidate. This file is REGENERATED
deterministically by ``quant-system agent promote-candidate`` (sorted imports) -- do not
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
    snapshot: VerifiedCandidateSnapshot,
    *,
    expected_candidate_digest: str,
    library_dir: Path,
    tests_dir: Path,
    promotion_scope: str = "live_eligible",
    reviewer: str = "manual",
    automation_policy_digest: str | None = None,
    intake_contract_digest: str | None = None,
) -> PromotionResult:
    """Write the promotion diff from a verified snapshot; never touch git.

    Candidate filesystem verification belongs to the caller immediately before
    this internal materializer. All preconditions are checked before the first
    write, so a refusal leaves the working tree untouched.

    Provenance is path-free and clock-free: stable candidate ID, manifest
    schema/digest, and the UTC approval date from ``snapshot.review_record``.
    """
    library_dir = Path(library_dir)
    tests_dir = Path(tests_dir)
    candidate_id = snapshot.candidate_id

    if promotion_scope not in {"paper_only", "live_eligible"}:
        raise PromotionError("invalid promotion_scope")
    if reviewer not in {"auto", "manual"}:
        raise PromotionError("invalid promotion reviewer")
    if reviewer == "auto":
        if promotion_scope != "paper_only":
            raise PromotionError("auto promotion must be paper_only")
        if (
            not isinstance(automation_policy_digest, str)
            or _DIGEST.fullmatch(automation_policy_digest) is None
            or not isinstance(intake_contract_digest, str)
            or _DIGEST.fullmatch(intake_contract_digest) is None
        ):
            raise PromotionError("auto promotion requires exact policy and intake digests")
    elif automation_policy_digest is not None or intake_contract_digest is not None:
        raise PromotionError("manual promotion cannot claim machine-policy digests")

    # 1. Expected-digest CAS and digest-bound approval (no FS re-open).
    if snapshot.manifest_digest != expected_candidate_digest:
        raise PromotionError(
            f"candidate {candidate_id!r} manifest digest mismatch: "
            f"expected {expected_candidate_digest}, got {snapshot.manifest_digest}"
        )
    if snapshot.approval_binding != "approved":
        raise PromotionError(
            f"candidate {candidate_id!r} is not approved for promotion "
            f"(approval_binding={snapshot.approval_binding!r}); "
            "run `quant-system agent review --decision approve` first"
        )
    if snapshot.review_record is None:
        raise PromotionError(
            f"candidate {candidate_id!r} is approved but has no structured review record"
        )

    source_bytes = snapshot.artifact_bytes.get("factor.py.candidate")
    if source_bytes is None:
        raise PromotionError(f"candidate {candidate_id!r} has no factor.py.candidate")
    source = source_bytes.decode("utf-8", errors="strict")

    # 2. Static AST safety allowlist (same check as the research-time loader).
    try:
        _check_source(source, candidate_id)
    except CandidateLoadError as exc:
        raise PromotionError(str(exc)) from exc

    # 3. Static discovery of the single factor class -- no exec.
    class_name, factor_id = _extract_factor_class(source, candidate_id)
    default_lookback = _extract_default_lookback(source, candidate_id)

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

    approved_on = _approval_date_utc(snapshot.review_record)

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
        #
        # Capture the prior __init__.py bytes *before* regeneration so a failure
        # in the scaffold write (after _regenerate_init already swapped the new
        # registry in) restores the old registry atomically. Otherwise the tree
        # would keep an __init__.py that imports a module we just rolled back --
        # a registry referencing a deleted module (breaks every cold
        # build_factor_registry()).
        init_path = library_dir / "__init__.py"
        prior_init_bytes: bytes | None = (
            init_path.read_bytes() if init_path.exists() else None
        )
        _write_new(
            module_path,
            _provenance_header(
                candidate_id=candidate_id,
                manifest_schema=snapshot.manifest.schema_version,
                manifest_digest=snapshot.manifest_digest,
                approved_on=approved_on,
                promotion_scope=promotion_scope,
                reviewer=reviewer,
                automation_policy_digest=automation_policy_digest,
                intake_contract_digest=intake_contract_digest,
            )
            + source,
        )
        try:
            init_path = _regenerate_init(library_dir)

            tests_dir.mkdir(parents=True, exist_ok=True)
            _write_new(
                test_path,
                _test_scaffold(
                    class_name=class_name,
                    factor_id=factor_id,
                    default_lookback=default_lookback,
                ),
            )
        except BaseException:
            module_path.unlink(missing_ok=True)
            # Restore the prior registry (atomic rename) so no __init__.py
            # references the just-rolled-back module. If there was no prior
            # __init__.py, remove the one _regenerate_init may have written.
            if prior_init_bytes is not None:
                tmp_restore = library_dir / "__init__.py.restore.tmp"
                tmp_restore.write_bytes(prior_init_bytes)
                tmp_restore.replace(init_path)
            else:
                init_path.unlink(missing_ok=True)
            raise
    finally:
        lock_path.unlink(missing_ok=True)

    return PromotionResult(
        factor_id=factor_id,
        module_path=module_path,
        test_path=test_path,
        init_path=init_path,
    )


def _approval_date_utc(review_record: ReviewRecord) -> str:
    """Return YYYY-MM-DD from the structured approval timestamp (never wall clock)."""
    raw = review_record.created_at
    if not isinstance(raw, str) or not raw:
        raise PromotionError("approval record missing created_at")
    match = _ISO_DATE_PREFIX.match(raw)
    if match is None:
        raise PromotionError(
            f"approval record created_at is not a valid ISO timestamp: {raw!r}"
        )
    return match.group(1)


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


def _extract_default_lookback(source: str, context: str) -> int:
    tree = ast.parse(source)
    factor_classes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _has_base_factor_base(node)
    ]
    if len(factor_classes) != 1:
        raise PromotionError(
            f"candidate {context!r} must define exactly one BaseFactor subclass"
        )
    for stmt in factor_classes[0].body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        if any(
            isinstance(target, ast.Name) and target.id == "default_lookback"
            for target in targets
        ):
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and not isinstance(value.value, bool)
                and value.value > 0
            ):
                return value.value
            break
    raise PromotionError(
        f"candidate {context!r} must assign a positive literal default_lookback"
    )


def _provenance_header(
    *,
    candidate_id: str,
    manifest_schema: str,
    manifest_digest: str,
    approved_on: str,
    promotion_scope: str,
    reviewer: str,
    automation_policy_digest: str | None,
    intake_contract_digest: str | None,
) -> str:
    return (
        "# Promoted factor -- generated by `quant-system agent promote-candidate` "
        "(Gate 3, D-20).\n"
        f"# candidate_id: {candidate_id}\n"
        f"# manifest_schema: {manifest_schema}\n"
        f"# manifest_digest: {manifest_digest}\n"
        f"# approved_on: {approved_on}\n"
        f"# promotion_scope: {promotion_scope}\n"
        f"# promotion_reviewer: {reviewer}\n"
        f"# automation_policy_digest: {automation_policy_digest or 'none'}\n"
        f"# intake_contract_digest: {intake_contract_digest or 'none'}\n"
        "# source: verbatim copy of factor.py.candidate at promotion time.\n"
    )


def _render_promoted_init(entries: list[tuple[str, str]]) -> str:
    """Render the promoted ``__init__.py`` source deterministically.

    ``entries`` is a list of ``(module_name, class_name)`` pairs. The output is
    a pure function of the sorted entry list: no clock, no path, no glob. Each
    factor is exposed through a module-level import (``from ... import module
    as module_module``) and referenced in ``PROMOTED_FACTORS`` as
    ``module_module.ClassName``. Imports form one continuous first-party block
    after ``BaseFactor`` (no blank line) and wrap only when a single import
    would exceed the 100-column limit -- this is exactly the layout external
    ``ruff check`` (isort I001 + E501) accepts, so the generated file is lint
    clean without the generator ever spawning ruff (which is forbidden here).
    """
    entries = sorted(entries, key=lambda entry: entry[0])

    lines: list[str] = [
        _INIT_DOCSTRING,
        "",
        "from __future__ import annotations",
        "",
        "from quant_system.factors.base import BaseFactor",
    ]
    for module_name, _class_name in entries:
        alias = f"{module_name}_module"
        single = f"from {_PROMOTED_PACKAGE} import {module_name} as {alias}"
        if len(single) <= 100:
            lines.append(single)
        else:
            lines.extend(
                [
                    f"from {_PROMOTED_PACKAGE} import (",
                    f"    {module_name} as {alias},",
                    ")",
                ]
            )
    if entries:
        lines.extend(["", "PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = ("])
        lines.extend(
            f"    {module_name}_module.{class_name}," for module_name, class_name in entries
        )
        lines.append(")")
    else:
        lines.extend(["", "PROMOTED_FACTORS: tuple[type[BaseFactor], ...] = ()"])
    lines.extend(["", '__all__ = ["PROMOTED_FACTORS"]', ""])
    return "\n".join(lines)


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

    content = _render_promoted_init(entries)

    init_path = library_dir / "__init__.py"
    # Atomic write: a concurrent cold import of the promoted package (any
    # build_factor_registry() call site) must never observe a truncated/0-byte
    # __init__.py. write_text truncates in place; instead write a temp file in
    # the same directory and Path.replace (atomic rename on POSIX) it into place
    # so readers always see the complete old or complete new file (adversarial
    # re-review). Path.replace keeps this module dependency-free (pathlib only).
    tmp_path = library_dir / "__init__.py.tmp"
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(init_path)
    return init_path


def _test_scaffold(
    *, class_name: str, factor_id: str, default_lookback: int
) -> str:
    synthetic_rows = max(80, default_lookback + 20)
    import_module = f"{_PROMOTED_PACKAGE}.{factor_id}"
    single_import = f"from {import_module} import {class_name}"
    if len(single_import) <= 100:
        imports = f"import pandas as pd\n\n{single_import}"
        factor_helpers = ""
        factor_constructor = class_name
        expected_factor_id = f'"{factor_id}"'
    else:
        imports = "from importlib import import_module\n\nimport pandas as pd"
        factor_helpers = (
            f"\n{_render_string_constant('EXPECTED_FACTOR_ID', factor_id)}\n\n"
            f"{_render_string_constant('FACTOR_CLASS_NAME', class_name)}\n\n\n"
            "def _factor():\n"
            "    factor_module = import_module(\n"
            f'        f"{_PROMOTED_PACKAGE}.{{EXPECTED_FACTOR_ID}}"\n'
            "    )\n"
            "    return getattr(factor_module, FACTOR_CLASS_NAME)()"
        )
        factor_constructor = "_factor"
        expected_factor_id = "EXPECTED_FACTOR_ID"
    return f'''"""Scaffold test for a promoted factor (generated at Gate 3).

Extend with factor-specific assertions during the git-diff review.
"""

from __future__ import annotations

{imports}
{factor_helpers}


def _synthetic_ohlcv(rows: int = {synthetic_rows}) -> pd.DataFrame:
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


def test_factor_metadata() -> None:
    factor = {factor_constructor}()
    metadata = factor.metadata
    assert metadata.factor_id == {expected_factor_id}
    assert metadata.factor_name
    assert metadata.factor_version
    assert metadata.lookback > 0
    assert metadata.description


def test_factor_computes_on_synthetic_ohlcv() -> None:
    factor = {factor_constructor}()
    result = factor.compute(_synthetic_ohlcv())
    assert not result.empty
    assert set(result["factor_id"]) == {{{expected_factor_id}}}
    assert result["value"].notna().all()
'''


def _render_string_constant(name: str, value: str) -> str:
    chunks = [value[index : index + 72] for index in range(0, len(value), 72)]
    return "\n".join(
        [
            f"{name} = (",
            *(f"    {chunk!r}" for chunk in chunks),
            ")",
        ]
    )
