"""Pure, shared trading kernel.

A provider-, broker-, and storage-free rules layer that the backtest and
paper-trading code paths share so their order-generation and accounting rules
cannot drift apart. Nothing in this package may import a data provider, Futu,
a broker, storage, or any other I/O module — arithmetic only.
"""

from __future__ import annotations

from quant_system.trading_kernel.accounting import (
    apply_fill_to_portfolio,
    roll_position_on_fill,
)
from quant_system.trading_kernel.models import OrderIntent, Side
from quant_system.trading_kernel.weights import plan_rebalance

__all__ = [
    "OrderIntent",
    "Side",
    "apply_fill_to_portfolio",
    "plan_rebalance",
    "roll_position_on_fill",
]
