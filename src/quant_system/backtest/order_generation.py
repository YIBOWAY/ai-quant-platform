from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from quant_system.backtest.models import BacktestConfig, Order, OrderSide, TargetWeight
from quant_system.backtest.portfolio import Portfolio


class OrderGenerator:
    def __init__(self, config: BacktestConfig) -> None:
        self.config = config

    def generate_orders(
        self,
        *,
        timestamp: pd.Timestamp,
        targets: list[TargetWeight],
        portfolio: Portfolio,
        prices: Mapping[str, float],
    ) -> list[Order]:
        normalized_prices = {symbol.upper(): float(price) for symbol, price in prices.items()}
        target_map = {target.symbol.upper(): float(target.target_weight) for target in targets}
        symbols = sorted(set(portfolio.positions).union(target_map))
        equity = portfolio.equity(normalized_prices)
        orders: list[Order] = []

        for index, symbol in enumerate(symbols, start=1):
            if symbol not in normalized_prices:
                raise ValueError(f"missing order generation price for {symbol}")
            price = normalized_prices[symbol]
            current_quantity = portfolio.position(symbol)
            current_value = current_quantity * price
            target_value = target_map.get(symbol, 0.0) * equity
            value_delta = target_value - current_value
            if abs(value_delta) < self.config.min_order_value:
                continue
            side = OrderSide.BUY if value_delta > 0 else OrderSide.SELL
            quantity = abs(value_delta) / price
            if quantity <= 0:
                continue
            orders.append(
                Order(
                    order_id=f"{pd.Timestamp(timestamp).strftime('%Y%m%d')}-{index:04d}",
                    timestamp=pd.Timestamp(timestamp),
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    reason="rebalance_to_target_weight",
                )
            )
        return orders
