from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from quant_system.execution.models import ExecutionFill, ManagedOrder, OrderSide, OrderStatus
from quant_system.execution.portfolio import PaperPortfolio


class PaperBroker:
    """Paper broker that shares the future broker adapter interface."""

    def __init__(
        self,
        *,
        portfolio: PaperPortfolio,
        max_fill_ratio_per_tick: float = 1.0,
        commission_bps: float = 0.0,
        slippage_bps: float = 0.0,
    ) -> None:
        if max_fill_ratio_per_tick < 0:
            raise ValueError("max_fill_ratio_per_tick must be non-negative")
        self.portfolio = portfolio
        self.max_fill_ratio_per_tick = max_fill_ratio_per_tick
        self.commission_bps = commission_bps
        self.slippage_bps = slippage_bps
        self.open_orders: dict[str, ManagedOrder] = {}
        self.all_orders: dict[str, ManagedOrder] = {}
        self.submitted_order_ids: list[str] = []
        self._fill_counter = 0

    def submit_order(self, order: ManagedOrder) -> ManagedOrder:
        self.open_orders[order.order_id] = order
        self.all_orders[order.order_id] = order
        self.submitted_order_ids.append(order.order_id)
        return order

    def cancel_order(self, order_id: str, *, timestamp: pd.Timestamp, reason: str) -> ManagedOrder:
        if order_id not in self.open_orders:
            raise KeyError(f"order {order_id!r} is not open")
        order = self.open_orders.pop(order_id)
        order.status = OrderStatus.CANCELLED
        return order

    def process_market_data(
        self,
        *,
        timestamp: pd.Timestamp,
        prices: Mapping[str, float],
    ) -> list[ExecutionFill]:
        fills: list[ExecutionFill] = []
        normalized_prices = {symbol.upper(): float(price) for symbol, price in prices.items()}
        for order in list(self.open_orders.values()):
            price = normalized_prices.get(order.symbol)
            if price is None or self.max_fill_ratio_per_tick == 0:
                continue
            requested_fill_quantity = min(
                order.remaining_quantity,
                order.quantity * min(self.max_fill_ratio_per_tick, 1.0),
            )
            fill_quantity = self._executable_quantity(
                order=order,
                requested_quantity=requested_fill_quantity,
                market_price=price,
            )
            if fill_quantity <= 0:
                continue
            fill_price = self._apply_slippage(price, order.side)
            gross_value = fill_quantity * fill_price
            commission = gross_value * self.commission_bps / 10_000
            self._fill_counter += 1
            fill = ExecutionFill(
                fill_id=f"paper-fill-{self._fill_counter:06d}",
                order_id=order.order_id,
                timestamp=timestamp,
                symbol=order.symbol,
                side=order.side,
                quantity=fill_quantity,
                fill_price=fill_price,
                gross_value=gross_value,
                commission=commission,
            )
            order.filled_quantity += fill_quantity
            order.status = (
                OrderStatus.FILLED
                if order.remaining_quantity <= 1e-10
                else OrderStatus.PARTIALLY_FILLED
            )
            self.portfolio.apply_fill(fill)
            fills.append(fill)
            if order.status == OrderStatus.FILLED:
                self.open_orders.pop(order.order_id, None)
        return fills

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        slippage = self.slippage_bps / 10_000
        if side == OrderSide.BUY:
            return price * (1 + slippage)
        return price * (1 - slippage)

    def _executable_quantity(
        self,
        *,
        order: ManagedOrder,
        requested_quantity: float,
        market_price: float,
    ) -> float:
        if requested_quantity <= 0:
            return 0.0

        fill_price = self._apply_slippage(market_price, order.side)
        if order.side == OrderSide.SELL:
            return min(requested_quantity, max(self.portfolio.position(order.symbol), 0.0))

        cash_required_per_share = fill_price * (1 + self.commission_bps / 10_000)
        if cash_required_per_share <= 0:
            return 0.0
        affordable_quantity = self.portfolio.cash / cash_required_per_share
        return min(requested_quantity, max(affordable_quantity, 0.0))
