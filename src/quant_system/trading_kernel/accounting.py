"""Pure accounting math shared by the backtest and paper portfolios/account.

Two helpers capture arithmetic that was previously duplicated:

- :func:`apply_fill_to_portfolio` is the identical cash/position update used by
  :class:`~quant_system.backtest.portfolio.Portfolio` and
  :class:`~quant_system.execution.portfolio.PaperPortfolio` (simple net share
  count, ``< 1e-10`` dust pop).
- :func:`roll_position_on_fill` is the average-cost / realized-P&L roll used by
  :class:`~quant_system.execution.account.PaperAccount.apply_fill`. It returns
  the numeric deltas only; the account keeps its own ledger / source-quantity /
  realized-P&L side effects around this call.

This module is PURE: standard library plus the neutral kernel models only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_system.trading_kernel.models import Side

# Dust threshold below which a portfolio position is dropped, matching the
# historical ``Portfolio`` / ``PaperPortfolio`` behavior exactly.
_POSITION_DUST = 1e-10


def _is_buy(side: Any) -> bool:
    """True when ``side`` is a BUY, regardless of which OrderSide enum it is.

    The backtest and execution ``OrderSide`` enums and the kernel :class:`Side`
    are all ``StrEnum`` valued ``"buy"`` / ``"sell"``, so comparing by value
    keeps this helper decoupled from any concrete enum module.
    """

    return str(getattr(side, "value", side)) == Side.BUY.value


def apply_fill_to_portfolio(
    positions: Mapping[str, float],
    cash: float,
    fill: Any,
) -> tuple[dict[str, float], float]:
    """Apply a fill to a simple ``{symbol: quantity}`` portfolio.

    Returns a fresh ``(positions, cash)`` pair; the input mapping is not
    mutated. ``fill`` must expose ``symbol``, ``side``, ``quantity``,
    ``gross_value`` and ``commission`` (both :class:`Fill` and
    :class:`ExecutionFill` satisfy this). BUYs debit ``gross_value +
    commission`` and add shares; SELLs credit ``gross_value - commission`` and
    remove shares. A resulting near-zero position (``< 1e-10``) is dropped.
    """

    updated: dict[str, float] = {
        symbol.upper(): float(quantity) for symbol, quantity in positions.items()
    }
    symbol = fill.symbol.upper()
    current = updated.get(symbol, 0.0)
    if _is_buy(fill.side):
        cash = cash - (fill.gross_value + fill.commission)
        updated[symbol] = current + fill.quantity
    else:
        cash = cash + (fill.gross_value - fill.commission)
        updated[symbol] = current - fill.quantity

    if abs(updated.get(symbol, 0.0)) < _POSITION_DUST:
        updated.pop(symbol, None)
    return updated, cash


def roll_position_on_fill(
    *,
    side: Any,
    position_quantity: float,
    position_avg_cost: float,
    fill_quantity: float,
    fill_price: float,
    gross_value: float,
    commission: float,
) -> tuple[float, float, float, float]:
    """Roll one position's quantity / average cost on a fill.

    Returns ``(new_quantity, new_avg_cost, realized_pnl_delta, cash_delta)``.

    BUYs add to the position and roll the average cost with commission folded
    into the basis (``realized_pnl_delta`` is ``0``). SELLs realise P&L against
    ``position_avg_cost`` (net of commission) and leave the basis of the
    remaining shares unchanged. This is the exact arithmetic previously inlined
    in :meth:`PaperAccount.apply_fill`.
    """

    if _is_buy(side):
        total_basis = position_quantity * position_avg_cost
        total_basis += gross_value + commission
        new_quantity = position_quantity + fill_quantity
        new_avg_cost = total_basis / new_quantity if new_quantity > 0 else 0.0
        cash_delta = -(gross_value + commission)
        return new_quantity, new_avg_cost, 0.0, cash_delta

    realized_delta = fill_quantity * (fill_price - position_avg_cost)
    realized_delta -= commission
    new_quantity = position_quantity - fill_quantity
    cash_delta = gross_value - commission
    # Average cost of the remaining shares is unchanged on a sell.
    return new_quantity, position_avg_cost, realized_delta, cash_delta
