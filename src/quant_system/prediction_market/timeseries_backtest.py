from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean, median, pstdev
from typing import Literal

from pydantic import BaseModel, Field

from quant_system.prediction_market.execution_threshold import (
    ExecutionThresholdConfig,
    ProfitThresholdChecker,
)
from quant_system.prediction_market.models import (
    HistoricalSnapshotRecord,
    Market,
    MispricingCandidate,
    OrderBookSnapshot,
)
from quant_system.prediction_market.pipeline import MispricingScanner, scan_market
from quant_system.prediction_market.scanners.outcome_set_consistency import (
    OutcomeSetConsistencyScanner,
)
from quant_system.prediction_market.scanners.yes_no_arbitrage import YesNoArbitrageScanner
from quant_system.prediction_market.storage import PredictionMarketSnapshotStore


class PredictionMarketTimeseriesBacktestConfig(BaseModel):
    provider: Literal["sample", "polymarket"] = "sample"
    start_time: str | None = None
    end_time: str | None = None
    scanners: list[Literal["yes_no_arbitrage", "outcome_set_consistency"]] = Field(
        default_factory=lambda: ["yes_no_arbitrage", "outcome_set_consistency"]
    )
    min_edge_bps: float = Field(default=200.0, ge=0)
    capital_limit: float = Field(default=1_000.0, gt=0)
    max_legs: int = Field(default=3, gt=0)
    max_markets: int = Field(default=50, gt=0)
    fee_bps: float = Field(default=0.0, ge=0)
    display_size_multiplier: float = Field(default=1.0, gt=0)
    market_ids: list[str] = Field(default_factory=list)


class SnapshotOpportunity(BaseModel):
    timestamp_utc: str
    market_id: str
    condition_id: str
    scanner_id: str
    direction: str
    edge_bps: float
    description: str


class SimulatedLeg(BaseModel):
    token_id: str
    side: Literal["buy", "sell"]
    price: float
    size: float


class SimulatedTrade(BaseModel):
    timestamp_utc: str
    market_id: str
    condition_id: str
    scanner_id: str
    direction: str
    size: float
    notional: float
    estimated_profit: float
    edge_bps: float
    net_edge_bps: float
    legs: list[SimulatedLeg]
    execution_mode: str = "simulated_snapshot_fill"


class DailyOpportunitySummary(BaseModel):
    date: str
    opportunity_count: int
    simulated_trade_count: int
    estimated_profit: float


class EquityCurvePoint(BaseModel):
    timestamp_utc: str
    cumulative_estimated_profit: float


class SensitivityPoint(BaseModel):
    min_edge_bps: float
    opportunity_count: int
    simulated_trade_count: int
    cumulative_estimated_profit: float


class PredictionMarketTimeseriesMetrics(BaseModel):
    provider: str
    market_count: int
    snapshot_count: int
    market_snapshot_count: int
    opportunity_count: int
    simulated_trade_count: int
    trigger_rate: float
    mean_edge_bps: float
    median_edge_bps: float
    max_edge_bps: float
    cumulative_estimated_profit: float
    max_drawdown: float
    daily_volatility_proxy: float


class PredictionMarketTimeseriesBacktestResult(BaseModel):
    config: PredictionMarketTimeseriesBacktestConfig
    metrics: PredictionMarketTimeseriesMetrics
    opportunities: list[SnapshotOpportunity]
    simulated_trades: list[SimulatedTrade]
    daily_summary: list[DailyOpportunitySummary]
    equity_curve: list[EquityCurvePoint]
    sensitivity: list[SensitivityPoint]
    assumptions: list[str]


@dataclass(slots=True)
class _SnapshotMarket:
    market: Market
    order_books: list[OrderBookSnapshot]


