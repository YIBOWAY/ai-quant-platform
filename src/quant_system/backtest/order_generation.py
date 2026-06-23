from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from quant_system.backtest.models import BacktestConfig, Order, OrderSide, TargetWeight
from quant_system.backtest.portfolio import Portfolio
from quant_system.trading_kernel import plan_rebalance
from quant_system.trading_kernel.weights import _apply_weight_constraints


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
        # Thin adapter over the shared pure kernel. The backtest is the superset
        # call site: weight caps, whole-share flooring, and the double
        # min-order-value gate, in sorted-union symbol order (no sells-first).
        normalized_prices = {
            symbol.upper(): float(price) for symbol, price in prices.items()
        }
        target_map = {
            target.symbol.upper(): float(target.target_weight) for target in targets
        }
        equity = portfolio.equity(normalized_prices)
        intents = plan_rebalance(
            holdings=portfolio.positions,
            target_weights=target_map,
            prices=normalized_prices,
            equity=equity,
            min_order_value=self.config.min_order_value,
            whole_share=self.config.whole_share_orders,
            max_weight_per_symbol=self.config.max_weight_per_symbol,
            sector_cap=self.config.sector_cap,
            sector_map=self.config.sector_map,
        )
        order_date = pd.Timestamp(timestamp).strftime("%Y%m%d")
        return [
            Order(
                order_id=f"{order_date}-{intent.symbol_index:04d}",
                timestamp=pd.Timestamp(timestamp),
                symbol=intent.symbol,
                side=OrderSide(intent.side.value),
                quantity=intent.quantity,
                reason=intent.reason,
            )
            for intent in intents
        ]

    def _apply_weight_constraints(self, target_map: dict[str, float]) -> dict[str, float]:
        """Clamp target weights to the configured caps.

        Thin pass-through to the shared kernel constraint so the backtest and
        paper paths apply identical capping. Kept as a method for the existing
        engine-depth unit tests that exercise capping directly.
        """
        return _apply_weight_constraints(
            target_map,
            max_weight_per_symbol=self.config.max_weight_per_symbol,
            sector_cap=self.config.sector_cap,
            sector_map=self.config.sector_map,
        )
