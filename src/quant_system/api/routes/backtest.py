from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from quant_system.api.dependencies import ApiRunsDirDep, BacktestJobRunnerDep, SettingsDep
from quant_system.api.errors import not_found_404, provider_unavailable_400
from quant_system.api.jobs.backtest_jobs import execute_backtest_run
from quant_system.api.schemas.backtest import (
    BacktestDetailResponse,
    BacktestJobStateResponse,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestsResponse,
)
from quant_system.api.schemas.common import (
    RunStatus,
    make_run_id,
    read_json,
    read_parquet_records,
    resolve_run_dir,
)
from quant_system.data.provider_factory import DataProviderUnavailableError
from quant_system.storage.runs_repository import list_run_metadatas, persist_run

router = APIRouter()


@router.post(
    "/backtests/run",
    response_model=BacktestRunResponse,
    status_code=status.HTTP_200_OK,
    responses={status.HTTP_202_ACCEPTED: {"model": BacktestJobStateResponse}},
)
def run_backtest(
    request: BacktestRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    backtest_job_runner: BacktestJobRunnerDep,
) -> dict | JSONResponse:
    if settings.backtest_jobs.enabled:
        try:
            payload = backtest_job_runner.submit(request)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail={"code": "backtest_job_runner_unavailable", "message": str(exc)},
            ) from exc
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)

    run_id = make_run_id("backtest")
    run_dir = api_runs_dir / "backtests" / run_id
    try:
        metadata = execute_backtest_run(
            request=request,
            run_id=run_id,
            run_dir=run_dir,
            settings=settings,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_backtest_request", "message": str(exc)},
        ) from exc
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc
    return persist_run(run_dir, "backtest", metadata, settings=settings)


def _is_completed_backtest_metadata(metadata: dict) -> bool:
    return metadata.get("status", RunStatus.COMPLETED.value) == RunStatus.COMPLETED.value


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
        if _is_completed_backtest_metadata(metadata)
    ]
    return {"backtests": backtests}


@router.get("/backtests/jobs/{run_id}", response_model=BacktestJobStateResponse)
def backtest_job(run_id: str, backtest_job_runner: BacktestJobRunnerDep) -> dict:
    try:
        return backtest_job_runner.status(run_id)
    except FileNotFoundError as exc:
        raise not_found_404("backtest job", run_id) from exc


@router.post("/backtests/jobs/{run_id}/cancel", response_model=BacktestJobStateResponse)
def cancel_backtest_job(run_id: str, backtest_job_runner: BacktestJobRunnerDep) -> dict:
    try:
        return backtest_job_runner.cancel(run_id)
    except FileNotFoundError as exc:
        raise not_found_404("backtest job", run_id) from exc


@router.get("/backtests/{run_id}", response_model=BacktestDetailResponse)
def backtest_detail(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "backtests", run_id)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        raise not_found_404("backtest", run_id)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not _is_completed_backtest_metadata(metadata):
        raise HTTPException(
            status_code=409,
            detail={"code": "backtest_not_completed", "status": metadata.get("status")},
        )
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
