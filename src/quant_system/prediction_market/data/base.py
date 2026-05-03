from __future__ import annotations

from typing import Protocol

from quant_system.prediction_market.models import (
    Market,
    MarketTrade,
    OrderBookSnapshot,
    PriceHistoryPoint,
)


class PredictionMarketDataProvider(Protocol):
    def list_markets(self, limit: int | None = None) -> list[Market]:
        """Return available markets."""

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        """Return order book snapshots for every outcome token in one market."""

    def get_price_history(
        self,
        token_id: str,
        *,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> list[PriceHistoryPoint]:
        """Return historical public price points when available."""

    def get_trades(
        self,
        condition_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MarketTrade]:
        """Return historical public trades when available."""
