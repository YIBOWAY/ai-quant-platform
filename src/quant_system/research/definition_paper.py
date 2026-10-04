"""Strict strategy-definition adapters for existing paper sleeves; no I/O writes."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from quant_system.research.strategy_definition import StrategyDefinition, validate_definition
from quant_system.trading_kernel import plan_rebalance


def definition_schedule_available() -> bool:
    from quant_system.d34 import paper_cycle

    return getattr(paper_cycle, "DEFINITION_REBALANCE_SUPPORTED", False) is True


def paper_definition(value: StrategyDefinition | dict) -> StrategyDefinition:
    raw = value.model_dump(mode="json") if isinstance(value, StrategyDefinition) else value
    if (
        not isinstance(raw, dict)
        or not raw.get("content_digest")
        or not raw.get("source_fingerprints")
    ):
        raise ValueError("strategy_definition_binding_required")
    definition = validate_definition(raw)
    if definition.whole_share_orders:
        raise ValueError("strategy_whole_share_paper_unsupported")
    return definition


def load_candidate_definition(
    path: Path,
    *,
    factor_id: str,
    universe: Sequence[str],
    expected_digest: str | None = None,
) -> StrategyDefinition:
    definition = paper_definition(json.loads(path.read_text(encoding="utf-8")))
    if factor_id != "definition_" + definition.content_digest[:24]:
        raise ValueError("strategy_definition_factor_identity_mismatch")
    if list(universe) != list(definition.symbols):
        raise ValueError("strategy_definition_universe_mismatch")
    if expected_digest is not None and definition.content_digest != expected_digest:
        raise ValueError("strategy_definition_digest_mismatch")
    return definition


def definition_config_fields(definition: StrategyDefinition) -> dict[str, Any]:
    """Keep the inspectable config columns consistent with the immutable recipe."""
    identifier = "definition_" + definition.content_digest[:24]
    factor_ids = [item.factor_id for item in definition.factors] or [identifier]
    weights = {item.factor_id: item.weight for item in definition.factors} or {identifier: 1.0}
    lookback = max((item.lookback for item in definition.factors), default=252)
    if definition.formula is not None:
        lookback = max(1, definition.formula.eligibility_window)
    return {
        "strategy_id": "strategy_definition",
        "symbols": list(definition.symbols),
        "factor_ids": factor_ids,
        "weights": weights,
        "lookback": lookback,
        "top_n": definition.top_n,
        "rebalance_frequency": definition.rebalance,
        "max_weight_per_symbol": definition.max_weight_per_symbol,
        "min_order_value": definition.min_order_value,
        "data_provider": definition.provider,
        "execution_timing": definition.execution_price,
        "strategy_definition": definition.model_dump(mode="json"),
    }


def require_paper_costs(definition: StrategyDefinition, settings: Any) -> None:
    costs = settings.paper_account
    if (
        costs.commission_bps != definition.commission_bps
        or costs.slippage_bps != definition.slippage_bps
    ):
        raise ValueError("strategy_definition_execution_cost_mismatch")


def definition_orders(
    *,
    definition: StrategyDefinition,
    holdings: Mapping[str, float],
    cash: float,
    targets: Mapping[str, float] | None,
    prices: Mapping[str, float],
    account_id: str,
) -> list[dict[str, Any]]:
    if targets is None:
        return []
    equity = cash + sum(quantity * prices[symbol] for symbol, quantity in holdings.items())
    intents = plan_rebalance(
        holdings=holdings,
        target_weights=targets,
        prices=prices,
        equity=equity,
        min_order_value=definition.min_order_value,
        max_weight_per_symbol=definition.max_weight_per_symbol,
        sells_first=True,
    )
    slip = definition.slippage_bps / 10_000
    commission = definition.commission_bps / 10_000
    available = cash
    orders = []
    for intent in intents:
        side = intent.side.value
        quantity = intent.quantity
        if side == "sell":
            quantity = min(quantity, holdings.get(intent.symbol, 0.0))
            available += quantity * intent.price * (1 - slip) * (1 - commission)
        else:
            # Match the backtest broker's cash affordability at the reference
            # mark. The actual next-open execution still owns price/policy checks.
            affordable = max(0.0, available) / (intent.price * (1 + slip) * (1 + commission))
            quantity = min(quantity, affordable)
            available -= quantity * intent.price * (1 + slip) * (1 + commission)
        if quantity <= 1e-9:
            continue
        current_value = holdings.get(intent.symbol, 0.0) * intent.price
        orders.append(
            {
                "symbol": intent.symbol,
                "side": side,
                "target_weight": float(targets.get(intent.symbol, 0.0)),
                "current_value": current_value,
                "target_value": equity * float(targets.get(intent.symbol, 0.0)),
                "notional_delta": quantity * intent.price * (1 if side == "buy" else -1),
                "reference_price": intent.price,
                "estimated_quantity": quantity,
                "reason": "advisory_only_no_execution",
                "account_id": account_id,
            }
        )
    return orders
