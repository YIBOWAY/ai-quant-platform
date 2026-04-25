from __future__ import annotations

from collections.abc import Mapping

from quant_system.backtest.models import BacktestConfig, Fill, FillStatus, Order, OrderSide
from quant_system.backtest.portfolio import Portfolio


class BrokerSimulator:
    """Market-order simulator with configurable commission and slippage."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def execute_orders(
        self,
        orders: list[Order],
        prices: Mapping[str, float],
        portfolio: Portfolio,
    ) -> list[Fill]:
        fills: list[Fill] = []
        sorted_orders = sorted(orders, key=lambda order: 0 if order.side == OrderSide.SELL else 1)
        for order in sorted_orders:
            symbol = order.symbol.upper()
            if symbol not in prices:
                raise ValueError(f"missing execution price for {symbol}")
            requested_price = float(prices[symbol])
            quantity = self._executable_quantity(order, requested_price, portfolio)
            if quantity <= 0:
                continue

            fill_price = self._fill_price(requested_price, order.side)
            gross_value = quantity * fill_price
            commission = gross_value * self.config.commission_bps / 10_000
            status = FillStatus.FILLED
            if quantity < order.quantity:
                status = FillStatus.PARTIAL
            fill = Fill(
                fill_id=f"fill-{order.order_id}",
                order_id=order.order_id,
                timestamp=order.timestamp,
                symbol=symbol,
                side=order.side,
                quantity=quantity,
                requested_price=requested_price,
                fill_price=fill_price,
                gross_value=gross_value,
                commission=commission,
                slippage_bps=self.config.slippage_bps,
                status=status,
            )
            portfolio.apply_fill(fill)
            fills.append(fill)
        return fills

    def _fill_price(self, requested_price: float, side: OrderSide) -> float:
        slippage = self.config.slippage_bps / 10_000
        if side == OrderSide.BUY:
            return requested_price * (1 + slippage)
        return requested_price * (1 - slippage)

    def _executable_quantity(
        self,
        order: Order,
        requested_price: float,
        portfolio: Portfolio,
    ) -> float:
        fill_price = self._fill_price(requested_price, order.side)
        if order.side == OrderSide.SELL:
            return min(order.quantity, max(portfolio.position(order.symbol), 0.0))

        cash_required_per_share = fill_price * (1 + self.config.commission_bps / 10_000)
        if cash_required_per_share <= 0:
            return 0.0
        affordable_quantity = portfolio.cash / cash_required_per_share
        return min(order.quantity, max(affordable_quantity, 0.0))
