from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class RiskLimits(BaseModel):
    kill_switch: bool = True
    max_position_size: float = Field(default=0.05, ge=0, le=1)
    max_daily_loss: float = Field(default=0.02, ge=0, le=1)
    max_drawdown: float = Field(default=0.10, ge=0, le=1)
    max_order_value: float = Field(default=10_000.0, ge=0)
    allowed_symbols: list[str] = Field(default_factory=list)
    blocked_symbols: list[str] = Field(default_factory=list)

    @property
    def normalized_allowed_symbols(self) -> set[str]:
        return {symbol.upper().strip() for symbol in self.allowed_symbols}

    @property
    def normalized_blocked_symbols(self) -> set[str]:
        return {symbol.upper().strip() for symbol in self.blocked_symbols}


class RiskContext(BaseModel):
    cash: float
    equity: float = Field(ge=0)
    peak_equity: float = Field(ge=0)
    daily_pnl: float = 0.0
    positions: dict[str, float] = Field(default_factory=dict)
    latest_prices: dict[str, float] = Field(default_factory=dict)

    def position(self, symbol: str) -> float:
        return float(self.positions.get(symbol.upper(), 0.0))

    def price_for(self, symbol: str, fallback: float | None = None) -> float | None:
        return self.latest_prices.get(symbol.upper(), fallback)


class RiskBreach(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: pd.Timestamp
    rule_name: str
    symbol: str
    message: str
    order_id: str | None = None


class RiskDecision(BaseModel):
    approved: bool
    breaches: list[RiskBreach] = Field(default_factory=list)

    @property
    def reason(self) -> str:
        return "; ".join(breach.message for breach in self.breaches)


def context_from_portfolio(
    *,
    cash: float,
    positions: Mapping[str, float],
    prices: Mapping[str, float],
    equity: float,
    peak_equity: float,
    daily_pnl: float,
) -> RiskContext:
    return RiskContext(
        cash=cash,
        equity=equity,
        peak_equity=peak_equity,
        daily_pnl=daily_pnl,
        positions={symbol.upper(): float(quantity) for symbol, quantity in positions.items()},
        latest_prices={symbol.upper(): float(price) for symbol, price in prices.items()},
    )
