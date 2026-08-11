"""Load one digest-bound D-34 factor into a paper-only registry.

The generated module is deliberately absent from ``build_factor_registry``.
Resident live callers therefore have no code path that can discover it; only
the D-34 paper sleeve resolves exact Artifact Registry bytes through this
loader.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from types import ModuleType

from quant_system.factors.base import BaseFactor
from quant_system.factors.registry import FactorRegistry

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_FACTOR_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")


def load_d34_paper_factor_registry(
    *,
    code_path: str | Path,
    expected_code_digest: str,
    expected_factor_id: str,
) -> FactorRegistry:
    if (
        _DIGEST_RE.fullmatch(expected_code_digest) is None
        or _FACTOR_ID_RE.fullmatch(expected_factor_id) is None
    ):
        raise ValueError("d34_artifact_factor_identity_invalid")
    path = Path(code_path).expanduser()
    if not path.is_file():
        raise ValueError("d34_artifact_code_unavailable")
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise ValueError("d34_artifact_code_unavailable") from exc
    if hashlib.sha256(source).hexdigest() != expected_code_digest:
        raise ValueError("d34_artifact_code_digest_mismatch")

    module = ModuleType(f"quant_system_d34_artifact_{expected_code_digest[:16]}")
    module.__file__ = str(path)
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102
    except Exception as exc:  # noqa: BLE001 - generated artifact boundary
        raise ValueError("d34_artifact_code_import_failed") from exc
    factor_class = getattr(module, "D34_FACTOR", None)
    if (
        not isinstance(factor_class, type)
        or not issubclass(factor_class, BaseFactor)
        or factor_class is BaseFactor
    ):
        raise ValueError("d34_artifact_factor_contract_invalid")
    try:
        factor = factor_class()
    except Exception as exc:  # noqa: BLE001 - generated artifact boundary
        raise ValueError("d34_artifact_factor_contract_invalid") from exc
    if factor.factor_id != expected_factor_id:
        raise ValueError("d34_artifact_factor_id_mismatch")

    registry = FactorRegistry()
    registry.register(factor_class, origin="d34_artifact")
    return registry


__all__ = ["load_d34_paper_factor_registry"]
