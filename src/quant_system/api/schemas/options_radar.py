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


class OptionsDailyScanTaskStateResponse(BaseModel):
    status: str
    terminal: bool
    current_step: str
    target_session: str
    trigger: Literal["manual", "scheduled"]
    queued_at: str
    started_at: str | None
    finished_at: str | None
    scanned_tickers: int
    total_tickers: int


class OptionsRefreshResponse(BaseModel):
    kind: str
    source: str
    status: str
    row_count: int
    output_path: str
    fetched_at: str
    warning: str | None = None


class OptionsRadarCandidateResponse(BaseModel):
    ticker: str
    sector: str | None = None
    strategy: Literal["sell_put", "covered_call"]
    symbol: str
    expiry: str
    strike: float
    days_to_expiry: int
    mid: float | None = None
    annualized_yield: float | None = None
    gross_annualized_yield: float
    pop: float
    otm_pct: float
    extrinsic_value: float
    breakeven: float
    take_profit_50_price: float
    manage_at_21_dte: str
    expected_value: float
    excess_annualized_ev: float
    liquidity_factor: float
    recommendation_score: float
    recommendation_score_model: str
    hard_gate_passed: bool
    quote_as_of: str
    implied_volatility: float | None = None
    iv_rank: float | None = None
    iv_measure: str
    iv_history_samples: int
    iv_rank_status: Literal["warming", "ready"]
    delta: float | None = None
    open_interest: float | None = None
    spread_pct: float | None = None
    earnings_date: str | None = None
    earnings_in_window: bool
    ex_dividend_date: str | None = None
    ex_dividend_in_window: bool | None = None
    dividend_per_share: float | None = None
    global_score: float
    market_regime: str | None = None
    market_regime_penalty: float | None = None


class OptionsDailyScanResponse(BaseModel):
    run_date: str
    provider: Literal["sample", "futu"] | None
    as_of: str | None
    status: Literal["available", "empty", "unavailable"]
    risk_free_rate: float | None
    shortfall_count: int
    shortfall_reasons: dict[str, int]
    universe_size: int
    scanned_tickers: int
    failed_tickers: list[tuple[str, str]]
    is_stale: bool
    snapshot_age_days: int
    expired_candidate_count: int
    candidate_count: int
    candidates: list[OptionsRadarCandidateResponse]


class OptionsDailyScanSymbolResponse(BaseModel):
    ticker: str
    run_date: str
    provider: Literal["sample", "futu"] | None
    as_of: str | None
    status: Literal["available", "empty", "unavailable"]
    shortfall_count: int
    shortfall_reasons: dict[str, int]
    universe_size: int
    scanned_tickers: int
    failed_tickers: list[tuple[str, str]]
    is_stale: bool
    snapshot_age_days: int
    candidate_count: int
    candidates: list[OptionsRadarCandidateResponse]
