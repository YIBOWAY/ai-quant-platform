from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from quant_system.options.models import OptionsScreenerConfig

OptionRecord = dict[str, Any]


class OptionsExpirationsResponse(BaseModel):
    ticker: str
    source: str
    expirations: list[OptionRecord]


class OptionsChainResponse(BaseModel):
    ticker: str
    source: str
    expiration: str
    option_type: str
    contracts: list[OptionRecord]


class OptionsSnapshotResponse(BaseModel):
    success: bool
    ticker: str
    source: str
    price: float
    nearest_expiry: str
    atm_iv: float | None = None
    hv_30d: float | None = None
    iv_rank: float | None = None
    iv_percentile: float | None = None
    iv_rank_source: str
    vrp: float | None = None
    vrp_level: str | None = None
    assumptions: list[str]


class OptionsVolSurface(BaseModel):
    moneyness_axis: list[float]
    expiry_axis: list[str]
    iv_grid: list[list[float | None]]
    points: list[OptionRecord]


class OptionsVolSurfaceResponse(BaseModel):
    success: bool
    ticker: str
    source: str
    price: float
    surface: OptionsVolSurface
    atm_term_structure: dict[str, float]
    shape: str
    assumptions: list[str]


class OptionsVolSmile(BaseModel):
    strikes: list[float | None]
    ivs: list[float | None]
    deltas: list[float | None]
    option_types: list[str]
    moneyness: list[float | None]


class OptionsVolSmileResponse(BaseModel):
    success: bool
    ticker: str
    source: str
    price: float
    expiry: str
    dte: int
    smile: OptionsVolSmile
    skew_metrics: dict[str, float | None]
    shape: str
    assumptions: list[str]


class OptionsGreeksResponse(BaseModel):
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    charm: float
    vanna: float
    volga: float


class OptionsImpliedVolatilityResponse(BaseModel):
    implied_volatility: float


class OptionsSimulationResponse(BaseModel):
    ticker: str
    price: float
    position: dict[str, Any]
    pnl_at_expiry: dict[str, Any]
    breakevens: list[float]
    max_profit: float | None = None
    max_loss: float | None = None
    risk_reward_ratio: float | None = None
    scenarios: dict[str, Any]
    assumptions: list[str]


class OptionsStrategyBuildResponse(BaseModel):
    mode: str
    template_id: str
    strategy: str
    spot: float
    expiry_days: int
    legs: list[OptionRecord]
    net_debit: float
    max_profit: float | None = None
    max_loss: float | None = None
    breakevens: list[float]
    risk_reward_ratio: float | None = None
    assumptions: list[str]


class OptionsContractScoreResponse(BaseModel):
    success: bool
    objective: str
    spot: float
    ranked_contracts: list[OptionRecord]
    assumptions: list[str]


class OptionsStrategyRankResponse(BaseModel):
    success: bool
    market_view: str
    rankings: list[OptionRecord]
    assumptions: list[str]


class OptionsBullPutSignalResponse(BaseModel):
    success: bool
    fear_score: float
    enter_signal: bool
    selected_spread: dict[str, Any] | None = None
    reasons: list[str]
    assumptions: list[str]


class OptionsFearScoreResponse(BaseModel):
    success: bool
    fear_score: float
    tier: str
    components: dict[str, Any]
    bull_put_spread_signal: bool
    assumptions: list[str]


class OptionsIvRankResponse(BaseModel):
    success: bool
    ticker: str
    current_iv: float | None = None
    sample_count: int
    iv_rank: float | None = None
    iv_percentile: float | None = None
    zone: str
    assumptions: list[str]


class OptionsMarketSentimentResponse(BaseModel):
    success: bool
    sentiment_score: float
    regime: str
    components: dict[str, Any]
    assumptions: list[str]


class OptionsEarningsCrushResponse(BaseModel):
    success: bool
    ticker: str
    sample_count: int
    average_crush_pct: float | None = None
    expected_post_event_iv: float | None = None
    implied_move_pct: float | None = None
    strategy_tag: str
    assumptions: list[str]


class OptionsHedgeAdvisorResponse(BaseModel):
    success: bool
    ticker: str
    situation: dict[str, Any]
    structures: list[OptionRecord]
    assumptions: list[str]


class OptionsUnusualActivityResponse(BaseModel):
    success: bool
    events: list[OptionRecord]
    assumptions: list[str]


__all__ = [
    "OptionsBullPutSignalResponse",
    "OptionsChainResponse",
    "OptionsContractScoreResponse",
    "OptionsEarningsCrushResponse",
    "OptionsExpirationsResponse",
    "OptionsFearScoreResponse",
    "OptionsGreeksResponse",
    "OptionsHedgeAdvisorResponse",
    "OptionsImpliedVolatilityResponse",
    "OptionsIvRankResponse",
    "OptionsMarketSentimentResponse",
    "OptionsScreenerConfig",
    "OptionsSimulationResponse",
    "OptionsSnapshotResponse",
    "OptionsStrategyBuildResponse",
    "OptionsStrategyRankResponse",
    "OptionsUnusualActivityResponse",
    "OptionsVolSmileResponse",
    "OptionsVolSurfaceResponse",
]
