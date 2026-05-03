from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.schemas.backtest import BacktestRunRequest
from quant_system.api.schemas.common import (
    make_run_id,
    read_json,
    read_parquet_records,
    resolve_run_dir,
    sorted_metadata_paths,
)
from quant_system.backtest.pipeline import run_backtest as execute_backtest

router = APIRouter()


@router.post("/backtests/run")
def run_backtest(
    request: BacktestRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    run_id = make_run_id("backtest")
    run_dir = api_runs_dir / "backtests" / run_id
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
        provider=request.provider,
        settings=settings,
    )
    metadata = {
        "run_id": run_id,
        "source": result.source,
        "request": {
            "symbols": request.symbols,
            "start": request.start,
            "end": request.end,
            "provider": request.provider,
            "lookback": request.lookback,
            "top_n": request.top_n,
            "initial_cash": request.initial_cash,
            "commission_bps": request.commission_bps,
            "slippage_bps": request.slippage_bps,
        },
        "metrics": {
            "total_return": result.total_return,
            "sharpe": result.sharpe,
            "max_drawdown": result.max_drawdown,
        },
        "paths": {
            "equity_curve": str(result.equity_curve_path),
            "trade_blotter": str(result.trade_blotter_path),
            "orders": str(result.orders_path),
            "positions": str(result.positions_path),
            "metrics": str(result.metrics_path),
            "report": str(result.report_path),
        },
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return metadata


@router.get("/backtests")
def list_backtests(api_runs_dir: ApiRunsDirDep) -> dict:
    root = api_runs_dir / "backtests"
    backtests = []
    for metadata_path in sorted_metadata_paths(root):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        backtests.append(
            {
                "id": metadata["run_id"],
                "source": metadata.get("source", "sample"),
                "metrics": metadata.get("metrics", {}),
            }
        )
    return {"backtests": backtests}


@router.get("/backtests/{run_id}")
def backtest_detail(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "backtests", run_id)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail=f"backtest {run_id!r} not found")
    return {
        "id": run_id,
        "metadata": json.loads(metadata_path.read_text(encoding="utf-8")),
        "metrics": read_json(run_dir / "backtests" / "metrics.json"),
        "equity_curve": read_parquet_records(run_dir / "backtests" / "equity_curve.parquet"),
        "orders": read_parquet_records(run_dir / "backtests" / "orders.parquet"),
        "positions": read_parquet_records(run_dir / "backtests" / "positions.parquet"),
        "trade_blotter": read_parquet_records(run_dir / "backtests" / "trade_blotter.parquet"),
    }
