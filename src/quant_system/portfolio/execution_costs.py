"""Read-only scenario cost checks on net orders; never create fills or NAV.

The capacity quantity is a budget based on a known prior session's raw volume,
not proof that the quantity can fill at the next open. Inputs and scenario fees
must be frozen separately before a historical run; no broker tariff is implied.
"""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from quant_system.backtest.models import BacktestConfig, Order, TargetWeight
from quant_system.backtest.order_generation import OrderGenerator
from quant_system.backtest.portfolio import Portfolio
from quant_system.portfolio.combiner import _digest, _time


class _FrozenInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, strict=True)


class CostTier(_FrozenInput):
    minimum_daily_turnover_usd: float = Field(ge=0)
    commission_bps: float = Field(ge=0)
    minimum_fee_usd: float = Field(ge=0)
    slippage_bps: float = Field(ge=0, lt=10_000)


class ExecutionCostScenario(_FrozenInput):
    scenario_id: str = Field(min_length=1)
    interpretation: Literal["assumption_sensitivity_not_broker_tariff"]
    tiers: tuple[CostTier, ...] = Field(strict=False)
    max_prior_volume_participation: float = Field(gt=0, le=1)
    max_liquidity_age_hours: float = Field(gt=0)

    @model_validator(mode="after")
    def valid_tiers(self):
        floors = [tier.minimum_daily_turnover_usd for tier in self.tiers]
        if not floors or floors[0] != 0 or floors != sorted(set(floors)):
            raise ValueError("cost_tiers_require_zero_floor_and_strict_ascending_order")
        return self


class _PriceInput(_FrozenInput):
    price: float = Field(gt=0)
    currency: Literal["USD"]
    price_basis: Literal["unadjusted"]
    as_of: str
    available_at: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class _LiquidityInput(_FrozenInput):
    raw_volume_shares: float = Field(gt=0)
    raw_turnover_usd: float = Field(gt=0)
    raw_low: float = Field(gt=0)
    raw_high: float = Field(gt=0)
    currency: Literal["USD"]
    volume_unit: Literal["shares"]
    price_basis: Literal["unadjusted"]
    as_of: str
    available_at: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def _price(value, execution):
    price = _PriceInput.model_validate(value)
    as_of, available = _time(price.as_of), _time(price.available_at)
    if not (as_of == execution and as_of <= available <= execution):
        raise ValueError("execution_price_time_mismatch")
    return price


def _liquidity(value, cutoff, scenario):
    liquidity = _LiquidityInput.model_validate(value)
    as_of, available = _time(liquidity.as_of), _time(liquidity.available_at)
    if not (as_of <= available <= cutoff):
        raise ValueError("liquidity_not_known_at_decision")
    if cutoff - as_of > pd.Timedelta(hours=scenario.max_liquidity_age_hours):
        raise ValueError("liquidity_stale")
    average_price = liquidity.raw_turnover_usd / liquidity.raw_volume_shares
    if not (liquidity.raw_low <= average_price <= liquidity.raw_high):
        raise ValueError("liquidity_turnover_volume_units_inconsistent")
    return liquidity


def _envelope(scenario):
    contract = scenario.model_dump(mode="json")
    return {
        "schema": "portfolio_execution_cost_preflight/v1",
        "scenario": contract,
        "scenario_digest": _digest(contract),
        "research_only": True,
        "admission_authority": False,
        "funding_authority": False,
        "fills_created": False,
        "nav_computed": False,
        "cash_and_inventory_feasibility": "not_evaluated",
        "input_provenance_verified": False,
        "capacity_basis": "prior_completed_session_raw_volume_budget_not_open_fill_capacity",
        "impact_model": "not_evaluated",
    }


