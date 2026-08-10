from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MarketCrossSectionMetaResponse(BaseModel):
    provider: Literal["futu"]
    symbol: str
    currency: Literal["USD"]
    timezone: Literal["America/New_York"]
    as_of: str
    adjustment: Literal["qfq"]
    provenance: Literal["futu", "futu_cache"]


class MarketCrossSectionReturnsResponse(BaseModel):
    week_pct: float
    month_pct: float
    ytd_pct: float


class MarketCrossSectionHistoryPointResponse(BaseModel):
    date: str
    close: float
    indexed_return_pct: float


class MarketCrossSectionRowResponse(BaseModel):
    symbol: str
    rank: int
    returns: MarketCrossSectionReturnsResponse
    volatility_pct: float
    max_drawdown_pct: float
    history: list[MarketCrossSectionHistoryPointResponse]
    meta: MarketCrossSectionMetaResponse


class MarketCrossSectionBasketLabelResponse(BaseModel):
    en: str
    zh: str


class MarketCrossSectionResponse(BaseModel):
    """Read-only cross-section over a preset/custom symbol universe.

    Same fail-closed Futu contract as Asia Radar: no sample data, no estimated
    valuation metrics.
    """

    schema_version: Literal["1.0"]
    provider: Literal["futu"]
    as_of: str
    timezone: Literal["America/New_York"]
    fetched_at: str
    provenance: Literal["futu", "futu_cache"]
    basket: str | None
    basket_label: MarketCrossSectionBasketLabelResponse | None
    methodology: dict[str, str]
    rows: list[MarketCrossSectionRowResponse]