class SnapshotMatchingEngine:
    def __init__(
        self,
        *,
        fee_bps: float,
        display_size_multiplier: float,
        capital_limit: float,
    ) -> None:
        self.fee_bps = fee_bps
        self.display_size_multiplier = display_size_multiplier
        self.capital_limit = capital_limit

    def simulate(
        self,
        *,
        timestamp_utc: str,
        candidate: MispricingCandidate,
        market: Market,
        order_books: list[OrderBookSnapshot],
    ) -> SimulatedTrade | None:
        books_by_token = {book.token_id: book for book in order_books}
        legs: list[SimulatedLeg] = []
        prices: list[float] = []
        sizes: list[float] = []

        if candidate.direction == "underpriced_complete_set":
            for outcome in market.outcomes:
                book = books_by_token.get(outcome.token_id)
                best_ask = book.best_ask if book else None
                if best_ask is None:
                    return None
                legs.append(
                    SimulatedLeg(
                        token_id=outcome.token_id,
                        side="buy",
                        price=best_ask.price,
                        size=0.0,
                    )
                )
                prices.append(best_ask.price)
                sizes.append(best_ask.size)
            gross_edge = max(1.0 - sum(prices), 0.0)
        else:
            for outcome in market.outcomes:
                book = books_by_token.get(outcome.token_id)
                best_bid = book.best_bid if book else None
                if best_bid is None:
                    return None
                legs.append(
                    SimulatedLeg(
                        token_id=outcome.token_id,
                        side="sell",
                        price=best_bid.price,
                        size=0.0,
                    )
                )
                prices.append(best_bid.price)
                sizes.append(best_bid.size)
            gross_edge = max(sum(prices) - 1.0, 0.0)

        total_price = sum(prices)
        if gross_edge <= 0 or total_price <= 0:
            return None

        fee_fraction = self.fee_bps / 10_000
        net_edge_fraction = max(gross_edge - fee_fraction, 0.0)
        if net_edge_fraction <= 0:
            return None

        size_cap = min(sizes) * self.display_size_multiplier
        affordable_size = self.capital_limit / total_price
        size = min(size_cap, affordable_size)
        if size <= 0:
            return None
        for leg in legs:
            leg.size = size
        notional = size * total_price
        estimated_profit = size * net_edge_fraction
        return SimulatedTrade(
            timestamp_utc=timestamp_utc,
            market_id=candidate.market_id,
            condition_id=candidate.condition_id,
            scanner_id=candidate.scanner_id,
            direction=candidate.direction,
            size=size,
            notional=notional,
            estimated_profit=estimated_profit,
            edge_bps=gross_edge * 10_000,
            net_edge_bps=net_edge_fraction * 10_000,
            legs=legs,
        )


def run_prediction_market_timeseries_backtest(
    *,
    store: PredictionMarketSnapshotStore,
    config: PredictionMarketTimeseriesBacktestConfig,
) -> PredictionMarketTimeseriesBacktestResult:
    records = store.load_history_records(
        provider=config.provider,
        start_time=config.start_time,
        end_time=config.end_time,
        market_ids=config.market_ids,
    )
    if not records:
        raise ValueError("no historical prediction-market snapshots matched the requested range")

    grouped = _group_history_records(records, max_markets=config.max_markets)
    scanners = _build_scanners(config.scanners, min_edge_bps=config.min_edge_bps)
    threshold = ProfitThresholdChecker(
        ExecutionThresholdConfig(
            min_edge_bps=config.min_edge_bps,
            max_capital_per_leg=config.capital_limit,
            max_legs=config.max_legs,
        )
    )
    matcher = SnapshotMatchingEngine(
        fee_bps=config.fee_bps,
        display_size_multiplier=config.display_size_multiplier,
        capital_limit=config.capital_limit,
    )

    opportunities: list[SnapshotOpportunity] = []
    simulated_trades: list[SimulatedTrade] = []
    daily_opportunities: dict[str, int] = defaultdict(int)
    daily_trade_counts: dict[str, int] = defaultdict(int)
    daily_profit: dict[str, float] = defaultdict(float)

    for timestamp_utc in sorted(grouped):
        provider_view = _HistoricalSnapshotProvider(grouped[timestamp_utc])
        candidates = scan_market(
            provider=provider_view,
            scanners=scanners,
            max_markets=config.max_markets,
        )
        for candidate in candidates:
            if not threshold.is_allowed(candidate):
                continue
            opportunities.append(
                SnapshotOpportunity(
                    timestamp_utc=timestamp_utc,
                    market_id=candidate.market_id,
                    condition_id=candidate.condition_id,
                    scanner_id=candidate.scanner_id,
                    direction=candidate.direction,
                    edge_bps=candidate.edge_bps,
                    description=candidate.description,
                )
            )
            date_key = timestamp_utc[:10]
            daily_opportunities[date_key] += 1
            snapshot_market = provider_view.market_map[candidate.market_id]
            trade = matcher.simulate(
                timestamp_utc=timestamp_utc,
                candidate=candidate,
                market=snapshot_market.market,
                order_books=snapshot_market.order_books,
            )
            if trade is None:
                continue
            simulated_trades.append(trade)
            daily_trade_counts[date_key] += 1
            daily_profit[date_key] += trade.estimated_profit

    daily_summary = _build_daily_summary(
        daily_opportunities=daily_opportunities,
        daily_trade_counts=daily_trade_counts,
        daily_profit=daily_profit,
    )
    equity_curve = _build_equity_curve(simulated_trades)
    sensitivity = _build_sensitivity(opportunities, simulated_trades, config)
    profit_values = [item.estimated_profit for item in simulated_trades]
    cumulative_profit = sum(profit_values)
    edge_values = [item.edge_bps for item in opportunities]
    metrics = PredictionMarketTimeseriesMetrics(
        provider=config.provider,
        market_count=len({record.market_id for record in records}),
        snapshot_count=len(grouped),
        market_snapshot_count=sum(len(markets) for markets in grouped.values()),
        opportunity_count=len(opportunities),
        simulated_trade_count=len(simulated_trades),
        trigger_rate=(
            len(opportunities) / sum(len(markets) for markets in grouped.values())
            if grouped
            else 0.0
        ),
        mean_edge_bps=mean(edge_values) if edge_values else 0.0,
        median_edge_bps=median(edge_values) if edge_values else 0.0,
        max_edge_bps=max(edge_values, default=0.0),
        cumulative_estimated_profit=cumulative_profit,
        max_drawdown=_max_drawdown([point.cumulative_estimated_profit for point in equity_curve]),
        daily_volatility_proxy=pstdev([item.estimated_profit for item in daily_summary])
        if len(daily_summary) > 1
        else 0.0,
    )
    return PredictionMarketTimeseriesBacktestResult(
        config=config,
        metrics=metrics,
        opportunities=opportunities,
        simulated_trades=simulated_trades,
        daily_summary=daily_summary,
        equity_curve=equity_curve,
        sensitivity=sensitivity,
        assumptions=[
            "This is a read-only historical quasi-backtest based on stored order-book snapshots.",
            "Simulated fills assume immediate execution at displayed best bid/ask prices.",
            (
                "Per-leg size is capped by displayed top-of-book size "
                "multiplied by the configured size multiplier."
            ),
            (
                "Latency, legging risk, settlement, resolution risk, "
                "and exchange-specific fees are not fully modeled."
            ),
            (
                "Overpriced complete-set opportunities assume a hypothetical "
                "synthetic short at best bid only for research comparison."
            ),
        ],
    )


