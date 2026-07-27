from quant_system.prediction_market.models import (
    CLOBOrder,
    Market,
    OrderBookSnapshot,
    Outcome,
)
from quant_system.prediction_market.scanners.outcome_set_consistency import (
    OutcomeSetConsistencyScanner,
)
from quant_system.prediction_market.scanners.yes_no_arbitrage import (
    YesNoArbitrageScanner,
)


def _market(*outcomes: tuple[str, str]) -> Market:
    return Market(
        market_id="decimal-boundary",
        event_id="decimal-boundary-event",
        condition_id="decimal-boundary-condition",
        question="Does the inclusive decimal threshold remain exact?",
        outcomes=[
            Outcome(name=name, outcome_index=index, token_id=token_id)
            for index, (name, token_id) in enumerate(outcomes)
        ],
    )


def _book(token_id: str, ask: float) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        market_id="decimal-boundary",
        condition_id="decimal-boundary-condition",
        token_id=token_id,
        bids=[CLOBOrder(price=max(ask - 0.01, 0.01), size=10)],
        asks=[CLOBOrder(price=ask, size=10)],
    )


def test_three_way_decimal_edge_exactly_on_threshold_is_included() -> None:
    scanner = OutcomeSetConsistencyScanner(min_edge_bps=200)
    candidates = scanner.scan(
        market=_market(("A", "a"), ("B", "b"), ("C", "c")),
        order_books=[
            _book("a", 0.28),
            _book("b", 0.34),
            _book("c", 0.36),
        ],
    )

    assert len(candidates) == 1
    assert candidates[0].edge_bps == 200.0


def test_three_way_decimal_edge_below_threshold_is_rejected() -> None:
    scanner = OutcomeSetConsistencyScanner(min_edge_bps=200)

    assert (
        scanner.scan(
            market=_market(("A", "a"), ("B", "b"), ("C", "c")),
            order_books=[
                _book("a", 0.28001),
                _book("b", 0.34),
                _book("c", 0.36),
            ],
        )
        == []
    )


def test_binary_decimal_edge_exactly_on_threshold_is_included() -> None:
    scanner = YesNoArbitrageScanner(min_edge_bps=200)
    candidates = scanner.scan(
        market=_market(("YES", "yes"), ("NO", "no")),
        order_books=[_book("yes", 0.41), _book("no", 0.57)],
    )

    assert len(candidates) == 1
    assert candidates[0].edge_bps == 200.0
