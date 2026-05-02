from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class MarketDataHistoryQuery(BaseModel):
    ticker: str
    start: str
    end: str
    freq: str = "1d"
    provider: Literal["sample", "futu", "tiingo"] = "futu"