def preflight_orders(
    orders: list[Order],
    *,
    scenario: ExecutionCostScenario,
    prices: dict,
    liquidity: dict,
    decision_at,
    execute_at,
) -> dict:
    """Quote each already-netted order once; missing evidence stays unevaluated.

    Report fees for the full requested quantity. Budget-limited quantity is a
    separate diagnostic, never a partial fill or a new order. Duplicate symbols
    are refused to prevent charging component orders or reusing a volume budget.
    """
    cutoff, execution = _time(decision_at), _time(execute_at)
    if execution <= cutoff:
        raise ValueError("cost_execution_not_after_decision")
    symbols = [order.symbol.upper() for order in orders]
    if len(set(symbols)) != len(symbols):
        raise ValueError("cost_orders_must_be_netted_once_per_symbol")
    rows = []
    for order in orders:
        row = {"order": order.model_dump(mode="json")}
        try:
            if (
                _time(order.timestamp) != execution
                or not math.isfinite(order.quantity)
                or order.symbol != order.symbol.upper()
            ):
                raise ValueError("cost_order_time_or_quantity_invalid")
            price = _price(prices.get(order.symbol), execution)
            volume = _liquidity(liquidity.get(order.symbol), cutoff, scenario)
            tier = next(
                tier
                for tier in reversed(scenario.tiers)
                if volume.raw_turnover_usd >= tier.minimum_daily_turnover_usd
            )
            sign = 1 if order.side == "buy" else -1
            estimated_price = price.price * (1 + sign * tier.slippage_bps / 10_000)
            gross = order.quantity * estimated_price
            fee = max(tier.minimum_fee_usd, gross * tier.commission_bps / 10_000)
            limit = volume.raw_volume_shares * scenario.max_prior_volume_participation
            if not all(
                math.isfinite(value)
                for value in (estimated_price, gross, fee, limit, gross + fee, gross - fee)
            ):
                raise ValueError("cost_quote_nonfinite")
            rows.append(
                {
                    **row,
                    "status": "evaluated",
                    "selected_tier": tier.model_dump(),
                    "estimated_execution_price": estimated_price,
                    "requested_gross_usd": gross,
                    "requested_commission_usd": fee,
                    "requested_cash_debit_usd": gross + fee if sign == 1 else None,
                    "requested_sale_proceeds_usd": gross - fee if sign == -1 else None,
                    "capacity_budget_shares": limit,
                    "within_capacity_budget": order.quantity <= limit,
                    "budget_limited_quantity": min(order.quantity, limit),
                    "over_budget_quantity": max(order.quantity - limit, 0.0),
                    "price_input": price.model_dump(),
                    "liquidity_input": volume.model_dump(),
                }
            )
        except (ValueError, TypeError) as exc:
            # Structured validation errors are retained; no default volume,
            # currency, price adjustment, zero fee or successful fill is invented.
            rows.append({**row, "status": "not_evaluated", "reason": str(exc)})
    complete = all(row["status"] == "evaluated" for row in rows)
    total, reason = None, None
    if complete:
        try:
            total = math.fsum(row["requested_commission_usd"] for row in rows)
        except OverflowError:
            complete, reason = False, "cost_commission_total_nonfinite"
    return {
        **_envelope(scenario),
        "status": "evaluated" if complete else "not_evaluated",
        "decision_at": cutoff.isoformat(),
        "execute_at": execution.isoformat(),
        "order_count": len(orders),
        "orders": rows,
        "requested_commission_total_usd": total,
        "reason": reason,
        "all_within_capacity_budget": (
            all(row["within_capacity_budget"] for row in rows) if complete else None
        ),
    }


def preflight_combined_targets(
    combined: dict,
    *,
    portfolio: Portfolio,
    config: BacktestConfig,
    scenario: ExecutionCostScenario,
    prices: dict,
    liquidity: dict,
) -> dict:
    """Connect the combiner's sealed net target to the existing OrderGenerator.

    Reads the supplied portfolio snapshot. Does not instantiate a broker, apply
    fills, modify the supplied portfolio, or change the legacy cost configuration.
    """
    if combined.get("schema") != "portfolio_combined_target/v1" or combined.get(
        "target_digest"
    ) != _digest({key: value for key, value in combined.items() if key != "target_digest"}):
        raise ValueError("cost_combined_target_identity_changed")
    execution = _time(combined["execute_at"])
    required = set(combined["symbol_weights"]) | set(portfolio.positions)
    try:
        checked = {symbol: _price(prices.get(symbol), execution).price for symbol in required}
    except (ValueError, TypeError) as exc:
        return {
            **_envelope(scenario),
            "status": "not_evaluated",
            "target_digest": combined["target_digest"],
            "reason": str(exc),
            "order_count": None,
            "orders": [],
            "requested_commission_total_usd": None,
            "all_within_capacity_budget": None,
        }
    targets = [
        TargetWeight(timestamp=execution, symbol=symbol, target_weight=weight)
        for symbol, weight in combined["symbol_weights"].items()
    ]
    orders = OrderGenerator(config).generate_orders(
        timestamp=execution,
        targets=targets,
        portfolio=portfolio,
        prices=checked,
    )
    result = preflight_orders(
        orders,
        scenario=scenario,
        prices=prices,
        liquidity=liquidity,
        decision_at=combined["decision_at"],
        execute_at=execution,
    )
    return {
        **result,
        "target_digest": combined["target_digest"],
        "order_generation_config": config.model_dump(mode="json"),
        "portfolio_snapshot": {"cash": portfolio.cash, "positions": dict(portfolio.positions)},
    }
