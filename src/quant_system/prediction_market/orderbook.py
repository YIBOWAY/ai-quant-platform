from __future__ import annotations

from quant_system.prediction_market.models import CLOBOrder, OrderBookSnapshot


class OrderBookView:
    def __init__(self, snapshot: OrderBookSnapshot) -> None:
        self.snapshot = snapshot

    @property
    def best_bid(self) -> CLOBOrder | None:
        return self.snapshot.best_bid

    @property
    def best_ask(self) -> CLOBOrder | None:
        return self.snapshot.best_ask

    @property
    def spread(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask.price - self.best_bid.price

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid.price + self.best_ask.price) / 2
