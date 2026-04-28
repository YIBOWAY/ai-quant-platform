from __future__ import annotations

from typing import Protocol

from quant_system.prediction_market.models import Market, OrderBookSnapshot


class PredictionMarketDataProvider(Protocol):
    def list_markets(self) -> list[Market]:
        """Return available markets."""

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        """Return order book snapshots for every outcome token in one market."""
