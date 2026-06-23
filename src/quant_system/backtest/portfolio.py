from __future__ import annotations

from collections.abc import Mapping

from quant_system.backtest.models import Fill
from quant_system.trading_kernel import apply_fill_to_portfolio


class Portfolio:
    def __init__(self, *, initial_cash: float) -> None:
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions: dict[str, float] = {}

    def position(self, symbol: str) -> float:
        return float(self.positions.get(symbol.upper(), 0.0))

    def market_value(self, prices: Mapping[str, float]) -> float:
        normalized_prices = {symbol.upper(): float(price) for symbol, price in prices.items()}
        missing = sorted(symbol for symbol in self.positions if symbol not in normalized_prices)
        if missing:
            raise ValueError(f"missing mark prices: {', '.join(missing)}")
        return sum(
            quantity * normalized_prices[symbol]
            for symbol, quantity in self.positions.items()
        )

    def equity(self, prices: Mapping[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def apply_fill(self, fill: Fill) -> None:
        # Delegate the cash/position arithmetic to the shared pure kernel so the
        # backtest and paper portfolios cannot drift apart.
        self.positions, self.cash = apply_fill_to_portfolio(
            self.positions, self.cash, fill
        )
