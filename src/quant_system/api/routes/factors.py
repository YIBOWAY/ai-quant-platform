from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep, OutputDirDep, SettingsDep
from quant_system.api.errors import not_found_404, provider_unavailable_400
from quant_system.api.schemas.common import (
    make_run_id,
    read_parquet_records,
    resolve_run_dir,
)
from quant_system.api.schemas.factors import (
    FactorCatalogResponse,
    FactorLabResponse,
    FactorRunDetailResponse,
    FactorRunRequest,
    FactorRunResponse,
    FactorRunsResponse,
)
from quant_system.data.provider_factory import DataProviderUnavailableError
from quant_system.factors.lab import build_factor_lab_dashboard
from quant_system.factors.pipeline import run_factor_research
from quant_system.factors.registry import build_factor_registry
from quant_system.storage.runs_repository import list_run_metadatas, persist_run

router = APIRouter()

# Human-approved candidates live at the CLI's canonical output path (mirror of
# cli.py's --candidates-dir default). It is a fixed on-disk location, not the
# API output_dir, because HQA drives propose/approve through the CLI. Loading
# from here execs approved candidate source (SafetyGate + AST gated) and is
# reserved for this opt-in catalog view — never the resident trading path.
# Anchored on the repo root (this file: src/quant_system/api/routes/factors.py)
# so it does not silently fail closed under a non-repo-root CWD (F6).
_REPO_ROOT = Path(__file__).resolve().parents[4]
AGENT_CANDIDATES_DIR = _REPO_ROOT / "data" / "agent_run" / "agent" / "candidates"


@router.get("/factors", response_model=FactorCatalogResponse)
def list_factors(include_candidates: bool = False) -> dict:
    # Default: examples + promoted only (no candidate exec). Opt-in surfaces
    # human-approved candidates with origin="candidate"; pending candidates are
    # dropped by the SafetyGate inside the loader and never appear.
    registry = build_factor_registry(
        include_approved_candidates=include_candidates,
        candidates_dir=AGENT_CANDIDATES_DIR if include_candidates else None,
    )
    origins = registry.origins()
    return {
        "factors": [
            {
                **metadata.model_dump(mode="json"),
                "origin": origins[metadata.factor_id],
            }
            for metadata in registry.list_metadata()
        ]
    }


@router.post("/factors/run", response_model=FactorRunResponse)
def run_factor(
    request: FactorRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    run_id = make_run_id("factor")
    run_dir = api_runs_dir / "factors" / run_id
    try:
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
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc
    metadata = {
        "run_id": run_id,
        "source": result.source,
        "row_count": result.row_count,
        "signal_count": result.signal_count,
        "warnings": result.warnings,
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
    return persist_run(run_dir, "factor", metadata, settings=settings)



@router.get("/factors/runs", response_model=FactorRunsResponse)
def list_factor_runs(api_runs_dir: ApiRunsDirDep, settings: SettingsDep) -> dict:
    root = api_runs_dir / "factors"
    runs = [
        {
            "id": metadata["run_id"],
            "source": metadata.get("source", "sample"),
            "row_count": metadata.get("row_count", 0),
            "signal_count": metadata.get("signal_count", 0),
            "paths": metadata.get("paths", {}),
        }
        for metadata in list_run_metadatas("factor", root, settings)
    ]
    return {"runs": runs}


@router.get("/factors/lab", response_model=FactorLabResponse)
def factor_lab_dashboard(
    output_dir: OutputDirDep,
    settings: SettingsDep,
    provider: str = "sample",
    universe_id: str = "etf",
    symbol: str = "QQQ",
    benchmark_symbol: str = "QQQ",
    start: str = "2024-01-02",
    end: str = "2024-12-31",
    lookback: int = 20,
    force_refresh: bool = False,
) -> dict:
    try:
        return build_factor_lab_dashboard(
            settings=settings,
            output_dir=output_dir,
            provider=provider,
            universe_id=universe_id,
            symbol=symbol,
            benchmark_symbol=benchmark_symbol,
            start=start,
            end=end,
            lookback=lookback,
            force_refresh=force_refresh,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_factor_lab_request", "message": str(exc)},
        ) from exc
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc


@router.get("/factors/{run_id}", response_model=FactorRunDetailResponse)
def factor_detail(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "factors", run_id)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        raise not_found_404("factor_run", run_id)
    return {
        "run_id": run_id,
        "metadata": json.loads(metadata_path.read_text(encoding="utf-8")),
        "factor_results": read_parquet_records(run_dir / "factors" / "factor_results.parquet"),
        "signals": read_parquet_records(run_dir / "factors" / "factor_signals.parquet"),
        "information_coefficients": read_parquet_records(run_dir / "factors" / "factor_ic.parquet"),
        "quantile_returns": read_parquet_records(run_dir / "factors" / "quantile_returns.parquet"),
    }
