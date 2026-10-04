from pydantic import BaseModel


class SecurityEntry(BaseModel):
    symbol: str
    name: str
    asset_type: str
    exchange: str
    currency: str
    sector: str | None
    industry: str | None
    isin: str | None


class SecuritySearchResponse(BaseModel):
    items: list[SecurityEntry]
    source: str
    version: str
    retrieved_at: str
    total: int
    scope: str
