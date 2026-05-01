from __future__ import annotations

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.schemas.common import make_run_id, read_json, resolve_run_dir
from quant_system.api.schemas.prediction_market import (
    PredictionMarketDryArbitrageRequest,
    PredictionMarketScanRequest,
)
from quant_system.prediction_market.backtest import (
    PredictionMarketBacktestConfig,
    run_prediction_market_quasi_backtest,
)
from quant_system.prediction_market.charts import write_prediction_market_charts
from quant_system.prediction_market.data.polymarket_readonly import PolymarketProviderError
from quant_system.prediction_market.execution_threshold import (
    ExecutionThresholdConfig,
    ProfitThresholdChecker,
)
from quant_system.prediction_market.optimizer.greedy_stub import GreedyStub
from quant_system.prediction_market.pipeline import run_dry_arbitrage, scan_market
from quant_system.prediction_market.provider_factory import build_prediction_market_provider
from quant_system.prediction_market.reporting import (
    write_phase11_backtest_report,
    write_prediction_market_report,
)
from quant_system.prediction_market.storage import PredictionMarketSnapshotStore

router = APIRouter()


@router.get("/prediction-market/markets")
def prediction_market_markets(
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
    provider: str | None = None,
    limit: int = 50,
) -> dict:
    active_provider, provider_label = _build_provider_or_400(settings, provider)
    try:
        markets = (
            active_provider.list_markets(limit=limit)
            if provider_label == "polymarket"
            else active_provider.list_markets()
        )
    except PolymarketProviderError as exc:
        raise _provider_http_exception(exc) from exc
    markets = markets[:limit]
    store = PredictionMarketSnapshotStore(settings.prediction_market.polymarket_cache_dir)
    order_books = []
    for market in markets:
        try:
            market_books = active_provider.get_order_books(market.market_id)
        except PolymarketProviderError as exc:
            raise _provider_http_exception(exc) from exc
        order_books.extend(snapshot.model_dump(mode="json") for snapshot in market_books)
        store.write_snapshot(
            provider=provider_label,
            market=market,
            order_books=market_books,
            source_endpoint=provider_label,
        )
    return {
        "markets": [market.model_dump(mode="json") for market in markets],
        "order_books": order_books,
        "provider": provider_label,
    }


@router.post("/prediction-market/scan")
def prediction_market_scan(
    request: PredictionMarketScanRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    provider, provider_label = _build_provider_or_400(settings, request.provider)
    try:
        candidates = scan_market(provider=provider)
    except PolymarketProviderError as exc:
        raise _provider_http_exception(exc) from exc
    report_path = write_prediction_market_report(
        candidates=candidates,
        trades=[],
        output_dir=api_runs_dir,
    )
    return {
        "candidates": [_candidate_payload(candidate) for candidate in candidates],
        "report_path": str(report_path),
        "provider": provider_label,
    }


@router.post("/prediction-market/dry-arbitrage")
def prediction_market_dry_arbitrage(
    request: PredictionMarketDryArbitrageRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    provider, provider_label = _build_provider_or_400(settings, request.provider)
    threshold = ProfitThresholdChecker(
        ExecutionThresholdConfig(
            min_edge_bps=request.min_edge_bps,
            max_capital_per_leg=request.max_capital_per_leg,
            max_legs=request.max_legs,
        )
    )
    optimizer = GreedyStub(max_capital=request.max_capital_per_leg)
    try:
        trades = run_dry_arbitrage(
            provider=provider,
            optimizer=optimizer,
            threshold=threshold,
            output_dir=api_runs_dir,
        )
        candidates = scan_market(provider=provider)
    except PolymarketProviderError as exc:
        raise _provider_http_exception(exc) from exc
    report_path = write_prediction_market_report(
        candidates=candidates,
        trades=trades,
        output_dir=api_runs_dir,
    )
    return {
        "proposed_trades": [trade.model_dump(mode="json") for trade in trades],
        "report_path": str(report_path),
        "provider": provider_label,
    }


@router.post("/prediction-market/backtest")
def prediction_market_backtest(
    request: PredictionMarketScanRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    provider, provider_label = _build_provider_or_400(settings, request.provider)
    run_id = make_run_id("pm-backtest")
    run_dir = api_runs_dir / "prediction_market" / "backtests" / run_id
    try:
        result = run_prediction_market_quasi_backtest(
            provider=provider,
            config=PredictionMarketBacktestConfig(
                min_edge_bps=request.min_edge_bps,
                capital_limit=request.capital_limit or request.max_capital_per_leg,
                max_legs=request.max_legs,
                max_markets=request.max_markets,
                fee_bps=request.fee_bps,
            ),
        )
    except PolymarketProviderError as exc:
        raise _provider_http_exception(exc) from exc
    chart_index = write_prediction_market_charts(result=result, output_dir=run_dir)
    report_path = write_phase11_backtest_report(
        result=result,
        chart_index=chart_index,
        output_dir=run_dir,
        run_id=run_id,
        provider=provider_label,
    )
    return {
        "run_id": run_id,
        "provider": provider_label,
        "metrics": result.metrics.model_dump(mode="json"),
        "chart_index": chart_index,
        "report_path": str(report_path),
    }


@router.get("/prediction-market/results/{run_id}")
def prediction_market_result(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "prediction_market" / "backtests", run_id)
    result_path = run_dir / "result.json"
    if not result_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"prediction market result {run_id!r} not found",
        )
    return {
        "run_id": run_id,
        "result": read_json(result_path),
        "chart_index": read_json(run_dir / "chart_index.json"),
        "report_path": str(run_dir / "report.md"),
    }


def _reject_credentials(request: PredictionMarketScanRequest) -> None:
    if request.polymarket_api_key or _contains_credential_marker(request.extra):
        raise HTTPException(
            status_code=400,
            detail="Credential-like fields are not accepted by the Phase 11 read-only API",
        )


def _contains_credential_marker(payload) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if any(
                marker in key.lower()
                for marker in ("key", "secret", "token", "password", "private")
            ):
                return True
            if _contains_credential_marker(value):
                return True
    if isinstance(payload, list):
        return any(_contains_credential_marker(item) for item in payload)
    return False


def _build_provider_or_400(settings, requested: str | None):
    try:
        return build_prediction_market_provider(settings, requested=requested)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _provider_http_exception(exc: PolymarketProviderError) -> HTTPException:
    status_code = 504 if exc.code == "provider_timeout" else 502
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _candidate_payload(candidate) -> dict:
    payload = candidate.model_dump(mode="json")
    payload["candidate_id"] = candidate.candidate_id
    return payload
