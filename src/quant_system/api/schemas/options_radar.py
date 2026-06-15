from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class OptionsStrategyTemplatesResponse(BaseModel):
    templates: list[dict[str, Any]]


class OptionsWatchlistResponse(BaseModel):
    watchlist: list[dict[str, Any]]


class OptionsDailyScanDatesResponse(BaseModel):
    dates: list[str]


class OptionsDailyScanStatusResponse(BaseModel):
    exists: bool
    status_path: str
    status: dict[str, Any] | None = None


class OptionsRadarCandidateResponse(BaseModel):
    ticker: str
    sector: str | None = None
    strategy: Literal["sell_put", "covered_call"]
    symbol: str
    expiry: str
    strike: float
    mid: float | None = None
    annualized_yield: float | None = None
    implied_volatility: float | None = None
    iv_rank: float | None = None
    delta: float | None = None
    open_interest: float | None = None
    spread_pct: float | None = None
    earnings_date: str | None = None
    earnings_in_window: bool
    global_score: float
    rating: str
    notes: list[str]
    market_regime: str | None = None
    market_regime_penalty: float | None = None


class OptionsDailyScanResponse(BaseModel):
    run_date: str
    universe_size: int
    scanned_tickers: int
    failed_tickers: list[tuple[str, str]]
    is_stale: bool
    snapshot_age_days: int
    expired_candidate_count: int
    candidates: list[OptionsRadarCandidateResponse]


class OptionsDailyScanSymbolResponse(BaseModel):
    ticker: str
    run_date: str
    candidate_count: int
    candidates: list[OptionsRadarCandidateResponse]
