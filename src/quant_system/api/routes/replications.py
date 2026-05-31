from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quant_system.api.dependencies import SettingsDep
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


@router.post("/replications/reversal-momentum/run")
def run_reversal_momentum_replication(
    request: ReversalMomentumRunRequest,
    settings: SettingsDep,
) -> dict:
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
    return result


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
