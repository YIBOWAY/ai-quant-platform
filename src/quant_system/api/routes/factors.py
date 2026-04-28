from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep
from quant_system.api.schemas.common import (
    make_run_id,
    read_parquet_records,
    resolve_run_dir,
)
from quant_system.api.schemas.factors import FactorRunRequest
from quant_system.factors.pipeline import run_sample_factor_research
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
) -> dict:
    run_id = make_run_id("factor")
    run_dir = api_runs_dir / "factors" / run_id
    result = run_sample_factor_research(
        symbols=request.symbols,
        start=request.start,
        end=request.end,
        output_dir=run_dir,
        lookback=request.lookback,
        quantiles=request.quantiles,
    )
    metadata = {
        "run_id": run_id,
        "row_count": result.row_count,
        "signal_count": result.signal_count,
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
    }
