"""Read-only paper state for the UI; saved enablement is not execution health.

The strict config loader owns current implementation compatibility. Existing
committed-journal validation owns fill evidence. No provider, recovery, signal,
valuation or account mutation is invoked by this projection.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from quant_system.d34.hung_sleeve_effect import _committed_states


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        for item in exc.errors(include_url=False, include_input=False):
            error = item.get("ctx", {}).get("error")
            if error is not None and str(error).startswith("strategy_"):
                return str(error)
        return "strategy_config_invalid"
    if isinstance(exc, FileNotFoundError):
        return "strategy_config_missing"
    return str(exc) if str(exc).startswith("strategy_") else "strategy_config_unavailable"


def read_paper_runtime_status(storage, sleeve) -> dict:
    """Project one bound sleeve without changing persisted status or evidence."""
    result = {
        "checked_at": datetime.now(UTC).isoformat(),
        "sleeve_id": sleeve.sleeve_id,
        "config_id": sleeve.strategy_config_id,
        "config_version": sleeve.strategy_config_version,
        "enabled": str(sleeve.status) == "running",
        "configuration": {"status": "compatible", "reason": None},
        "signal": {"status": "not_generated", "reason": "no_saved_signal"},
        "fills": {"status": "unavailable", "count": None, "days": None},
        "valuation": {
            "status": "not_checked",
            "reason": "saved_paper_review_required",
        },
    }
    definition_digest = None
    try:
        config = storage.load_strategy_config(
            sleeve.strategy_config_id, version=sleeve.strategy_config_version
        )
        if (config.strategy_config_id != sleeve.strategy_config_id
                or config.version != sleeve.strategy_config_version):
            raise ValueError("strategy_config_binding_mismatch")
        if config.strategy_definition is not None:
            definition_digest = config.strategy_definition["content_digest"]
            if sleeve.metadata.get("definition_digest") != definition_digest:
                raise ValueError("strategy_definition_execution_binding_mismatch")
        elif sleeve.metadata.get("definition_digest"):
            raise ValueError("strategy_definition_execution_binding_mismatch")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["configuration"] = {"status": "blocked", "reason": _reason(exc)}
    # `enabled` is the persisted lifecycle flag only; consumers deciding whether the
    # sleeve can actually produce signals must use execution_ready instead.
    result["execution_ready"] = (
        str(sleeve.status) == "running"
        and result["configuration"]["status"] != "blocked"
    )

    try:
        signals = [signal for signal in storage.load_signals(sleeve.sleeve_id)
                   if signal.sleeve_id == sleeve.sleeve_id
                   and signal.strategy_config_id == sleeve.strategy_config_id
                   and signal.strategy_config_version == sleeve.strategy_config_version]
        latest = max(signals, key=lambda signal: signal.generated_at, default=None)
        if latest:
            result["signal"] = {
                "status": str(latest.status),
                "reason": latest.execution_blocked_reason,
                "signal_id": latest.signal_id,
                "signal_date": latest.signal_date,
                "generated_at": latest.generated_at,
                "target_count": len(latest.target_weights),
                "order_count": len(latest.proposed_orders),
            }
            if (definition_digest is not None
                    and latest.metadata.get("definition_digest") != definition_digest):
                result["signal"].update(
                    status="blocked", reason="strategy_definition_signal_binding_mismatch",
                )
    except (OSError, ValueError, KeyError, TypeError):
        result["signal"] = {"status": "unavailable", "reason": "saved_signal_unavailable"}
    if result["configuration"]["status"] == "blocked":
        # Old generated signals do not certify the current implementation.
        result["signal"] = {
            **result["signal"], "status": "blocked",
            "reason": result["configuration"]["reason"],
        }
    try:
        states = _committed_states(sleeve_storage=storage, sleeves=[sleeve])
        observations = [state for state in states if state["is_observation"]]
        result["fills"] = {
            "status": "verified", "reason": None,
            "count": sum(len(state["fills"]) for state in observations),
            "days": len({state["date"] for state in observations}),
            "last_fill_date": max((state["date"] for state in observations), default=None),
            "scope": "cumulative_sleeve_history",
        }
        if not observations:
            result["valuation"] = {"status": "cash_only", "reason": "no_committed_fills"}
    except (OSError, ValueError, KeyError, TypeError):
        result["fills"]["reason"] = "committed_effect_state_unavailable"
    return result
