from __future__ import annotations

from pydantic import BaseModel, Field

from quant_system.prediction_market.data.base import PredictionMarketDataProvider
from quant_system.prediction_market.models import MispricingCandidate, PriceHistoryPoint
from quant_system.prediction_market.pipeline import scan_market
from quant_system.prediction_market.scanners.outcome_set_consistency import (
    OutcomeSetConsistencyScanner,
)
from quant_system.prediction_market.scanners.yes_no_arbitrage import YesNoArbitrageScanner


class PredictionMarketBacktestConfig(BaseModel):
    min_edge_bps: float = Field(default=200, ge=0)
    capital_limit: float = Field(default=1_000, ge=0)
    max_legs: int = Field(default=3, ge=1)
    max_markets: int = Field(default=50, ge=1)
    fee_bps: float = Field(default=0, ge=0)
    history_interval: str = "1d"
    history_fidelity: int = Field(default=60, ge=1)


class PredictionMarketOpportunity(BaseModel):
    candidate_id: str
    market_id: str
    condition_id: str
    scanner_id: str
    edge_bps: float
    net_edge_bps: float
    estimated_edge: float
    capital: float
    hypothetical: bool = True
    description: str


class PredictionMarketEquityPoint(BaseModel):
    index: int
    market_id: str
    estimated_edge: float
    cumulative_estimated_edge: float


class PredictionMarketBacktestMetrics(BaseModel):
    market_count: int
    opportunity_count: int
    trigger_rate: float
    mean_edge_bps: float
    max_edge_bps: float
    total_estimated_edge: float
    max_drawdown: float


class PredictionMarketBacktestResult(BaseModel):
    config: PredictionMarketBacktestConfig
    metrics: PredictionMarketBacktestMetrics
    opportunities: list[PredictionMarketOpportunity]
    equity_curve: list[PredictionMarketEquityPoint]
    assumptions: list[str]


def run_prediction_market_quasi_backtest(
    *,
    provider: PredictionMarketDataProvider,
    config: PredictionMarketBacktestConfig,
) -> PredictionMarketBacktestResult:
    markets = provider.list_markets(limit=config.max_markets)
    market_ids = {market.market_id for market in markets}
    historical_opportunities = _build_historical_opportunities(
        provider=provider,
        markets=markets,
        config=config,
    )
    if historical_opportunities:
        opportunities = historical_opportunities
        equity_curve = _build_equity_curve(opportunities)
        assumptions = [
            "Research-only quasi-backtest; no orders are submitted.",
            (
                "historical last-trade price observations are used when the "
                "public endpoint is available."
            ),
            "Displayed size, latency, fees, and slippage are simplified assumptions.",
            "No settlement outcome or hit-rate claim is made in Phase 11.",
        ]
    else:
        scanners = [
            YesNoArbitrageScanner(min_edge_bps=config.min_edge_bps),
            OutcomeSetConsistencyScanner(min_edge_bps=config.min_edge_bps),
        ]
        candidates = [
            candidate
            for candidate in scan_market(
                provider=_StaticMarketProvider(provider, market_ids),
                scanners=scanners,
                max_markets=config.max_markets,
            )
            if candidate.edge_bps >= config.min_edge_bps
        ]
        opportunities = [_candidate_to_opportunity(candidate, config) for candidate in candidates]
        equity_curve = _build_equity_curve(opportunities)
        assumptions = [
            "Research-only quasi-backtest; no orders are submitted.",
            "Best ask prices are treated as hypothetical observation prices.",
            "Displayed size, latency, fees, and slippage are simplified assumptions.",
            "No settlement outcome or hit-rate claim is made in Phase 11.",
        ]
    total_estimated_edge = sum(item.estimated_edge for item in opportunities)
    metrics = PredictionMarketBacktestMetrics(
        market_count=len(markets),
        opportunity_count=len(opportunities),
        trigger_rate=len(opportunities) / len(markets) if markets else 0.0,
        mean_edge_bps=(
            sum(item.net_edge_bps for item in opportunities) / len(opportunities)
            if opportunities
            else 0.0
        ),
        max_edge_bps=max((item.net_edge_bps for item in opportunities), default=0.0),
        total_estimated_edge=total_estimated_edge,
        max_drawdown=_max_drawdown([item.cumulative_estimated_edge for item in equity_curve]),
    )
    return PredictionMarketBacktestResult(
        config=config,
        metrics=metrics,
        opportunities=opportunities,
        equity_curve=equity_curve,
        assumptions=assumptions,
    )


