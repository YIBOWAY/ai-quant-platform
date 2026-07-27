from __future__ import annotations

from decimal import Decimal

from quant_system.prediction_market.models import Market, MispricingCandidate, OrderBookSnapshot


class OutcomeSetConsistencyScanner:
    scanner_id = "outcome_set_consistency"

    def __init__(self, *, min_edge_bps: float = 200) -> None:
        self.min_edge_bps = min_edge_bps

    def scan(
        self,
        *,
        market: Market,
        order_books: list[OrderBookSnapshot],
    ) -> list[MispricingCandidate]:
        if len(market.outcomes) < 2:
            return []
        books = {book.token_id: book for book in order_books}
        prices: dict[str, float] = {}
        for outcome in market.outcomes:
            book = books.get(outcome.token_id)
            if book is None or book.best_ask is None:
                return []
            prices[outcome.name] = book.best_ask.price
        total = sum((Decimal(str(price)) for price in prices.values()), Decimal(0))
        edge_bps = float(abs(Decimal(1) - total) * Decimal(10_000))
        if edge_bps < self.min_edge_bps:
            return []
        direction = (
            "underpriced_complete_set"
            if total < Decimal(1)
            else "overpriced_complete_set"
        )
        return [
            MispricingCandidate(
                market_id=market.market_id,
                condition_id=market.condition_id,
                scanner_id=self.scanner_id,
                description="Outcome best asks do not sum to 1.0 for a complete set.",
                edge_bps=edge_bps,
                prices=prices,
                direction=direction,
            )
        ]
