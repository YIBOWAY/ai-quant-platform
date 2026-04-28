import json
from pathlib import Path

import pytest

from quant_system.prediction_market.data.polymarket_stub import PolymarketStub
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.execution_threshold import (
    ExecutionThresholdConfig,
    ProfitThresholdChecker,
)
from quant_system.prediction_market.models import (
    CLOBOrder,
    Market,
    MispricingCandidate,
    OrderBookSnapshot,
    Outcome,
)
from quant_system.prediction_market.optimizer.greedy_stub import GreedyStub
from quant_system.prediction_market.partial_fill import PartialFillManager, PartialFillState
from quant_system.prediction_market.pipeline import run_dry_arbitrage
from quant_system.prediction_market.scanners.outcome_set_consistency import (
    OutcomeSetConsistencyScanner,
)
from quant_system.prediction_market.scanners.yes_no_arbitrage import YesNoArbitrageScanner
from quant_system.prediction_market.settlement import SettlementRiskTracker


def _market(outcomes: list[Outcome] | None = None) -> Market:
    return Market(
        market_id="m-test",
        event_id="e-test",
        condition_id="c-test",
        question="Will this test pass?",
        outcomes=outcomes
        or [
            Outcome(name="YES", outcome_index=0, token_id="token-yes"),
            Outcome(name="NO", outcome_index=1, token_id="token-no"),
        ],
    )


def _book(token_id: str, ask_price: float) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        market_id="m-test",
        condition_id="c-test",
        token_id=token_id,
        bids=[CLOBOrder(price=max(ask_price - 0.02, 0.01), size=100)],
        asks=[CLOBOrder(price=ask_price, size=100)],
    )


def test_sample_provider_yes_no_sums_below_one() -> None:
    provider = SamplePredictionMarketProvider()
    binary_markets = [market for market in provider.list_markets() if len(market.outcomes) == 2]

    sums = []
    for market in binary_markets:
        books = provider.get_order_books(market.market_id)
        sums.append(sum(book.best_ask.price for book in books if book.best_ask is not None))

    assert sums
    assert all(total <= 1.0 for total in sums)
    assert any(total < 0.98 for total in sums)


def test_yes_no_arbitrage_scanner_detects_known_case() -> None:
    scanner = YesNoArbitrageScanner(min_edge_bps=200)
    candidates = scanner.scan(
        market=_market(),
        order_books=[_book("token-yes", 0.40), _book("token-no", 0.50)],
    )

    assert len(candidates) == 1
    assert candidates[0].edge_bps == pytest.approx(1000.0)


def test_outcome_set_scanner_handles_three_way() -> None:
    market = _market(
        [
            Outcome(name="A", outcome_index=0, token_id="token-a"),
            Outcome(name="B", outcome_index=1, token_id="token-b"),
            Outcome(name="C", outcome_index=2, token_id="token-c"),
        ]
    )
    scanner = OutcomeSetConsistencyScanner(min_edge_bps=200)

    candidates = scanner.scan(
        market=market,
        order_books=[
            _book("token-a", 0.30),
            _book("token-b", 0.35),
            _book("token-c", 0.40),
        ],
    )

    assert len(candidates) == 1
    assert candidates[0].edge_bps == pytest.approx(500.0)


def test_threshold_checker_filters_low_edge() -> None:
    candidate = MispricingCandidate(
        market_id="m-test",
        condition_id="c-test",
        scanner_id="test",
        description="low edge",
        edge_bps=100,
        prices={"YES": 0.495, "NO": 0.495},
    )
    checker = ProfitThresholdChecker(ExecutionThresholdConfig(min_edge_bps=200))

    assert checker.is_allowed(candidate) is False


def test_polymarket_stub_raises_not_implemented() -> None:
    stub = PolymarketStub()

    with pytest.raises(NotImplementedError, match="intentionally not wired"):
        stub.list_markets()


def test_dry_arbitrage_writes_proposed_trade_only(tmp_path) -> None:
    trades = run_dry_arbitrage(
        provider=SamplePredictionMarketProvider(),
        optimizer=GreedyStub(max_capital=100),
        threshold=ProfitThresholdChecker(ExecutionThresholdConfig(min_edge_bps=200)),
        output_dir=tmp_path,
    )

    proposals = list(Path(tmp_path, "prediction_market", "proposals").glob("*.json"))
    assert trades
    assert proposals
    payload = json.loads(proposals[0].read_text(encoding="utf-8"))
    assert payload["dry_run"] is True
    assert not Path(tmp_path, "prediction_market", "orders").exists()
    assert not Path(tmp_path, "prediction_market", "fills").exists()
    assert not Path(tmp_path, "prediction_market", "token_transfers").exists()


def test_partial_fill_manager_state_machine_initial_state() -> None:
    manager = PartialFillManager()

    assert manager.state == PartialFillState.NEW


def test_settlement_risk_tracker_is_placeholder() -> None:
    tracker = SettlementRiskTracker()

    with pytest.raises(NotImplementedError, match="placeholder"):
        tracker.assess_resolution_risk("m-test")
