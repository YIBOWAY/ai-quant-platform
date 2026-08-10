from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.market_cross_section import MarketCrossSectionResponse
from quant_system.data.price_history import HistoricalPriceReadError
from quant_system.factors.market_cross_section import read_market_cross_section

router = APIRouter()
MarketCrossSectionReader = Callable[..., dict[str, Any]]


def get_market_cross_section_reader() -> MarketCrossSectionReader:
    return read_market_cross_section


MarketCrossSectionReaderDep = Annotated[
    MarketCrossSectionReader, Depends(get_market_cross_section_reader)
]


@router.get("/market-cross-section", response_model=MarketCrossSectionResponse)
def market_cross_section(
    settings: SettingsDep,
    reader: MarketCrossSectionReaderDep,
    provider: str = Query(default="futu"),
    basket: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
) -> dict[str, Any]:
    if provider != "futu":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "market_cross_section_requires_futu",
                "provider": provider,
                "message": "Market cross-section requires provider=futu",
            },
        )
    symbol_list = None
    if symbols:
        symbol_list = [part.strip() for part in symbols.split(",") if part.strip()]
    try:
        return reader(settings=settings, basket=basket, symbols=symbol_list)
    except HistoricalPriceReadError as exc:
        status = 400 if exc.code == "market_cross_section_invalid_request" else 503
        raise HTTPException(
            status_code=status,
            detail={
                "code": (
                    "market_cross_section_invalid_request"
                    if status == 400
                    else "market_cross_section_provider_unavailable"
                ),
                "provider": "futu",
                "provider_code": exc.provider_code or exc.code,
                "message": exc.message,
            },
        ) from exc