class _StaticMarketProvider:
    def __init__(self, provider: PredictionMarketDataProvider, market_ids: set[str]) -> None:
        self.provider = provider
        self.market_ids = market_ids

    def list_markets(self, limit=None):
        markets = [
            market
            for market in self.provider.list_markets()
            if market.market_id in self.market_ids
        ]
        return markets if limit is None else markets[:limit]

    def get_order_books(self, market_id: str):
        return self.provider.get_order_books(market_id)


def _candidate_to_opportunity(
    candidate: MispricingCandidate,
    config: PredictionMarketBacktestConfig,
) -> PredictionMarketOpportunity:
    net_edge_bps = max(candidate.edge_bps - config.fee_bps, 0.0)
    capital = config.capital_limit
    estimated_edge = capital * (net_edge_bps / 10_000)
    return PredictionMarketOpportunity(
        candidate_id=candidate.candidate_id,
        market_id=candidate.market_id,
        condition_id=candidate.condition_id,
        scanner_id=candidate.scanner_id,
        edge_bps=candidate.edge_bps,
        net_edge_bps=net_edge_bps,
        estimated_edge=estimated_edge,
        capital=capital,
        description=candidate.description,
    )


def _build_equity_curve(
    opportunities: list[PredictionMarketOpportunity],
) -> list[PredictionMarketEquityPoint]:
    points: list[PredictionMarketEquityPoint] = []
    cumulative = 0.0
    for index, opportunity in enumerate(opportunities, start=1):
        cumulative += opportunity.estimated_edge
        points.append(
            PredictionMarketEquityPoint(
                index=index,
                market_id=opportunity.market_id,
                estimated_edge=opportunity.estimated_edge,
                cumulative_estimated_edge=cumulative,
            )
        )
    return points


def _build_historical_opportunities(
    *,
    provider: PredictionMarketDataProvider,
    markets,
    config: PredictionMarketBacktestConfig,
) -> list[PredictionMarketOpportunity]:
    if not hasattr(provider, "get_price_history"):
        return []

    opportunities: list[PredictionMarketOpportunity] = []
    for market in markets:
        if len(market.outcomes) != 2:
            continue
        yes_history = provider.get_price_history(
            market.outcomes[0].token_id,
            interval=config.history_interval,
            fidelity=config.history_fidelity,
        )
        no_history = provider.get_price_history(
            market.outcomes[1].token_id,
            interval=config.history_interval,
            fidelity=config.history_fidelity,
        )
        for timestamp, yes_price, no_price in _aligned_history_points(yes_history, no_history):
            combined_price = yes_price + no_price
            edge_bps = max((1.0 - combined_price) * 10_000, 0.0)
            if edge_bps < config.min_edge_bps:
                continue
            net_edge_bps = max(edge_bps - config.fee_bps, 0.0)
            estimated_edge = config.capital_limit * (net_edge_bps / 10_000)
            opportunities.append(
                PredictionMarketOpportunity(
                    candidate_id=f"{market.market_id}-{timestamp}",
                    market_id=market.market_id,
                    condition_id=market.condition_id,
                    scanner_id="historical_complete_set",
                    edge_bps=edge_bps,
                    net_edge_bps=net_edge_bps,
                    estimated_edge=estimated_edge,
                    capital=config.capital_limit,
                    description=(
                        f"Historical YES+NO last-trade sum={combined_price:.4f} at {timestamp}"
                    ),
                )
            )
    return opportunities


def _aligned_history_points(
    yes_history: list[PriceHistoryPoint],
    no_history: list[PriceHistoryPoint],
) -> list[tuple[str, float, float]]:
    no_lookup = {point.timestamp: point.price for point in no_history}
    aligned: list[tuple[str, float, float]] = []
    for point in yes_history:
        no_price = no_lookup.get(point.timestamp)
        if no_price is None:
            continue
        aligned.append((point.timestamp, point.price, no_price))
    return aligned


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for value in values:
        peak = max(peak, value)
        max_dd = max(max_dd, peak - value)
    return max_dd
