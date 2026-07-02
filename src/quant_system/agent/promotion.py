"""First consumer of the SafetyGate: load human-approved candidate factors.

The gate stays observation-only -- this module NEVER creates approval locks;
it only loads factor sources for candidates a human has already approved via
``quant-system agent review --decision approve``.
"""

from __future__ import annotations

from pathlib import Path

from quant_system.agent.safety import SafetyGate
from quant_system.factors.base import BaseFactor
from quant_system.factors.registry import FactorRegistry

_FORBIDDEN_SNIPPETS = (
    "import socket",
    "import subprocess",
    "import urllib",
    "import requests",
    "import http",
    "import os",
    "from socket",
    "from subprocess",
    "from urllib",
    "from requests",
    "from http",
    "from os",
)


class CandidateLoadError(RuntimeError):
    """A candidate factor source failed the static safety check."""


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
        lowered = source.lower()
        for snippet in _FORBIDDEN_SNIPPETS:
            if snippet in lowered:
                raise CandidateLoadError(
                    f"candidate {candidate_dir.name!r} contains forbidden code: {snippet!r}"
                )
        namespace: dict[str, object] = {}
        # Human-approved candidate (approved.lock verified above); static check passed.
        exec(compile(source, str(source_path), "exec"), namespace)  # noqa: S102
        for value in namespace.values():
            if isinstance(value, type) and issubclass(value, BaseFactor) and value is not BaseFactor:
                try:
                    registry.register(value)
                except ValueError:
                    continue  # already registered -- idempotent reload
                loaded.append(value.factor_id)
    return loaded
