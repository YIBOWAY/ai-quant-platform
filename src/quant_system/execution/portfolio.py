from __future__ import annotations

from collections.abc import Mapping

from quant_system.execution.models import ExecutionFill, OrderSide


class PaperPortfolio:
    def __init__(self, *, initial_cash: float) -> None:
        if initial_cash < 0:
            raise ValueError("initial_cash must be non-negative")
        self.initial_cash = float(initial_cash)
        self.cash = float(initial_cash)
        self.positions: dict[str, float] = {}

    def position(self, symbol: str) -> float:
        return float(self.positions.get(symbol.upper(), 0.0))

    def market_value(self, prices: Mapping[str, float]) -> float:
        normalized = {symbol.upper(): float(price) for symbol, price in prices.items()}
        return sum(
            quantity * normalized.get(symbol, 0.0)
            for symbol, quantity in self.positions.items()
        )

    def equity(self, prices: Mapping[str, float]) -> float:
        return self.cash + self.market_value(prices)

    def apply_fill(self, fill: ExecutionFill) -> None:
        symbol = fill.symbol.upper()
        current = self.position(symbol)
        if fill.side == OrderSide.BUY:
            self.cash -= fill.gross_value + fill.commission
            self.positions[symbol] = current + fill.quantity
        else:
            self.cash += fill.gross_value - fill.commission
            self.positions[symbol] = current - fill.quantity
        if abs(self.positions.get(symbol, 0.0)) < 1e-10:
            self.positions.pop(symbol, None)
