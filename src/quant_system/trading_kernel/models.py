"""Neutral value objects for the shared, pure trading kernel.

These types intentionally know nothing about pydantic models, brokers,
providers, or storage. Call-site adapters map between these neutral objects
and the existing :class:`~quant_system.backtest.models.Order` /
:class:`~quant_system.execution.models.OrderRequest` models.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Side(StrEnum):
    """Order side, value-compatible with both existing ``OrderSide`` enums.

    ``backtest.models.OrderSide`` and ``execution.models.OrderSide`` are both
    ``StrEnum`` with the values ``"buy"`` / ``"sell"``. Adapters convert by
    value (``OtherSide(side.value)``), so this neutral enum stays decoupled
    from either concrete model module.
    """

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class OrderIntent:
    """A single rebalance leg produced by :func:`plan_rebalance`.

    ``symbol_index`` is the 1-based position of ``symbol`` in the deterministic
    ``sorted(set(holdings) | set(target_weights))`` symbol order, counting every
    candidate symbol (including those that produced no order). The backtest
    adapter uses it to reproduce its ``"%Y%m%d-%04d"`` order ids byte-for-byte.
    ``price`` carries the order-generation mark price for adapters that attach a
    limit price; it is ``None`` when no price context is propagated.
    """

    symbol: str
    side: Side
    quantity: float
    symbol_index: int
    price: float | None = None
    reason: str = ""
