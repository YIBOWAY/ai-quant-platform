from __future__ import annotations

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep
from quant_system.api.schemas.prediction_market import (
    PredictionMarketDryArbitrageRequest,
    PredictionMarketScanRequest,
)
from quant_system.prediction_market.data.sample_provider import SamplePredictionMarketProvider
from quant_system.prediction_market.execution_threshold import (
    ExecutionThresholdConfig,
    ProfitThresholdChecker,
)
from quant_system.prediction_market.optimizer.greedy_stub import GreedyStub
from quant_system.prediction_market.pipeline import run_dry_arbitrage, scan_market
from quant_system.prediction_market.reporting import write_prediction_market_report

router = APIRouter()


@router.get("/prediction-market/markets")
def prediction_market_markets() -> dict:
    provider = SamplePredictionMarketProvider()
    markets = provider.list_markets()
    order_books = [
        snapshot.model_dump(mode="json")
        for market in markets
        for snapshot in provider.get_order_books(market.market_id)
    ]
    return {
        "markets": [market.model_dump(mode="json") for market in markets],
        "order_books": order_books,
        "provider": "sample",
    }


@router.post("/prediction-market/scan")
def prediction_market_scan(
    request: PredictionMarketScanRequest,
    api_runs_dir: ApiRunsDirDep,
) -> dict:
    _reject_live_key(request.polymarket_api_key)
    provider = SamplePredictionMarketProvider()
    candidates = scan_market(provider=provider)
    report_path = write_prediction_market_report(
        candidates=candidates,
        trades=[],
        output_dir=api_runs_dir,
    )
    return {
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
        "report_path": str(report_path),
    }


@router.post("/prediction-market/dry-arbitrage")
def prediction_market_dry_arbitrage(
    request: PredictionMarketDryArbitrageRequest,
    api_runs_dir: ApiRunsDirDep,
) -> dict:
    _reject_live_key(request.polymarket_api_key)
    provider = SamplePredictionMarketProvider()
    threshold = ProfitThresholdChecker(
        ExecutionThresholdConfig(
            min_edge_bps=request.min_edge_bps,
            max_capital_per_leg=request.max_capital_per_leg,
            max_legs=request.max_legs,
        )
    )
    optimizer = GreedyStub(max_capital=request.max_capital_per_leg)
    trades = run_dry_arbitrage(
        provider=provider,
        optimizer=optimizer,
        threshold=threshold,
        output_dir=api_runs_dir,
    )
    candidates = scan_market(provider=provider)
    report_path = write_prediction_market_report(
        candidates=candidates,
        trades=trades,
        output_dir=api_runs_dir,
    )
    return {
        "proposed_trades": [trade.model_dump(mode="json") for trade in trades],
        "report_path": str(report_path),
    }


def _reject_live_key(polymarket_api_key: str | None) -> None:
    if polymarket_api_key:
        raise HTTPException(
            status_code=400,
            detail="Polymarket API key is not accepted by the Phase 9 read-only API",
        )


def _candidate_payload(candidate) -> dict:
    payload = candidate.model_dump(mode="json")
    payload["candidate_id"] = candidate.candidate_id
    return payload
