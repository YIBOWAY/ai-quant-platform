from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.schemas.common import make_run_id, read_json, resolve_run_dir
from quant_system.api.schemas.prediction_market import (
    PredictionMarketCollectRequest,
    PredictionMarketDryArbitrageRequest,
    PredictionMarketScanRequest,
    PredictionMarketTimeseriesBacktestRequest,
)
from quant_system.prediction_market.backtest import (
    PredictionMarketBacktestConfig,
    run_prediction_market_quasi_backtest,
)
from quant_system.prediction_market.charts import (
    write_prediction_market_charts,
    write_prediction_market_timeseries_charts,
)
from quant_system.prediction_market.collector import (
    PredictionMarketSnapshotCollector,
    ensure_no_polymarket_credentials_in_env,
    seed_sample_history_dataset,
)
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
    write_phase12_timeseries_report,
    write_prediction_market_report,
)
from quant_system.prediction_market.storage import PredictionMarketSnapshotStore
from quant_system.prediction_market.timeseries_backtest import (
    PredictionMarketTimeseriesBacktestConfig,
    run_prediction_market_timeseries_backtest,
)

router = APIRouter()


@router.get("/prediction-market/markets")
def prediction_market_markets(
    settings: SettingsDep,
    api_runs_dir: ApiRunsDirDep,
    provider: str | None = None,
    cache_mode: str = "prefer_cache",
    limit: int = 50,
) -> dict:
    active_provider, provider_label = _build_provider_or_400(
        settings,
        provider,
        cache_mode=cache_mode,
    )
    try:
        markets = active_provider.list_markets(limit=limit)
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
        "cache_status": getattr(active_provider, "last_cache_status", "live"),
    }


@router.post("/prediction-market/scan")
def prediction_market_scan(
    request: PredictionMarketScanRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    provider, provider_label = _build_provider_or_400(
        settings,
        request.provider,
        cache_mode=request.cache_mode,
    )
    try:
        candidates = scan_market(provider=provider, max_markets=request.max_markets)
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
        "cache_status": getattr(provider, "last_cache_status", "live"),
    }


@router.post("/prediction-market/collect")
def prediction_market_collect(
    request: PredictionMarketCollectRequest,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    try:
        ensure_no_polymarket_credentials_in_env()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    provider, provider_label = _build_provider_or_400(
        settings,
        request.provider,
        cache_mode=request.cache_mode,
    )
    store = PredictionMarketSnapshotStore(settings.prediction_market.history_dir)
    collector = PredictionMarketSnapshotCollector(
        provider=provider,
        provider_label=provider_label,
        store=store,
        interval_seconds=(
            request.interval_seconds
            or settings.prediction_market.collector_default_interval_seconds
        ),
        duration_seconds=request.duration_seconds,
        market_ids=request.market_ids,
        limit=request.limit,
    )
    try:
        summary = collector.run()
    except PolymarketProviderError as exc:
        raise _provider_http_exception(exc) from exc
    return {
        "provider": provider_label,
        "iteration_count": summary.iteration_count,
        "market_count": summary.market_count,
        "snapshot_record_count": summary.snapshot_record_count,
        "history_dir": str(summary.output_root),
        "first_timestamp": summary.first_timestamp,
        "last_timestamp": summary.last_timestamp,
        "cache_status": getattr(provider, "last_cache_status", "live"),
    }


@router.post("/prediction-market/dry-arbitrage")
def prediction_market_dry_arbitrage(
    request: PredictionMarketDryArbitrageRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    provider, provider_label = _build_provider_or_400(
        settings,
        request.provider,
        cache_mode=request.cache_mode,
    )
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
            max_markets=request.max_markets,
        )
        candidates = scan_market(provider=provider, max_markets=request.max_markets)
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
        "cache_status": getattr(provider, "last_cache_status", "live"),
    }