def _group_history_records(
    records: list[HistoricalSnapshotRecord],
    *,
    max_markets: int,
) -> dict[str, dict[str, _SnapshotMarket]]:
    grouped: dict[str, dict[str, _SnapshotMarket]] = {}
    for record in records:
        timestamp_group = grouped.setdefault(record.timestamp_utc, {})
        if len(timestamp_group) >= max_markets and record.market_id not in timestamp_group:
            continue
        snapshot_market = timestamp_group.setdefault(
            record.market_id,
            _SnapshotMarket(market=record.market, order_books=[]),
        )
        snapshot_market.order_books.append(record.order_book)
    return grouped


def _build_scanners(
    scanner_ids: list[str],
    *,
    min_edge_bps: float,
) -> list[MispricingScanner]:
    scanners: list[MispricingScanner] = []
    for scanner_id in scanner_ids:
        if scanner_id == "yes_no_arbitrage":
            scanners.append(YesNoArbitrageScanner(min_edge_bps=min_edge_bps))
        elif scanner_id == "outcome_set_consistency":
            scanners.append(OutcomeSetConsistencyScanner(min_edge_bps=min_edge_bps))
    if not scanners:
        raise ValueError("at least one scanner must be selected")
    return scanners


def _build_daily_summary(
    *,
    daily_opportunities: dict[str, int],
    daily_trade_counts: dict[str, int],
    daily_profit: dict[str, float],
) -> list[DailyOpportunitySummary]:
    dates = sorted(set(daily_opportunities) | set(daily_trade_counts) | set(daily_profit))
    return [
        DailyOpportunitySummary(
            date=date,
            opportunity_count=daily_opportunities.get(date, 0),
            simulated_trade_count=daily_trade_counts.get(date, 0),
            estimated_profit=daily_profit.get(date, 0.0),
        )
        for date in dates
    ]


def _build_equity_curve(trades: list[SimulatedTrade]) -> list[EquityCurvePoint]:
    cumulative = 0.0
    points: list[EquityCurvePoint] = []
    for trade in trades:
        cumulative += trade.estimated_profit
        points.append(
            EquityCurvePoint(
                timestamp_utc=trade.timestamp_utc,
                cumulative_estimated_profit=cumulative,
            )
        )
    return points


def _build_sensitivity(
    opportunities: list[SnapshotOpportunity],
    simulated_trades: list[SimulatedTrade],
    config: PredictionMarketTimeseriesBacktestConfig,
) -> list[SensitivityPoint]:
    thresholds = [config.min_edge_bps * multiplier for multiplier in (0.5, 1.0, 1.5, 2.0)]
    sensitivity: list[SensitivityPoint] = []
    for threshold in thresholds:
        matching_opportunities = [item for item in opportunities if item.edge_bps >= threshold]
        matching_trades = [item for item in simulated_trades if item.edge_bps >= threshold]
        sensitivity.append(
            SensitivityPoint(
                min_edge_bps=threshold,
                opportunity_count=len(matching_opportunities),
                simulated_trade_count=len(matching_trades),
                cumulative_estimated_profit=sum(item.estimated_profit for item in matching_trades),
            )
        )
    return sensitivity


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak - value)
    return max_drawdown


class _HistoricalSnapshotProvider:
    def __init__(self, market_map: dict[str, _SnapshotMarket]) -> None:
        self.market_map = market_map

    def list_markets(self, limit: int | None = None) -> list[Market]:
        markets = [item.market for item in self.market_map.values()]
        return markets if limit is None else markets[:limit]

    def get_order_books(self, market_id: str) -> list[OrderBookSnapshot]:
        return self.market_map[market_id].order_books
