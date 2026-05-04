from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

StrategyType = Literal["sell_put", "covered_call"]
BuySideStrategyType = Literal[
    "long_call",
    "bull_call_spread",
    "leaps_call",
    "leaps_call_spread",
]
BuySideViewType = Literal[
    "long_term_aggressive_bullish",
    "long_term_conservative_bullish",
    "short_term_speculative_bullish",
    "short_term_conservative_bullish",
    "event_driven_bullish",
]
BuySideVolatilityView = Literal[
    "auto",
    "prefer_low_iv",
    "expect_iv_crush",
    "expect_iv_expansion",
]
BuySideRiskPreference = Literal["aggressive", "balanced", "conservative"]
BuySideEventRisk = Literal[
    "none",
    "earnings",
    "fomc",
    "cpi",
    "product_event",
    "user_defined",
]
BuySideRiskWarning = Literal[
    "missing_quote",
    "invalid_bid_ask",
    "zero_mid_price",
    "wide_spread",
    "missing_iv",
    "missing_greeks",
    "missing_open_interest",
    "zero_open_interest",
    "missing_volume",
    "zero_volume",
    "stale_quote",
    "event_risk",
    "high_theta_decay",
    "iv_crush_risk",
    "breakeven_far",
    "insufficient_history",
    "HIGH_IV_CRUSH_RISK",
    "HIGH_THETA_BURN",
    "POOR_LIQUIDITY",
    "BREAK_EVEN_ABOVE_TARGET",
    "LOW_REWARD_RISK",
    "CAPPED_UPSIDE",
    "LOTTERY_OPTION",
    "EVENT_RISK",
    "MISSING_DATA",
    "MARKET_REGIME_ELEVATED",
    "MARKET_REGIME_PANIC",
]
BuySideLegSide = Literal["long", "short"]

_RISK_ATTRIBUTION_KEYS = frozenset(
    {"direction", "time", "volatility", "liquidity"}
)


def _parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO date") from exc


def _days_between(start: str | None, end: str) -> int:
    start_date = _parse_iso_date(start, field_name="as_of_date") if start else date.today()
    end_date = _parse_iso_date(end, field_name="expiry")
    return max((end_date - start_date).days, 0)


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
    market_regime: Literal["Normal", "Elevated", "Panic", "Unknown"] | None = None
    market_regime_penalty: float = 0.0
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
    market_regime: Literal["Normal", "Elevated", "Panic", "Unknown"] | None = None
    market_regime_penalty: float = 0.0
    market_regime_w_vix: float | None = None
    market_regime_vix_density: float | None = None
    market_regime_term_ratio: float | None = None
    candidates: list[OptionsScreenerCandidate]
    assumptions: list[str]


class BuySideThesisInput(BaseModel):
    ticker: str = "AAPL"
    view_type: BuySideViewType
    target_price: float | None = Field(default=None, gt=0)
    target_date: str | None = None
    max_premium: float | None = Field(default=None, ge=0)
    volatility_view: BuySideVolatilityView = "auto"
    risk_preference: BuySideRiskPreference = "balanced"
    event_risk: BuySideEventRisk = "none"
    event_label: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("target_date")
    @classmethod
    def _validate_target_date(cls, value: str | None) -> str | None:
        if value is not None:
            _parse_iso_date(value, field_name="target_date")
        return value


