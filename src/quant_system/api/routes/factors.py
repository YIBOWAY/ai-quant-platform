from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.schemas.common import (
    make_run_id,
    read_parquet_records,
    resolve_run_dir,
    sorted_metadata_paths,
)
from quant_system.api.schemas.factors import FactorRunRequest
from quant_system.factors.pipeline import run_factor_research
from quant_system.factors.registry import build_default_factor_registry

router = APIRouter()


@router.get("/factors")
def list_factors() -> dict:
    registry = build_default_factor_registry()
    return {
        "factors": [
            metadata.model_dump(mode="json")
            for metadata in registry.list_metadata()
        ]
    }


@router.post("/factors/run")
def run_factor(
    request: FactorRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    run_id = make_run_id("factor")
    run_dir = api_runs_dir / "factors" / run_id
    result = run_factor_research(
        symbols=request.symbols,
        start=request.start,
        end=request.end,
        output_dir=run_dir,
        lookback=request.lookback,
        quantiles=request.quantiles,
        provider=request.provider,
        settings=settings,
    )
    metadata = {
        "run_id": run_id,
        "source": result.source,
        "row_count": result.row_count,
        "signal_count": result.signal_count,
        "request": {
            "symbols": request.symbols,
            "start": request.start,
            "end": request.end,
            "provider": request.provider,
            "lookback": request.lookback,
            "quantiles": request.quantiles,
        },
        "paths": {
            "factor_results": str(result.factor_results_path),
            "signals": str(result.signal_frame_path),
            "ic": str(result.ic_path),
            "quantiles": str(result.quantile_returns_path),
            "report": str(result.report_path),
        },
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return metadata


@router.get("/factors/runs")
def list_factor_runs(api_runs_dir: ApiRunsDirDep) -> dict:
    root = api_runs_dir / "factors"
    runs = []
    for metadata_path in sorted_metadata_paths(root):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        runs.append(
            {
                "id": metadata["run_id"],
                "source": metadata.get("source", "sample"),
                "row_count": metadata.get("row_count", 0),
                "signal_count": metadata.get("signal_count", 0),
                "paths": metadata.get("paths", {}),
            }
        )
    return {"runs": runs}


@router.get("/factors/{run_id}")
def factor_detail(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "factors", run_id)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail=f"factor run {run_id!r} not found")
    return {
        "run_id": run_id,
        "metadata": json.loads(metadata_path.read_text(encoding="utf-8")),
        "factor_results": read_parquet_records(run_dir / "factors" / "factor_results.parquet"),
        "signals": read_parquet_records(run_dir / "factors" / "factor_signals.parquet"),
        "information_coefficients": read_parquet_records(run_dir / "factors" / "factor_ic.parquet"),
        "quantile_returns": read_parquet_records(run_dir / "factors" / "quantile_returns.parquet"),
    }
