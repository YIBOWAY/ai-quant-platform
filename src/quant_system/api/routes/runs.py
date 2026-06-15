from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.schemas.runs import RecentRunsResponse
from quant_system.storage.runs_repository import (
    KIND_DIRS,
    _created_at_from_run_id,
    list_run_metadatas,
)

router = APIRouter()


def _sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    created_at = item.get("created_at")
    run_id = str(item.get("run_id", ""))
    if not created_at:
        created_at = _created_at_from_run_id(run_id)
    return (str(created_at or ""), str(item.get("kind", "")), run_id)


@router.get("/runs/recent", response_model=RecentRunsResponse)
def recent_runs(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    limit: int = Query(default=10, ge=1, le=100),
) -> dict:
    runs: list[dict[str, Any]] = []
    for kind, dirname in KIND_DIRS.items():
        root = api_runs_dir / dirname
        for metadata in list_run_metadatas(kind, root, settings):
            run_id = str(metadata.get("run_id", ""))
            if not run_id:
                continue
            created_at = metadata.get("created_at") or _created_at_from_run_id(run_id)
            runs.append(
                {
                    "kind": kind,
                    "run_id": run_id,
                    "source": metadata.get("source", "unknown"),
                    "created_at": created_at,
                    "summary": metadata,
                }
            )
    runs.sort(key=_sort_key, reverse=True)
    return {
        "total": len(runs),
        "generated_at": datetime.now(UTC).isoformat(),
        "runs": runs[:limit],
    }
