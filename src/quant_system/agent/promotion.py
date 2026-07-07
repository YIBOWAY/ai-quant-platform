"""First consumer of the SafetyGate: load human-approved candidate factors.

The gate stays observation-only -- this module NEVER creates approval locks;
it only loads factor sources for candidates a human has already approved via
``quant-system agent review --decision approve``.

Two layers of defense sit behind that human gate:

1. A static **AST** check rejects any candidate source that imports a module
   outside an explicit allowlist or references any dynamic code-execution
   primitive (``__import__``, ``importlib``, ``eval``, ``exec``, ``compile``,
   ``globals``, ``vars``, ``builtins``, ``getattr`` on builtins, ``ctypes``).
   AST analysis is robust to the obfuscation that defeated the prior substring
   blocklist (whitespace, concatenation, ``chr``-assembly, nested ``exec``).
2. The candidate source is ``exec``'d in a namespace whose ``__builtins__`` is
   emptied, so even a name the AST missed cannot reach ``__import__``/``eval``
   via the builtins dict that CPython otherwise auto-injects.

These are defense-in-depth, NOT a sandbox. The human approval of the candidate
factor source remains the primary control. Both layers can be defeated by a
sufficiently determined author; their job is to make accidental/LLM-drift
escapes noisy and to stop the trivial bypasses, not to contain a hostile
cryptographic adversary who has already cleared human review.
"""

from __future__ import annotations

import ast
import builtins as _builtins
import re
from pathlib import Path

from quant_system.agent.safety import SafetyGate
from quant_system.factors.base import BaseFactor
from quant_system.factors.registry import FactorRegistry

# External module roots a candidate factor may import. Numeric/data plumbing and
# Python type helpers are allowed by root so submodules such as collections.abc
# or numpy.linalg can work without opening unrelated platform modules.
_ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "math",
        "statistics",
        "datetime",
        "collections",
        "itertools",
        "functools",
        "operator",
        "typing",
        "numpy",
        "pandas",
    }
)

# Exact in-repo modules candidate factors may import. Do not allow the
# `quant_system` root package here: many safe-looking submodules re-export
# filesystem, CLI, or process objects that candidate code must not reach.
_ALLOWED_PLATFORM_MODULES: frozenset[str] = frozenset(
    {
        "quant_system.factors.base",
    }
)

# Names whose bare reference in any expression context means the candidate is
# reaching for a dynamic import / code execution / introspection primitive.
_FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "__import__",
        "importlib",
        "eval",
        "exec",
        "compile",
        "globals",
        "vars",
        "builtins",
        "__builtins__",
        "ctypes",
        "getattr",
        "setattr",
        "delattr",
        "locals",
        "dir",
        "open",
        "object",
        "__class__",
        "__mro__",
        "__subclasses__",
        # Introspection gadgets: string-indirection chains such as
        # `type(x).__getattribute__(x, "__class__")` walk from any object to
        # object.__subclasses__() and reach subprocess.Popen without ever naming
        # a forbidden import (review finding F1). Deny the gadget vocabulary.
        "__getattribute__",
        "__getattr__",
        "__setattr__",
        "__delattr__",
        "__dict__",
        "__globals__",
        "__closure__",
        "__code__",
        "__func__",
        "__self__",
        "__bases__",
        "__base__",
        "__init_subclass__",
        "__reduce__",
        "__reduce_ex__",
        "__getstate__",
        "__setstate__",
        # Attribute-fetch-by-name primitives: these turn a runtime-built string
        # (e.g. "__glob" + "als__", which dodges the dunder-constant rule) into an
        # arbitrary attribute access. `operator`/`functools` are allowed import
        # roots, so the primitives themselves must be denied (review finding F1
        # residual, caught in adversarial re-review).
        "attrgetter",
        "methodcaller",
        "getattr_static",
    }
)

# Any dunder attribute/name is a gadget primitive; reject them generically so
# the check does not depend on enumerating every one. `__init__` is the sole
# exception: `super().__init__(...)` constructor chaining is legitimate.
_DUNDER_RE = re.compile(r"^__\w+__$")
_ALLOWED_DUNDERS: frozenset[str] = frozenset({"__init__"})

