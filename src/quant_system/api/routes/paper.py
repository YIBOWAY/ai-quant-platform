from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.schemas.common import make_run_id, read_parquet_records, resolve_run_dir
from quant_system.api.schemas.paper import PaperRunRequest
from quant_system.execution.pipeline import run_sample_paper_trading

router = APIRouter()


@router.post("/paper/run")
def run_paper(
    request: PaperRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    if settings.safety.kill_switch and not request.enable_kill_switch:
        raise HTTPException(
            status_code=409,
            detail="Global kill switch is enabled; API requests cannot disable the kill switch",
        )
    run_id = make_run_id("paper")
    run_dir = api_runs_dir / "paper" / run_id
    result = run_sample_paper_trading(
        symbols=request.symbols,
        start=request.start,
        end=request.end,
        output_dir=run_dir,
        initial_cash=request.initial_cash,
        kill_switch=request.enable_kill_switch,
        max_fill_ratio_per_tick=request.max_fill_ratio_per_tick,
    )
    metadata = {
        "run_id": run_id,
        "order_count": result.order_count,
        "trade_count": result.trade_count,
        "risk_breach_count": result.risk_breach_count,
        "final_equity": result.final_equity,
        "paths": {
            "orders": str(result.orders_path),
            "order_events": str(result.order_events_path),
            "trades": str(result.trades_path),
            "risk_breaches": str(result.risk_breaches_path),
            "report": str(result.report_path),
        },
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return metadata


@router.get("/paper")
def list_paper(api_runs_dir: ApiRunsDirDep) -> dict:
    root = api_runs_dir / "paper"
    paper_runs = []
    if root.exists():
        for metadata_path in sorted(root.glob("*/metadata.json")):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            paper_runs.append({"id": metadata["run_id"], "summary": metadata})
    return {"paper_runs": paper_runs}


@router.get("/paper/{run_id}")
def paper_detail(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "paper", run_id)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail=f"paper run {run_id!r} not found")
    return {
        "id": run_id,
        "metadata": json.loads(metadata_path.read_text(encoding="utf-8")),
        "orders": read_parquet_records(run_dir / "paper" / "orders.parquet"),
        "order_events": read_parquet_records(run_dir / "paper" / "order_events.parquet"),
        "trades": read_parquet_records(run_dir / "paper" / "trades.parquet"),
        "risk_breaches": read_parquet_records(run_dir / "paper" / "risk_breaches.parquet"),
    }
