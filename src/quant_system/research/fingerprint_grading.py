"""Conservative drift diagnostics and frozen identity reads for replacement.

A historical recipe may be authenticated without being executable today. Only
replacement inspection may use frozen_definition_identity; new definitions,
signals, decisions and executions still use validate_definition. File categories
are diagnostics, never deterministic proof that changed code is equivalent.
"""

from __future__ import annotations

from typing import Any, Literal

from quant_system.research.strategy_definition import (
    StrategyDefinition,
    current_source_fingerprints,
)

FINGERPRINT_GRADING_ENABLED = False
ObservationMode = Literal["fail_closed", "advisory"]

_ALGORITHM_SOURCES = frozenset(
    {
        "research/strategy_definition.py",
        "backtest/engine.py",
        "backtest/models.py",
        "backtest/broker.py",
        "backtest/order_generation.py",
        "backtest/portfolio.py",
        "backtest/metrics.py",
        "trading_kernel/__init__.py",
        "trading_kernel/accounting.py",
        "trading_kernel/weights.py",
        "trading_kernel/models.py",
        "d34/qlib_expr.py",
    }
)
# These files also calculate quantities, fees, prices or decisions. None is
# observation-only; whole-file advisory would silently authorize new behavior.
_OBSERVATION_SOURCES: frozenset[str] = frozenset()
_DUAL_ROLE_SOURCES = frozenset({
    "research/definition_paper.py",
    "execution/definition_open_prices.py",
    "execution/paper_strategy_signal_service.py",
    "execution/paper_strategy_execution_service.py",
    "research/strategy_runtime.py",
    "research/reference_backtests.py",
})


def frozen_definition_identity(definition: StrategyDefinition | dict) -> StrategyDefinition:
    """Read an existing sealed recipe; this grants no current execution authority.

    Preserve the original digest and every fingerprint. Nested factor/formula/
    profile validation remains strict: an unsupported historic factor/compiler
    requires its archived implementation, not automatic reinterpretation.
    """
    raw = (
        definition.model_dump(mode="json")
        if isinstance(definition, StrategyDefinition) else definition
    )
    if (not isinstance(raw, dict) or not raw.get("content_digest")
            or not raw.get("source_fingerprints")):
        raise ValueError("strategy_definition_binding_required")
    value = StrategyDefinition.model_validate(raw)
    if value.whole_share_orders:
        raise ValueError("strategy_whole_share_paper_unsupported")
    return value


def classify_source(path: str) -> str:
    """Grade a fingerprint key as ``algorithm`` / ``observation`` / ``dual_role``.

    The default is ``algorithm`` (fail-closed): anything not explicitly known to
    be observation-only — including factor identities and the
    ``dependency:exchange_calendars`` pseudo-entry — is treated as algorithm.
    """
    key = str(path).strip()
    if key in _OBSERVATION_SOURCES:
        return "observation"
    if key in _DUAL_ROLE_SOURCES:
        return "dual_role"
    if key in _ALGORITHM_SOURCES:
        return "algorithm"
    return "algorithm"


def current_source_fingerprints_v2(
    definition: StrategyDefinition, *, graded: bool = False
) -> dict[str, Any]:
    """Split the v1 fingerprint set into algorithm/observation buckets.

    ``graded=False`` keeps every entry in ``algorithm`` (v1-equivalent lumping);
    ``graded=True`` moves the observation-only files into their own bucket and
    lists them under ``advisory``.
    """
    current = current_source_fingerprints(definition)
    algorithm: dict[str, str] = {}
    observation: dict[str, str] = {}
    for path, digest in current.items():
        if graded and classify_source(path) == "observation":
            observation[path] = digest
        else:
            algorithm[path] = digest
    return {
        "algorithm": algorithm,
        "observation": observation,
        "advisory": sorted(observation) if graded else [],
    }


def validate_definition_v2(
    definition: StrategyDefinition | dict, *, observation_mode: ObservationMode = "fail_closed"
) -> dict[str, Any]:
    """Grade drift; ``fail_closed`` (default) is byte-for-byte the v1 behaviour."""
    if observation_mode not in ("fail_closed", "advisory"):
        raise ValueError("fingerprint_grading_mode_invalid")
    raw = (
        definition.model_dump(mode="json")
        if isinstance(definition, StrategyDefinition)
        else definition
    )
    value = StrategyDefinition.model_validate(raw)
    current = current_source_fingerprints(value)
    if value.source_fingerprints == current:
        return {"definition": value, "status": "ok", "advisory": [], "drifted": {}}
    drifted: dict[str, Any] = {}
    for path, digest in current.items():
        if value.source_fingerprints.get(path) != digest:
            drifted[path] = {"stored": value.source_fingerprints.get(path), "current": digest}
    for path, digest in value.source_fingerprints.items():
        if path not in current:
            drifted[path] = {"stored": digest, "current": None}
    algorithm = [path for path in drifted if classify_source(path) != "observation"]
    observation = [path for path in drifted if classify_source(path) == "observation"]
    if observation_mode == "fail_closed" or algorithm or not FINGERPRINT_GRADING_ENABLED:
        raise ValueError("strategy_algorithm_source_mismatch")
    return {
        "definition": value,
        "status": "observation_drift_advisory",
        "advisory": [
            {"path": path, "reason": "strategy_observation_source_drift"} for path in observation
        ],
        "drifted": drifted,
    }