class BuySideStrategyLeg(BaseModel):
    symbol: str
    option_type: Literal["CALL", "PUT"]
    side: BuySideLegSide
    expiry: str
    strike: float = Field(gt=0)
    spot: float = Field(gt=0)
    as_of_date: str | None = None
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    last: float | None = Field(default=None, ge=0)
    quantity: int = Field(default=1, ge=1)
    contract_size: int = Field(default=100, ge=1)
    implied_volatility: float | None = Field(default=None, ge=0)
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    volume: float | None = Field(default=None, ge=0)
    open_interest: float | None = Field(default=None, ge=0)
    update_time: str | None = None
    warnings: list[BuySideRiskWarning] = Field(default_factory=list)

    @field_validator("expiry", "as_of_date")
    @classmethod
    def _validate_date_fields(cls, value: str | None, info) -> str | None:
        if value is not None:
            _parse_iso_date(value, field_name=info.field_name)
        return value

    @model_validator(mode="after")
    def _attach_quote_warnings(self) -> BuySideStrategyLeg:
        warnings = list(dict.fromkeys(self.warnings))
        if self.bid is None or self.ask is None:
            warnings.append("missing_quote")
        elif self.ask < self.bid:
            warnings.append("invalid_bid_ask")
        elif self.mid_price is None or self.mid_price <= 0:
            warnings.append("zero_mid_price")
        if self.implied_volatility is None:
            warnings.append("missing_iv")
        if all(value is None for value in (self.delta, self.gamma, self.theta, self.vega)):
            warnings.append("missing_greeks")
        if self.open_interest is None:
            warnings.append("missing_open_interest")
        elif self.open_interest == 0:
            warnings.append("zero_open_interest")
        if self.volume is None:
            warnings.append("missing_volume")
        elif self.volume == 0:
            warnings.append("zero_volume")
        self.warnings = list(dict.fromkeys(warnings))
        return self

    @computed_field
    @property
    def mid_price(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        if self.bid < 0 or self.ask < 0 or self.ask < self.bid:
            return None
        value = (self.bid + self.ask) / 2
        return value if value > 0 else None

    @computed_field
    @property
    def spread_abs(self) -> float | None:
        if self.bid is None or self.ask is None or self.ask < self.bid:
            return None
        return self.ask - self.bid

    @computed_field
    @property
    def spread_pct(self) -> float | None:
        if self.spread_abs is None or self.mid_price is None:
            return None
        return self.spread_abs / self.mid_price

    @computed_field
    @property
    def call_moneyness(self) -> float:
        return self.spot / self.strike

    @computed_field
    @property
    def dte(self) -> int:
        return _days_between(self.as_of_date, self.expiry)

    @computed_field
    @property
    def is_tradable(self) -> bool:
        return self.mid_price is not None and not any(
            warning in {"missing_quote", "invalid_bid_ask", "zero_mid_price"}
            for warning in self.warnings
        )


class BuySideStrategyScore(BaseModel):
    total_score: float = Field(ge=0, le=100)
    direction_score: float | None = Field(default=None, ge=0, le=100)
    timing_score: float | None = Field(default=None, ge=0, le=100)
    volatility_score: float | None = Field(default=None, ge=0, le=100)
    liquidity_score: float | None = Field(default=None, ge=0, le=100)
    buyer_friendliness_score: float | None = Field(default=None, ge=0, le=100)
    iv_crash_risk_score: float | None = Field(default=None, ge=0, le=100)
    breakeven_difficulty_score: float | None = Field(default=None, ge=0, le=100)
    theta_pain_score: float | None = Field(default=None, ge=0, le=100)
    leverage_efficiency: float | None = Field(default=None, ge=0)
    cost_of_convexity: float | None = Field(default=None, ge=0)


class BuySideStrategyCandidate(BaseModel):
    strategy_type: BuySideStrategyType
    ticker: str
    legs: list[BuySideStrategyLeg] = Field(min_length=1)
    score: BuySideStrategyScore
    net_debit: float | None = Field(default=None, ge=0)
    max_loss: float | None = Field(default=None, ge=0)
    max_gain: float | None = None
    breakeven: float | None = Field(default=None, gt=0)
    expected_move_pct: float | None = None
    target_vs_expected_move_ratio: float | None = None
    risk_attribution: dict[str, float] = Field(
        default_factory=lambda: {
            "direction": 0.0,
            "time": 0.0,
            "volatility": 0.0,
            "liquidity": 0.0,
        }
    )
    warnings: list[BuySideRiskWarning] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    market_regime: Literal["Normal", "Elevated", "Panic", "Unknown"] | None = None
    market_regime_penalty: float = 0.0

    @field_validator("risk_attribution")
    @classmethod
    def _validate_risk_attribution(cls, value: dict[str, float]) -> dict[str, float]:
        keys = set(value)
        if keys != _RISK_ATTRIBUTION_KEYS:
            raise ValueError(
                "risk_attribution must contain direction, time, volatility, liquidity"
            )
        for score in value.values():
            if score < 0 or score > 100:
                raise ValueError("risk_attribution values must be between 0 and 100")
        return value


class BuySideUserScenario(BaseModel):
    label: str
    probability: float = Field(ge=0, le=1)
    spot_change_pct: float
    iv_change_vol_points: float


class BuySideScenarioInput(BaseModel):
    spot: float = Field(gt=0)
    implied_volatility: float | None = Field(default=None, ge=0)
    days_to_expiry: int = Field(ge=0)
    user_scenarios: list[BuySideUserScenario] = Field(default_factory=list)


class BuySideScenarioResult(BaseModel):
    label: str
    spot: float = Field(gt=0)
    implied_volatility: float | None = Field(default=None, ge=0)
    estimated_value: float | None = Field(default=None, ge=0)
    pnl: float | None = None
    return_pct: float | None = None
    warnings: list[BuySideRiskWarning] = Field(default_factory=list)


class BuySideScenarioMatrixCell(BaseModel):
    spot_change_pct: float
    iv_change_vol_points: float
    estimated_value: float | None = Field(default=None, ge=0)
    pnl: float | None = None
    return_pct: float | None = None


class BuySideScenarioContribution(BaseModel):
    label: str
    probability: float = Field(ge=0, le=1)
    pnl: float
    expected_value_contribution: float


class BuySideScenarioEV(BaseModel):
    expected_value: float
    contributions: list[BuySideScenarioContribution] = Field(default_factory=list)


class BuySideAssistantResult(BaseModel):
    ticker: str
    thesis: BuySideThesisInput
    provider: Literal["futu"] = "futu"
    candidates: list[BuySideStrategyCandidate] = Field(default_factory=list)
    scenario_results: list[BuySideScenarioResult] = Field(default_factory=list)
    scenario_matrix: list[BuySideScenarioMatrixCell] = Field(default_factory=list)
    scenario_ev: BuySideScenarioEV | None = None
    warnings: list[BuySideRiskWarning] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
