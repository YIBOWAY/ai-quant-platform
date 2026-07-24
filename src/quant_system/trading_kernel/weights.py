"""Pure rebalancing rules shared by the backtest and paper-trading paths.

:func:`plan_rebalance` is the single source of truth for turning *target
weights* into *order legs*. It is the superset of the three historical
implementations (backtest order generation, signal-replay request building,
and persistent-account rebalancing): it carries weight caps, whole-share
flooring, the double min-order-value gate, and an optional sells-before-buys
ordering. Each former call site becomes a thin adapter that selects the
relevant knobs and maps :class:`OrderIntent` onto its own order model.

This module is PURE: it imports only the standard library and the neutral
kernel models. It must never import a provider, broker, storage, Futu, or any
other I/O module.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from math import isfinite

from quant_system.trading_kernel.models import OrderIntent, Side


def plan_rebalance(
    *,
    holdings: Mapping[str, float],
    target_weights: Mapping[str, float],
    prices: Mapping[str, float],
    equity: float,
    min_order_value: float = 0.0,
    whole_share: bool = False,
    max_weight_per_symbol: float | None = None,
    sector_cap: float | None = None,
    sector_map: Mapping[str, str] | None = None,
    sells_first: bool = False,
    min_quantity: float = 0.0,
) -> list[OrderIntent]:
    """Plan rebalance order legs from current holdings and target weights.

    Parameters mirror the union of the previous three implementations:

    - ``holdings`` / ``target_weights`` keyed by symbol (case-insensitive).
    - ``prices`` is the order-generation mark per symbol; ``equity`` is the
      current portfolio equity used to size targets.
    - ``min_order_value`` gates a leg twice: once on the raw notional delta and
      again on the (possibly whole-share-floored) notional, matching the
      backtest superset.
    - ``whole_share`` floors each quantity with :func:`math.floor`.
    - ``max_weight_per_symbol`` / ``sector_cap`` / ``sector_map`` clamp target
      weights down before sizing (no redistribution); both caps unset is a
      no-op so the default order stream is unchanged.
    - ``sells_first`` re-orders the emitted legs so every SELL precedes every
      BUY (the execution paths free cash before spending it). The default
      (``False``) preserves the backtest's sorted-union emission order.
    - ``min_quantity`` is the dust floor: a leg is dropped when its quantity is
      ``<= min_quantity``. ``0.0`` reproduces the backtest's ``<= 0`` skip;
      ``1e-9`` reproduces the persistent account's dust floor.

    Symbols are always considered in deterministic
    ``sorted(set(holdings) | set(target_weights))`` order. Every such symbol
    must have a finite, strictly-positive price or the whole plan is rejected
    with ``ValueError`` (the unified strict rule). The 1-based position of each
    symbol in that sorted order is recorded on :attr:`OrderIntent.symbol_index`
    so adapters can reproduce position-dependent order ids.
    """

    normalized_prices = {
        symbol.upper(): float(price) for symbol, price in prices.items()
    }
    target_map = {
        symbol.upper(): float(weight) for symbol, weight in target_weights.items()
    }
    target_map = _apply_weight_constraints(
        target_map,
        max_weight_per_symbol=max_weight_per_symbol,
        sector_cap=sector_cap,
        sector_map=sector_map,
    )
    normalized_holdings = {
        symbol.upper(): float(quantity) for symbol, quantity in holdings.items()
    }
    symbols = sorted(set(normalized_holdings) | set(target_map))

    missing_prices = [
        symbol
        for symbol in symbols
        if symbol not in normalized_prices
        or normalized_prices[symbol] <= 0
        or not isfinite(normalized_prices[symbol])
    ]
    if missing_prices:
        raise ValueError(
            "missing order generation price for " + ", ".join(missing_prices)
        )

    intents: list[OrderIntent] = []
    for index, symbol in enumerate(symbols, start=1):
        price = normalized_prices[symbol]
        current_quantity = normalized_holdings.get(symbol, 0.0)
        current_value = current_quantity * price
        target_value = target_map.get(symbol, 0.0) * equity
        value_delta = target_value - current_value
        if abs(value_delta) < min_order_value:
            continue
        side = Side.BUY if value_delta > 0 else Side.SELL
        quantity = abs(value_delta) / price
        if whole_share:
            quantity = math.floor(quantity)
        if quantity * price < min_order_value:
            continue
        if quantity <= min_quantity:
            continue
        intents.append(
            OrderIntent(
                symbol=symbol,
                side=side,
                quantity=quantity,
                symbol_index=index,
                price=price,
                reason="rebalance_to_target_weight",
            )
        )

    if sells_first:
        # Stable resort: sells before buys, preserving relative order otherwise.
        intents.sort(key=lambda intent: 0 if intent.side == Side.SELL else 1)
    return intents


def _apply_weight_constraints(
    target_map: dict[str, float],
    *,
    max_weight_per_symbol: float | None,
    sector_cap: float | None,
    sector_map: Mapping[str, str] | None,
) -> dict[str, float]:
    """Clamp target weights to the configured caps.

    No-op when both ``max_weight_per_symbol`` and ``sector_cap`` are unset, so
    the default order stream is unchanged. Caps only ever scale weights
    *down*; freed weight is not redistributed, keeping gross exposure
    predictable (v1 semantics).
    """

    if max_weight_per_symbol is None and sector_cap is None:
        return target_map

    capped = dict(target_map)
    if max_weight_per_symbol is not None:
        capped = {
            symbol: min(weight, max_weight_per_symbol)
            for symbol, weight in capped.items()
        }

    if sector_cap is not None:
        resolved_sector_map: Mapping[str, str] = sector_map or {}
        sector_totals: dict[str, float] = {}
        for symbol, weight in capped.items():
            sector = resolved_sector_map.get(symbol, symbol)
            sector_totals[sector] = sector_totals.get(sector, 0.0) + weight
        for sector, total in sector_totals.items():
            if total > sector_cap and total > 0:
                scale = sector_cap / total
                for symbol in capped:
                    if resolved_sector_map.get(symbol, symbol) == sector:
                        capped[symbol] *= scale
    return capped