# Dangerous stdlib module names. numpy/pandas are allowed import ROOTS but they
# re-export os/subprocess/etc. as PLAIN (non-dunder) attributes, so a chain like
# `np.ctypeslib.os.system(...)` or `pd.compat.os` reaches a shell/filesystem
# through an allowed root without ever importing the module directly (adversarial
# re-review BLOCKER). The AST check cannot enumerate every re-export path, so it
# rejects the dangerous module NAME wherever it appears as an attribute or name.
# Per D-16 this is defense-in-depth, not a sandbox: the goal is to make such an
# attack look obviously weird (`pd.io.common.os.system` is not factor code) so
# the human Gate-2 reviewer catches it, and to stop the trivial/LLM-drift escape.
_FORBIDDEN_MODULE_NAMES: frozenset[str] = frozenset(
    {
        "os", "sys", "subprocess", "ctypes", "inspect", "importlib", "imp",
        "platform", "shutil", "socket", "pickle", "cPickle", "marshal", "shelve",
        "pty", "posix", "nt", "code", "codeop", "runpy", "multiprocessing",
        "threading", "signal", "resource", "fcntl", "mmap", "gc", "atexit",
        "pdb", "trace", "tracemalloc", "site", "sysconfig", "pkgutil", "modulefinder",
        "cython", "cffi", "distutils", "setuptools", "urllib", "http", "ftplib",
        "smtplib", "telnetlib", "asyncio", "webbrowser", "tempfile",
    }
)

# Reader / (de)serialization methods that read arbitrary files or execute pickle
# payloads at call time. `pd.read_pickle(...)` is an arbitrary-code primitive and
# `pd.read_csv(...)` an arbitrary-file read (adversarial re-review MAJOR). Factors
# receive their price frame as a compute() argument and never load their own data,
# so no legitimate factor calls these — reject the method NAME wherever it appears.
_FORBIDDEN_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "read_pickle", "read_csv", "read_table", "read_parquet", "read_feather",
        "read_hdf", "read_excel", "read_json", "read_orc", "read_sql",
        "read_sql_query", "read_sql_table", "read_stata", "read_sas", "read_spss",
        "read_gbq", "read_html", "read_xml", "read_fwf", "read_clipboard",
        "to_pickle", "load", "loads", "system", "popen", "fromfile", "memmap",
        "genfromtxt", "loadtxt", "fromregex", "DataSource",
    }
)

# A restricted ``__builtins__`` for the candidate ``exec`` namespace. CPython
# auto-injects the *full* builtins dict when ``__builtins__`` is absent, exposing
# ``__import__``/``eval``/``exec``/``open``/``getattr`` to the candidate source.
# We pass an explicit mapping instead, exposing only the safe builtins a factor
# genuinely needs (math/sequence/container helpers) plus a *guarded*
# ``__import__`` that enforces the same module allowlist as the static AST check
# at runtime -- defense in depth: even if the AST check missed an obfuscated
# import, the live ``__import__`` still rejects disallowed modules.

_SAFE_BUILTIN_NAMES: frozenset[str] = frozenset(
    {
        "abs", "min", "max", "sum", "round", "len", "range", "enumerate", "zip",
        "sorted", "reversed", "map", "filter", "any", "all", "int", "float",
        "str", "bool", "list", "tuple", "dict", "set", "frozenset", "print",
        "isinstance", "issubclass", "type", "super", "None", "True", "False",
    }
)


def _make_safe_builtins() -> dict[str, object]:
    def _guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        if not _is_allowed_import(name):
            raise ImportError(f"candidate import of {name!r} is not permitted")
        return _builtins.__import__(name, globals, locals, fromlist, level)

    safe: dict[str, object] = {name: getattr(_builtins, name) for name in _SAFE_BUILTIN_NAMES}
    safe["__import__"] = _guarded_import
    safe["__build_class__"] = _builtins.__build_class__  # required for `class` statements
    return safe


class CandidateLoadError(RuntimeError):
    """A candidate factor source failed the static safety check."""


def _is_allowed_import(module_name: str) -> bool:
    root = module_name.split(".")[0]
    if root in _ALLOWED_IMPORT_ROOTS:
        return True
    return any(
        module_name == allowed or module_name.startswith(f"{allowed}.")
        for allowed in _ALLOWED_PLATFORM_MODULES
    )


