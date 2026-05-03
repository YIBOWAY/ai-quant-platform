from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Event(BaseModel):
    event_id: str
    title: str
    description: str = ""


class Condition(BaseModel):
    condition_id: str
    event_id: str
    title: str


class Outcome(BaseModel):
    name: str
    outcome_index: int = Field(ge=0)
    token_id: str


class OutcomeToken(BaseModel):
    token_id: str
    condition_id: str
    outcome_index: int = Field(ge=0)
    name: str


class Market(BaseModel):
    market_id: str
    event_id: str
    condition_id: str
    question: str
    outcomes: list[Outcome]
    active: bool = True
    closed: bool = False


class CLOBOrder(BaseModel):
    price: float = Field(ge=0, le=1)
    size: float = Field(gt=0)


class OrderBookSnapshot(BaseModel):
    market_id: str
    condition_id: str
    token_id: str
    bids: list[CLOBOrder] = Field(default_factory=list)
    asks: list[CLOBOrder] = Field(default_factory=list)
    timestamp: str = Field(default_factory=utc_now_iso)

    @property
    def best_bid(self) -> CLOBOrder | None:
        return max(self.bids, key=lambda order: order.price, default=None)

    @property
    def best_ask(self) -> CLOBOrder | None:
        return min(self.asks, key=lambda order: order.price, default=None)


class PriceHistoryPoint(BaseModel):
    timestamp: str
    price: float = Field(ge=0, le=1)


class MarketTrade(BaseModel):
    condition_id: str
    token_id: str
    price: float = Field(ge=0, le=1)
    size: float = Field(gt=0)
    side: Literal["BUY", "SELL", "buy", "sell"]
    timestamp: str


class HistoricalSnapshotRecord(BaseModel):
    provider: str
    market_id: str
    condition_id: str
    token_id: str
    timestamp_utc: str
    fetched_at: str
    source_type: str
    source_endpoint: str
    market: Market
    order_book: OrderBookSnapshot


class MispricingCandidate(BaseModel):
    market_id: str
    condition_id: str
    scanner_id: str
    description: str
    edge_bps: float
    prices: dict[str, float]
    direction: Literal["underpriced_complete_set", "overpriced_complete_set"] = (
        "underpriced_complete_set"
    )
    created_at: str = Field(default_factory=utc_now_iso)

    @property
    def candidate_id(self) -> str:
        raw = f"{self.market_id}|{self.scanner_id}|{self.direction}|{self.prices}"
        return f"pm-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


class ProposedLeg(BaseModel):
    token_id: str
    side: Literal["buy", "sell"]
    price: float = Field(ge=0, le=1)
    size: float = Field(gt=0)


class ProposedTrade(BaseModel):
    proposal_id: str
    opportunity: MispricingCandidate
    legs: list[ProposedLeg]
    capital: float = Field(ge=0)
    expected_profit: float
    dry_run: bool = True
    threshold_passed: bool = True
    created_at: str = Field(default_factory=utc_now_iso)
