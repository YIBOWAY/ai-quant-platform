from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from quant_system.prediction_market.data.base import PredictionMarketDataProvider
from quant_system.prediction_market.execution_threshold import ProfitThresholdChecker
from quant_system.prediction_market.models import Market, MispricingCandidate, ProposedTrade
from quant_system.prediction_market.optimizer.base import OptimizerInterface
from quant_system.prediction_market.scanners.outcome_set_consistency import (
    OutcomeSetConsistencyScanner,
)
from quant_system.prediction_market.scanners.yes_no_arbitrage import YesNoArbitrageScanner


class MispricingScanner(Protocol):
    def scan(self, *, market: Market, order_books: list) -> list[MispricingCandidate]:
        """Scan one market and its outcome order books."""


def default_scanners() -> list[MispricingScanner]:
    return [YesNoArbitrageScanner(), OutcomeSetConsistencyScanner()]


def scan_market(
    *,
    provider: PredictionMarketDataProvider,
    scanners: list[MispricingScanner] | None = None,
    max_markets: int | None = None,
) -> list[MispricingCandidate]:
    active_scanners = scanners or default_scanners()
    candidates: list[MispricingCandidate] = []
    for market in provider.list_markets(limit=max_markets):
        order_books = provider.get_order_books(market.market_id)
        for scanner in active_scanners:
            candidates.extend(scanner.scan(market=market, order_books=order_books))
    return candidates


def run_dry_arbitrage(
    *,
    provider: PredictionMarketDataProvider,
    optimizer: OptimizerInterface,
    threshold: ProfitThresholdChecker,
    output_dir: str | Path,
    scanners: list[MispricingScanner] | None = None,
    max_markets: int | None = None,
) -> list[ProposedTrade]:
    proposals_dir = Path(output_dir) / "prediction_market" / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    trades: list[ProposedTrade] = []
    for candidate in scan_market(
        provider=provider,
        scanners=scanners,
        max_markets=max_markets,
    ):
        if not threshold.is_allowed(candidate):
            continue
        trade = optimizer.solve(candidate)
        if trade is None:
            continue
        trades.append(trade)
        path = proposals_dir / f"{trade.proposal_id}.json"
        path.write_text(
            json.dumps(trade.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return trades