def _check_source(source: str, candidate_id: str) -> None:
    """Statically reject disallowed imports and dangerous name references.

    Raises ``CandidateLoadError`` on the first violation.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CandidateLoadError(
            f"candidate {candidate_id!r} is not valid Python: {exc}"
        ) from exc

    for node in ast.walk(tree):
        # `import x` / `import x.y` / `import x as z`
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_allowed_import(alias.name):
                    raise CandidateLoadError(
                        f"candidate {candidate_id!r} imports disallowed module {alias.name!r}"
                    )
            continue
        # `from x import y` (optionally `from . import y`)
        if isinstance(node, ast.ImportFrom):
            if node.module is None:
                # relative `from . import y` — root is the package itself; treat
                # as allowed only if it resolves under a permitted package. We
                # cannot resolve relatives statically without the package, so
                # reject (candidate factors are self-contained, no relative imports).
                raise CandidateLoadError(
                    f"candidate {candidate_id!r} uses a relative import, which is not permitted"
                )
            if not _is_allowed_import(node.module):
                raise CandidateLoadError(
                    f"candidate {candidate_id!r} imports from disallowed module {node.module!r}"
                )
            # An allowed module can still re-export a dangerous name:
            # `from numpy.ctypeslib import os` imports the os module itself.
            for alias in node.names:
                if alias.name in _FORBIDDEN_MODULE_NAMES:
                    raise CandidateLoadError(
                        f"candidate {candidate_id!r} imports forbidden name {alias.name!r} "
                        f"from {node.module!r}"
                    )
            continue
        # Any bare/attribute reference to a forbidden name.
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise CandidateLoadError(
                f"candidate {candidate_id!r} references forbidden name {node.id!r}"
            )
        # A dunder string CONSTANT (e.g. "__subclasses__", "__class__") is the raw
        # material a getattr/gadget walk consumes; reject it wherever it appears
        # so string-indirection cannot smuggle a forbidden attribute name past the
        # ast.Attribute checks (review finding F1).
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _DUNDER_RE.fullmatch(node.value) is not None
            and node.value not in _ALLOWED_DUNDERS
        ):
            raise CandidateLoadError(
                f"candidate {candidate_id!r} references forbidden dunder string "
                f"constant {node.value!r}"
            )
        if isinstance(node, ast.Attribute):
            # Generic dunder-attribute rejection: `x.__globals__`, `x.__class__`,
            # `x.__getattribute__(...)` etc. are all gadget primitives. `__init__`
            # (super().__init__()) is the single legitimate exception.
            if (
                _DUNDER_RE.fullmatch(node.attr) is not None
                and node.attr not in _ALLOWED_DUNDERS
            ):
                raise CandidateLoadError(
                    f"candidate {candidate_id!r} references forbidden dunder attribute "
                    f"{node.attr!r}"
                )
            # Dangerous stdlib module re-exported as a plain attribute of an
            # allowed root (`np.ctypeslib.os`, `pd.compat.subprocess`).
            if node.attr in _FORBIDDEN_MODULE_NAMES:
                raise CandidateLoadError(
                    f"candidate {candidate_id!r} references forbidden module attribute "
                    f"{node.attr!r}"
                )
            # File-IO / deserialization reader methods (`pd.read_pickle`,
            # `np.fromfile`) — arbitrary file read / pickle RCE at call time.
            if node.attr in _FORBIDDEN_METHOD_NAMES:
                raise CandidateLoadError(
                    f"candidate {candidate_id!r} references forbidden method "
                    f"{node.attr!r}"
                )
            attr_chain = _attribute_chain(node)
            forbidden_part = next(
                (part for part in attr_chain if part in _FORBIDDEN_NAMES),
                None,
            )
            if forbidden_part is not None:
                raise CandidateLoadError(
                    f"candidate {candidate_id!r} references forbidden attribute chain "
                    f"{'.'.join(attr_chain)!r}"
                )


def _attribute_chain(node: ast.Attribute) -> list[str]:
    parts: list[str] = [node.attr]
    cur: ast.expr = node.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    parts.reverse()
    return parts


def load_approved_factor_candidates(
    registry: FactorRegistry,
    *,
    candidates_dir: str | Path,
) -> list[str]:
    root = Path(candidates_dir)
    if not root.exists():
        return []
    gate = SafetyGate(root)
    loaded: list[str] = []
    for candidate_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        source_path = candidate_dir / "factor.py.candidate"
        if not source_path.exists():
            continue
        if not gate.allow_promotion(candidate_dir.name):
            continue
        source = source_path.read_text(encoding="utf-8")
        _check_source(source, candidate_dir.name)
        # Restricted namespace: pass an explicit __builtins__ so CPython does not
        # inject the full builtins dict (which would expose __import__/eval/exec).
        # The guarded __import__ enforces the module allowlist at runtime too.
        # __name__ is seeded so `class` statements (and any module-introspection)
        # see a conventional module name rather than NameError.
        namespace: dict[str, object] = {
            "__builtins__": _make_safe_builtins(),
            "__name__": candidate_dir.name,
        }
        # Human-approved candidate (approved.lock verified above); static check passed.
        exec(compile(source, str(source_path), "exec"), namespace)  # noqa: S102
        for value in namespace.values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseFactor)
                and value is not BaseFactor
            ):
                try:
                    registry.register(value)
                except ValueError:
                    continue  # already registered -- idempotent reload
                loaded.append(value.factor_id)
    return loaded
