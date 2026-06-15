from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import OutputDirDep, SettingsDep
from quant_system.api.errors import provider_unavailable_400
from quant_system.api.schemas.common import read_json, read_parquet_records, resolve_run_dir
from quant_system.api.schemas.experiments import ExperimentRunRequest
from quant_system.data.provider_factory import (
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.experiments.runner import run_sample_experiment

router = APIRouter()


@router.get("/experiments")
def list_experiments(output_dir: OutputDirDep) -> dict:
    root = output_dir / "experiments"
    experiments = []
    if root.exists():
        for path in sorted(
            (item for item in root.iterdir() if item.is_dir()),
            key=lambda item: (item.stat().st_mtime_ns, item.name),
            reverse=True,
        ):
            agent_summary = _read_optional_json(path / "agent_summary.json")
            experiments.append(
                {
                    "id": path.name,
                    "path": str(path),
                    "best_run_id": agent_summary.get("best_run_id"),
                    "created_at": agent_summary.get("created_at"),
                }
            )
    return {"experiments": experiments}


@router.post("/experiments/run")
def run_experiment(
    request: ExperimentRunRequest,
    output_dir: OutputDirDep,
    settings: SettingsDep,
) -> dict:
    try:
        provider, source = build_ohlcv_provider(settings, requested=request.provider)
        result = run_sample_experiment(
            symbols=request.symbols,
            start=request.start,
            end=request.end,
            lookbacks=request.lookbacks,
            top_ns=request.top_ns,
            output_dir=output_dir,
            initial_cash=request.initial_cash,
            commission_bps=request.commission_bps,
            slippage_bps=request.slippage_bps,
            rebalance_every_n_bars=request.rebalance_every_n_bars,
            provider=provider,
            data_source=source,
            walk_forward=request.walk_forward,
        )
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "experiment_run_failed", "message": str(exc)},
        ) from exc
    experiment_id = result.config_path.parent.name
    return {
        "experiment_id": experiment_id,
        "raw_experiment_id": result.experiment_id,
        "provider": request.provider,
        "source": result.data_source,
        "run_count": result.run_count,
        "best_run_id": result.best_run_id,
        "paths": {
            "config": str(result.config_path),
            "runs": str(result.runs_path),
            "folds": str(result.folds_path),
            "agent_summary": str(result.agent_summary_path),
            "report": str(result.report_path),
        },
    }


@router.get("/experiments/{experiment_id}")
def experiment_detail(experiment_id: str, output_dir: OutputDirDep) -> dict:
    experiment_dir = resolve_run_dir(output_dir / "experiments", experiment_id)
    if not experiment_dir.exists():
        raise HTTPException(status_code=404, detail=f"experiment {experiment_id!r} not found")
    payload: dict = {"id": experiment_id, "path": str(experiment_dir)}
    for name in ["experiment_config.json", "agent_summary.json"]:
        path = experiment_dir / name
        if path.exists():
            payload[name.removesuffix(".json")] = read_json(path)
    artifact_frames = {
        "runs": ["experiment_runs.parquet", "runs.parquet"],
        "folds": ["walk_forward_folds.parquet", "folds.parquet"],
    }
    for payload_key, names in artifact_frames.items():
        path = _first_existing(experiment_dir, names)
        if path:
            payload[payload_key] = read_parquet_records(path)
    if (experiment_dir / "metadata.json").exists():
        payload["metadata"] = json.loads((experiment_dir / "metadata.json").read_text("utf-8"))
    return payload


def _read_optional_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return read_json(path)


def _first_existing(root: Path, names: list[str]) -> Path | None:
    for name in names:
        path = root / name
        if path.exists():
            return path
    return None
