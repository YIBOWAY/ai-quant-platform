from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class MarketDataHistoryQuery(BaseModel):
    ticker: str
    start: str
    end: str
    freq: str = "1d"
    provider: Literal["sample", "futu", "tiingo"] = "futu"


class MarketDataHistoryMetadata(BaseModel):
    provider: str
    requested_provider: str
    fetched_at: str | None = None


class MarketDataHistoryResponse(BaseModel):
    symbol: str
    ticker: str
    source: str
    frequency: str
    row_count: int
    rows: list[dict[str, Any]]
    metadata: MarketDataHistoryMetadata
