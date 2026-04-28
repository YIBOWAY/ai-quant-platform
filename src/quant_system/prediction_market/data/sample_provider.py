from __future__ import annotations

from quant_system.prediction_market.models import CLOBOrder, Market, OrderBookSnapshot, Outcome


class SamplePredictionMarketProvider:
    """Deterministic read-only sample data for Phase 8 scanners."""

    def __init__(self) -> None:
        self._markets = [
            Market(
                market_id="sample-binary-001",
                event_id="sample-event-001",
                condition_id="sample-condition-binary",
                question="Will the sample binary market resolve YES?",
                outcomes=[
                    Outcome(name="YES", outcome_index=0, token_id="sample-binary-yes"),
                    Outcome(name="NO", outcome_index=1, token_id="sample-binary-no"),
                ],
            ),
            Market(
                market_id="sample-three-way-001",
                event_id="sample-event-002",
                condition_id="sample-condition-three",
                question="Which sample outcome resolves?",
                outcomes=[
                    Outcome(name="A", outcome_index=0, token_id="sample-three-a"),
                    Outcome(name="B", outcome_index=1, token_id="sample-three-b"),
                    Outcome(name="C", outcome_index=2, token_id="sample-three-c"),
                ],
            ),
        ]
        self._asks = {
            "sample-binary-yes": 0.40,
            "sample-binary-no": 0.55,
            "sample-three-a": 0.30,
            "sample-three-b": 0.35,
            "sample-three-c": 0.40,
        }

    def list_markets(self) -> list[Market]:
        return list(self._markets)

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        market = next((item for item in self._markets if item.market_id == market_id), None)
        if market is None:
            raise KeyError(f"unknown sample market_id {market_id!r}")
        return [
            self._build_snapshot(
                market_id=market.market_id,
                condition_id=market.condition_id,
                token_id=outcome.token_id,
                ask=self._asks[outcome.token_id],
            )
            for outcome in market.outcomes
        ]

    @staticmethod
    def _build_snapshot(
        *,
        market_id: str,
        condition_id: str,
        token_id: str,
        ask: float,
    ) -> OrderBookSnapshot:
        bid = max(ask - 0.03, 0.01)
        return OrderBookSnapshot(
            market_id=market_id,
            condition_id=condition_id,
            token_id=token_id,
            bids=[CLOBOrder(price=bid, size=500)],
            asks=[CLOBOrder(price=ask, size=500)],
        )
