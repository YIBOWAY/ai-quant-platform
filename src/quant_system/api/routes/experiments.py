from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import OutputDirDep
from quant_system.api.schemas.common import read_json, read_parquet_records, resolve_run_dir

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
