from __future__ import annotations

from pydantic import BaseModel


class SymbolsResponse(BaseModel):
    symbols: list[str]
    source: str


class OHLCVResponse(BaseModel):
    symbol: str
    rows: list[dict]
