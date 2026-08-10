from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.asia_radar import AsiaRadarOverviewResponse
from quant_system.data.price_history import HistoricalPriceReadError
from quant_system.factors.asia_radar import read_asia_radar_overview

router = APIRouter()
AsiaRadarReader = Callable[..., dict[str, Any]]


def get_asia_radar_reader() -> AsiaRadarReader:
    return read_asia_radar_overview


AsiaRadarReaderDep = Annotated[AsiaRadarReader, Depends(get_asia_radar_reader)]


@router.get("/asia-radar/overview", response_model=AsiaRadarOverviewResponse)
def asia_radar_overview(
    settings: SettingsDep,
    reader: AsiaRadarReaderDep,
    provider: str = Query(default="futu"),
) -> dict[str, Any]:
    if provider != "futu":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "asia_radar_requires_futu",
                "provider": provider,
                "message": "Asia Radar requires provider=futu",
            },
        )
    try:
        return reader(settings=settings)
    except HistoricalPriceReadError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "asia_radar_provider_unavailable",
                "provider": "futu",
                "provider_code": exc.provider_code or exc.code,
                "message": exc.message,
            },
        ) from exc
