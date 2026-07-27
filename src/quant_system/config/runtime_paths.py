"""Fail-closed defaults for runtime paths that live outside the distribution.

Installed ``quant_system`` modules can live under ``site-packages``.  They must
never infer repository or HQA authority locations from ``__file__``.  Operators
bind those locations through the corresponding settings environment variables;
the deterministic sentinel keeps ordinary read-only configuration inspectable
while every authority probe remains closed until that binding is present.
"""

from __future__ import annotations

from pathlib import Path

UNCONFIGURED_RUNTIME_ROOT = Path("/__quant_system_unconfigured__")


def unconfigured_runtime_path(name: str) -> Path:
    """Return a stable, absolute path that cannot masquerade as a checkout."""

    if not name or "/" in name or name in {".", ".."}:
        raise ValueError("unconfigured runtime path name must be one segment")
    return UNCONFIGURED_RUNTIME_ROOT / name


def is_unconfigured_runtime_path(path: Path) -> bool:
    """Return whether *path* is inside the reserved fail-closed namespace."""

    candidate = Path(path)
    return candidate == UNCONFIGURED_RUNTIME_ROOT or (
        UNCONFIGURED_RUNTIME_ROOT in candidate.parents
    )


__all__ = [
    "UNCONFIGURED_RUNTIME_ROOT",
    "is_unconfigured_runtime_path",
    "unconfigured_runtime_path",
]
