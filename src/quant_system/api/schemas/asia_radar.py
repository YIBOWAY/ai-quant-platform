from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AsiaRadarMetaResponse(BaseModel):
    provider: Literal["futu"]
    symbol: str
    currency: Literal["USD"]
    timezone: Literal["America/New_York"]
    as_of: str
    adjustment: Literal["qfq"]
    provenance: Literal["futu", "futu_cache"]


class AsiaRadarReturnsResponse(BaseModel):
    week_pct: float
    month_pct: float
    ytd_pct: float


class AsiaRadarHistoryPointResponse(BaseModel):
    date: str
    close: float
    indexed_return_pct: float


class AsiaRadarMarketResponse(BaseModel):
    market_id: str
    name_en: str
    name_zh: str
    symbol: str
    data_status: Literal["real"]
    market_coverage: Literal["proxy"]
    rank: int
    k_leg: Literal["winner", "middle", "laggard"]
    returns: AsiaRadarReturnsResponse
    volatility_pct: float
    max_drawdown_pct: float
    history: list[AsiaRadarHistoryPointResponse]
    meta: AsiaRadarMetaResponse


class AsiaRadarKShapePointResponse(BaseModel):
    date: str
    winner_avg_pct: float
    laggard_avg_pct: float
    spread_pct: float


class AsiaRadarKShapeResponse(BaseModel):
    winners: list[str]
    laggards: list[str]
    series: list[AsiaRadarKShapePointResponse]


class AsiaRadarOverviewResponse(BaseModel):
    schema_version: Literal["1.0", "1.1"]
    provider: Literal["futu"]
    as_of: str
    timezone: Literal["America/New_York"]
    fetched_at: str
    provenance: Literal["futu", "futu_cache"]
    methodology: dict[str, str]
    markets: list[AsiaRadarMarketResponse]
    k_shape: AsiaRadarKShapeResponse