@router.post("/prediction-market/backtest")
def prediction_market_backtest(
    request: PredictionMarketScanRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    provider, provider_label = _build_provider_or_400(
        settings,
        request.provider,
        cache_mode=request.cache_mode,
    )
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
                history_interval=request.history_interval,
                history_fidelity=request.history_fidelity,
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
        "cache_status": getattr(provider, "last_cache_status", "live"),
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


@router.post("/prediction-market/timeseries-backtest")
def prediction_market_timeseries_backtest(
    request: PredictionMarketTimeseriesBacktestRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    _reject_credentials(request)
    if request.provider == "sample":
        _ensure_sample_history_exists(settings)
    store = PredictionMarketSnapshotStore(settings.prediction_market.history_dir)
    run_id = make_run_id("pm-timeseries")
    run_dir = api_runs_dir / "prediction_market" / "timeseries_backtests" / run_id
    try:
        result = run_prediction_market_timeseries_backtest(
            store=store,
            config=PredictionMarketTimeseriesBacktestConfig(
                provider=request.provider,
                start_time=request.start_time,
                end_time=request.end_time,
                scanners=request.scanners,
                min_edge_bps=request.min_edge_bps,
                capital_limit=request.capital_limit,
                max_legs=request.max_legs,
                max_markets=request.max_markets,
                fee_bps=(
                    request.fee_bps
                    if request.fee_bps is not None
                    else settings.prediction_market.backtest_default_fee_bps
                ),
                display_size_multiplier=request.display_size_multiplier,
                market_ids=request.market_ids,
            ),
        )
    except ValueError as exc:
        status_code = 404 if "no historical" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    chart_index = write_prediction_market_timeseries_charts(
        result=result,
        output_dir=run_dir,
    )
    chart_index = _attach_artifact_urls(
        chart_index,
        run_id=run_id,
        route_root="/api/prediction-market/timeseries-backtest",
    )
    report_path = write_phase12_timeseries_report(
        result=result,
        chart_index=chart_index,
        output_dir=run_dir,
        run_id=run_id,
    )
    return {
        "run_id": run_id,
        "provider": request.provider,
        "metrics": result.metrics.model_dump(mode="json"),
        "chart_index": chart_index,
        "report_path": str(report_path),
        "report_url": (
            f"/api/prediction-market/timeseries-backtest/{run_id}/artifacts/report.md"
        ),
        "history_dir": str(settings.prediction_market.history_dir),
    }


@router.get("/prediction-market/timeseries-backtest/{run_id}")
def prediction_market_timeseries_backtest_result(
    run_id: str,
    api_runs_dir: ApiRunsDirDep,
) -> dict:
    run_dir = resolve_run_dir(
        api_runs_dir / "prediction_market" / "timeseries_backtests",
        run_id,
    )
    result_path = run_dir / "result.json"
    if not result_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"prediction market timeseries result {run_id!r} not found",
        )
    chart_index = _attach_artifact_urls(
        read_json(run_dir / "chart_index.json"),
        run_id=run_id,
        route_root="/api/prediction-market/timeseries-backtest",
    )
    return {
        "run_id": run_id,
        "result": read_json(result_path),
        "chart_index": chart_index,
        "report_path": str(run_dir / "report.md"),
        "report_url": (
            f"/api/prediction-market/timeseries-backtest/{run_id}/artifacts/report.md"
        ),
    }


@router.get("/prediction-market/timeseries-backtest/{run_id}/artifacts/{artifact_name}")
def prediction_market_timeseries_artifact(
    run_id: str,
    artifact_name: str,
    api_runs_dir: ApiRunsDirDep,
) -> FileResponse:
    run_dir = resolve_run_dir(
        api_runs_dir / "prediction_market" / "timeseries_backtests",
        run_id,
    )
    candidate = (run_dir / artifact_name).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(candidate)


def _reject_credentials(request) -> None:
    if getattr(request, "polymarket_api_key", None) or _contains_credential_marker(
        getattr(request, "extra", {})
    ):
        raise HTTPException(
            status_code=400,
            detail="Credential-like fields are not accepted by the read-only prediction-market API",
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


def _build_provider_or_400(settings, requested: str | None, *, cache_mode: str | None = None):
    try:
        return build_prediction_market_provider(
            settings,
            requested=requested,
            cache_mode=cache_mode,
        )
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


def _ensure_sample_history_exists(settings) -> None:
    store = PredictionMarketSnapshotStore(settings.prediction_market.history_dir)
    existing = store.load_history_records(provider="sample")
    if not existing:
        seed_sample_history_dataset(settings.prediction_market.history_dir)


def _attach_artifact_urls(chart_index: dict, *, run_id: str, route_root: str) -> dict:
    charts = []
    for chart in chart_index.get("charts", []):
        payload = dict(chart)
        payload["url"] = f"{route_root}/{run_id}/artifacts/{payload['path']}"
        charts.append(payload)
    return {"charts": charts}
