from __future__ import annotations

from quant_system.prediction_market.models import Market, MispricingCandidate, OrderBookSnapshot


class YesNoArbitrageScanner:
    scanner_id = "yes_no_arbitrage"

    def __init__(self, *, min_edge_bps: float = 200) -> None:
        self.min_edge_bps = min_edge_bps

    def scan(
        self,
        *,
        market: Market,
        order_books: list[OrderBookSnapshot],
    ) -> list[MispricingCandidate]:
        if len(market.outcomes) != 2:
            return []
        outcome_by_name = {outcome.name.upper(): outcome for outcome in market.outcomes}
        if set(outcome_by_name) != {"YES", "NO"}:
            return []
        books = {book.token_id: book for book in order_books}
        prices: dict[str, float] = {}
        for name in ["YES", "NO"]:
            book = books.get(outcome_by_name[name].token_id)
            if book is None or book.best_ask is None:
                return []
            prices[name] = book.best_ask.price
        total = prices["YES"] + prices["NO"]
        edge_bps = (1.0 - total) * 10_000
        if edge_bps < self.min_edge_bps:
            return []
        return [
            MispricingCandidate(
                market_id=market.market_id,
                condition_id=market.condition_id,
                scanner_id=self.scanner_id,
                description="YES and NO best asks sum below 1.0 in a complete binary market.",
                edge_bps=edge_bps,
                prices=prices,
                direction="underpriced_complete_set",
            )
        ]
