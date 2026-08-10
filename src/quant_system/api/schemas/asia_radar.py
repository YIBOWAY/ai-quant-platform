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


class AsiaRadarLocalIndexPointResponse(BaseModel):
    date: str
    close: float
    indexed_return_pct: float


class AsiaRadarLocalIndexResponse(BaseModel):
    """Display-only local index overlay for one market (Slice 2A).

    Never mixed into the USD ETF proxy metrics. ``status="unavailable"``
    carries an explicit reason (pending channel or provider error) so the
    index lane is fail-closed without taking the ETF main path down.
    """

    status: Literal["available", "unavailable"]
    index_symbol: str | None
    index_name_en: str | None
    index_name_zh: str | None
    currency: str | None
    timezone: str | None
    as_of: str | None
    provider: Literal["futu"] | None
    provenance: Literal["futu", "futu_cache"] | None
    fetched_at: str | None
    adjustment: str | None
    series: list[AsiaRadarLocalIndexPointResponse]
    reason_code: str | None
    reason: str | None
    provider_code: str | None


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
    local_index: AsiaRadarLocalIndexResponse | None = None


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
    schema_version: Literal["1.0", "1.1", "1.2"]
    provider: Literal["futu"]
    as_of: str
    timezone: Literal["America/New_York"]
    fetched_at: str
    provenance: Literal["futu", "futu_cache"]
    methodology: dict[str, str]
    markets: list[AsiaRadarMarketResponse]
    k_shape: AsiaRadarKShapeResponse


class AsiaRadarMarketSummaryResponse(BaseModel):
    symbol: str
    market_id: str
    name_en: str
    name_zh: str
    rank: int
    k_leg: Literal["winner", "middle", "laggard"]
    ytd_pct: float
    week_pct: float
    month_pct: float
    volatility_pct: float
    max_drawdown_pct: float
    as_of: str


class AsiaRadarSummaryResponse(BaseModel):
    """Lightweight, read-only summary for daily-brief / notification surfaces.

    Same fail-closed contract as the overview: no sample data, no estimated
    valuation metrics, no narrative generation.
    """

    schema_version: Literal["1.1"]
    provider: Literal["futu"]
    as_of: str
    timezone: Literal["America/New_York"]
    fetched_at: str
    provenance: Literal["futu", "futu_cache"]
    status: Literal["available", "unavailable"]
    market_count: int
    winner_symbols: list[str]
    laggard_symbols: list[str]
    spread_pct: float | None
    top_ytd_symbol: str | None
    top_ytd_pct: float | None
    bottom_ytd_symbol: str | None
    bottom_ytd_pct: float | None
    markets: list[AsiaRadarMarketSummaryResponse]
