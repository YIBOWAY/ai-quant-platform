from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StrategyType = Literal["sell_put", "covered_call"]


class OptionsScreenerConfig(BaseModel):
    ticker: str = "AAPL"
    strategy_type: StrategyType = "sell_put"
    expiration: str | None = None
    min_iv: float = Field(default=0.0, ge=0)
    max_delta: float = Field(default=0.35, ge=0, le=1)
    min_premium: float = Field(default=0.10, ge=0)
    min_apr: float = Field(default=0.0, ge=0)
    min_dte: int = Field(default=0, ge=0)
    max_dte: int = Field(default=365, ge=0)
    max_spread_pct: float = Field(default=0.35, ge=0)
    min_open_interest: float = Field(default=0.0, ge=0)
    max_hv_iv: float = Field(default=10.0, ge=0)
    trend_filter: bool = True
    hv_iv_filter: bool = False
    provider: Literal["futu"] = "futu"
    # Rolling history window for HV/MA/ADV. None means rolling
    # [today - lookback_days, today]. Explicit start/end take precedence.
    history_start: str | None = None
    history_end: str | None = None
    history_lookback_days: int = Field(default=90, ge=20, le=365)
    # Phase 12 fix: extra liquidity / quality screens (Futu data only).
    top_n: int = Field(default=100, ge=1, le=1000)
    min_mid_price: float = Field(default=0.0, ge=0)
    min_avg_daily_volume: float = Field(default=0.0, ge=0)  # underlying ADV (shares/day)
    min_market_cap: float = Field(default=0.0, ge=0)        # USD; 0 = disabled
    # Phase 13 placeholders. Both default to 0/disabled because they require
    # daily IV history and an earnings calendar that Futu OpenAPI does not expose.
    # The radar scanner (Phase 13) will populate these via persisted snapshots
    # and an external earnings source (e.g. yfinance).
    min_iv_rank: float = Field(default=0.0, ge=0, le=100)
    avoid_earnings_within_days: int = Field(default=0, ge=0)


class OptionsScreenerCandidate(BaseModel):
    symbol: str
    underlying: str
    strategy_type: StrategyType
    option_type: Literal["PUT", "CALL"]
    expiry: str
    strike: float
    underlying_price: float
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    implied_volatility: float | None = None
    historical_volatility: float | None = None
    hv_iv_ratio: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    premium_per_contract: float | None = None
    moneyness: float | None = None
    distance_pct: float | None = None
    days_to_expiry: int | None = None
    annualized_yield: float | None = None
    spread_pct: float | None = None
    trend_pass: bool | None = None
    hv_iv_pass: bool | None = None
    avg_daily_volume: float | None = None
    market_cap: float | None = None
    iv_rank: float | None = None
    earnings_date: str | None = None
    rating: Literal["Strong", "Watch", "Avoid"]
    notes: list[str] = Field(default_factory=list)


class OptionsScreenerResult(BaseModel):
    ticker: str
    provider: Literal["futu"]
    strategy_type: StrategyType
    expiration: str | None = None
    scanned_expirations: list[str] = Field(default_factory=list)
    expiration_count: int = 0
    underlying_price: float
    historical_volatility: float | None = None
    trend_reference: float | None = None
    candidates: list[OptionsScreenerCandidate]
    assumptions: list[str]
