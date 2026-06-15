from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.errors import provider_unavailable_400
from quant_system.api.schemas.backtest import (
    BacktestDetailResponse,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestsResponse,
)
from quant_system.api.schemas.common import (
    make_run_id,
    read_json,
    read_parquet_records,
    resolve_run_dir,
)
from quant_system.backtest.pipeline import run_backtest as execute_backtest
from quant_system.data.provider_factory import DataProviderUnavailableError
from quant_system.storage.runs_repository import index_run, list_run_metadatas

router = APIRouter()


@router.post("/backtests/run", response_model=BacktestRunResponse)
def run_backtest(
    request: BacktestRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    run_id = make_run_id("backtest")
    run_dir = api_runs_dir / "backtests" / run_id
    try:
        result = execute_backtest(
            symbols=request.symbols,
            start=request.start,
            end=request.end,
            output_dir=run_dir,
            lookback=request.lookback,
            top_n=request.top_n,
            initial_cash=request.initial_cash,
            commission_bps=request.commission_bps,
            slippage_bps=request.slippage_bps,
            min_order_value=request.min_order_value,
            whole_share_orders=request.whole_share_orders,
            provider=request.provider,
            strategy_id=request.strategy_id,
            universe_id=request.universe_id,
            factor_ids=request.factor_ids,
            weights=request.weights,
            benchmark_symbol=request.benchmark_symbol,
            rebalance_frequency=request.rebalance_frequency,
            max_weight_per_symbol=request.max_weight_per_symbol,
            sector_cap=request.sector_cap,
            sector_map=request.sector_map,
            settings=settings,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_backtest_request", "message": str(exc)},
        ) from exc
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc
    metadata = {
        "run_id": run_id,
        "source": result.source,
        "trade_count": result.trade_count,
        "order_count": result.order_count,
        "warnings": result.warnings,
        "timings_ms": result.timings_ms,
        "request": {
            "symbols": result.symbols,
            "start": request.start,
            "end": request.end,
            "provider": request.provider,
            "strategy_id": result.strategy_id,
            "universe_id": result.universe_id,
            "factor_ids": result.factor_ids,
            "weights": result.weights,
            "benchmark_symbol": result.benchmark_symbol,
            "lookback": request.lookback,
            "top_n": request.top_n,
            "initial_cash": request.initial_cash,
            "commission_bps": request.commission_bps,
            "slippage_bps": request.slippage_bps,
            "min_order_value": request.min_order_value,
            "whole_share_orders": request.whole_share_orders,
            "rebalance_frequency": request.rebalance_frequency,
            "max_weight_per_symbol": request.max_weight_per_symbol,
            "sector_cap": request.sector_cap,
            "sector_map": request.sector_map,
        },
        "metrics": {
            "total_return": result.total_return,
            "sharpe": result.sharpe,
            "max_drawdown": result.max_drawdown,
        },
        "attribution": result.attribution,
        "benchmark": {
            "symbol": result.benchmark_symbol,
            "source": result.benchmark_source,
            "metrics": result.benchmark_metrics.model_dump(),
        },
        "paths": {
            "equity_curve": str(result.equity_curve_path),
            "trade_blotter": str(result.trade_blotter_path),
            "orders": str(result.orders_path),
            "positions": str(result.positions_path),
            "attribution": str(result.attribution_path),
            "metrics": str(result.metrics_path),
            "benchmark_curve": str(result.benchmark_curve_path),
            "benchmark_metrics": str(result.benchmark_metrics_path),
            "report": str(result.report_path),
        },
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    index_run("backtest", metadata, run_dir, settings)
    return metadata



@router.get("/backtests", response_model=BacktestsResponse)
def list_backtests(api_runs_dir: ApiRunsDirDep, settings: SettingsDep) -> dict:
    root = api_runs_dir / "backtests"
    backtests = [
        {
            "id": metadata["run_id"],
            "source": metadata.get("source", "sample"),
            "metrics": metadata.get("metrics", {}),
        }
        for metadata in list_run_metadatas("backtest", root, settings)
    ]
    return {"backtests": backtests}


@router.get("/backtests/{run_id}", response_model=BacktestDetailResponse)
def backtest_detail(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "backtests", run_id)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail=f"backtest {run_id!r} not found")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    benchmark_metadata = metadata.get("benchmark", {})
    request = metadata.get("request", {})
    benchmark_metrics = read_json_if_exists(run_dir / "backtests" / "benchmark_metrics.json")
    return {
        "id": run_id,
        "metadata": metadata,
        "metrics": read_json(run_dir / "backtests" / "metrics.json"),
        "equity_curve": read_parquet_records(run_dir / "backtests" / "equity_curve.parquet"),
        "benchmark": {
            "symbol": benchmark_metadata.get("symbol")
            or request.get("benchmark_symbol")
            or "SPY",
            "source": benchmark_metadata.get("source")
            or metadata.get("source")
            or "",
            "metrics": benchmark_metrics or benchmark_metadata.get("metrics", {}),
            "equity_curve": read_parquet_records(
                run_dir / "backtests" / "benchmark_curve.parquet"
            ),
        },
        "orders": read_parquet_records(run_dir / "backtests" / "orders.parquet"),
        "positions": read_parquet_records(run_dir / "backtests" / "positions.parquet"),
        "trade_blotter": read_parquet_records(run_dir / "backtests" / "trade_blotter.parquet"),
        "attribution": read_parquet_records(run_dir / "backtests" / "attribution.parquet"),
    }


def read_json_if_exists(path) -> dict:
    return read_json(path) if path.exists() else {}
