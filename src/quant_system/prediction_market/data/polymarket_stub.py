from __future__ import annotations

from quant_system.prediction_market.models import Market, OrderBookSnapshot


class PolymarketStub:
    """Phase 8 placeholder for future Polymarket Gamma/CLOB adapters.

    Official docs to review before a later live/data integration:
    - https://docs.polymarket.com/
    - https://docs.polymarket.com/developers/CLOB/introduction

    This class intentionally performs no HTTP requests, WebSocket connections,
    signing, chain RPC, redemption, or token transfer.
    """

    gamma_endpoint = "https://gamma-api.polymarket.com"
    clob_endpoint = "https://clob.polymarket.com"

    def list_markets(self) -> list[Market]:
        raise NotImplementedError(
            "Polymarket live integration is intentionally not wired in Phase 8 — "
            "see docs/architecture/phase_8_architecture.md §8.4"
        )

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        raise NotImplementedError(
            "Polymarket live integration is intentionally not wired in Phase 8 — "
            "see docs/architecture/phase_8_architecture.md §8.4"
        )
