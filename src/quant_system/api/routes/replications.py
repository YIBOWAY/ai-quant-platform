from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.schemas.common import make_run_id, read_json, resolve_run_dir
from quant_system.api.schemas.replications import (
    ReversalMomentumReplicationDetailResponse,
    ReversalMomentumReplicationRunResponse,
)
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.data.providers.futu import FutuProviderError
from quant_system.replication.reversal_momentum import build_reversal_momentum_replication

router = APIRouter()


class ReversalMomentumRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list, min_length=2, max_length=50)
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"] | None = None
    top_n: int | None = Field(default=None, ge=1, le=10)
    initial_cash: float = Field(default=1.0, gt=0)


@router.post(
    "/replications/reversal-momentum/run",
    response_model=ReversalMomentumReplicationRunResponse,
)
def run_reversal_momentum_replication(
    request: ReversalMomentumRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    run_id = make_run_id("replication")
    run_dir = api_runs_dir / "replications" / run_id
    symbols = [symbol.strip().upper() for symbol in request.symbols if symbol.strip()]
    provider, source = build_ohlcv_provider(settings, requested=request.provider)
    try:
        ohlcv = provider.fetch_ohlcv(symbols, start=request.start, end=request.end, interval="1d")
    except FutuProviderError as exc:
        raise HTTPException(
            status_code=_status_for_futu_error(exc.code),
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "replication_provider_failed",
                "message": f"{source} provider failed: {exc.__class__.__name__}",
            },
        ) from exc

    result = build_reversal_momentum_replication(
        ohlcv,
        initial_cash=request.initial_cash,
        top_n=request.top_n,
    )
    result.update(
        {
            "run_id": run_id,
            "result_type": "replication",
            "source": source,
            "request": {
                "symbols": symbols,
                "start": request.start,
                "end": request.end,
                "provider": request.provider or settings.data.default_data_provider,
                "top_n": request.top_n,
                "initial_cash": request.initial_cash,
            },
        }
    )
    result_path = run_dir / "result.json"
    metadata_path = run_dir / "metadata.json"
    paths = {
        "metadata": str(metadata_path),
        "result": str(result_path),
    }
    result["paths"] = paths
    result["artifact_path"] = str(run_dir)
    metadata = {
        "run_id": run_id,
        "result_type": "replication",
        "source": source,
        "request": result["request"],
        "metrics": result.get("metrics", {}),
        "diagnostics": result.get("diagnostics", {}),
        "warnings": result.get("warnings", []),
        "paths": paths,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return result


@router.get(
    "/replications/reversal-momentum/{run_id}",
    response_model=ReversalMomentumReplicationDetailResponse,
)
def reversal_momentum_replication_detail(
    run_id: str,
    api_runs_dir: ApiRunsDirDep,
) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "replications", run_id)
    metadata_path = run_dir / "metadata.json"
    result_path = run_dir / "result.json"
    if not metadata_path.exists() or not result_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"reversal momentum replication {run_id!r} not found",
        )
    return {
        "run_id": run_id,
        "metadata": read_json(metadata_path),
        "result": read_json(result_path),
    }


def _status_for_futu_error(code: str) -> int:
    if code in {"opend_unavailable", "provider_timeout", "rate_limited"}:
        return 503
    if code in {"invalid_symbol", "unsupported_interval"}:
        return 400
    if code == "permission_denied":
        return 403
    if code == "no_data":
        return 404
    return 502
