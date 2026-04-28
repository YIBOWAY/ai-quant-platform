from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import OutputDirDep
from quant_system.api.schemas.common import read_json, read_parquet_records, resolve_run_dir

router = APIRouter()


@router.get("/experiments")
def list_experiments(output_dir: OutputDirDep) -> dict:
    root = output_dir / "experiments"
    experiments = []
    if root.exists():
        for path in sorted(root.iterdir()):
            if path.is_dir():
                experiments.append({"id": path.name, "path": str(path)})
    return {"experiments": experiments}


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
    for name in ["runs.parquet", "folds.parquet"]:
        path = experiment_dir / name
        if path.exists():
            payload[name.removesuffix(".parquet")] = read_parquet_records(path)
    if (experiment_dir / "metadata.json").exists():
        payload["metadata"] = json.loads((experiment_dir / "metadata.json").read_text("utf-8"))
    return payload
