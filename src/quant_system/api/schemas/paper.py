from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PaperRunSummary(BaseModel):
    id: str
    source: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class StrategyConfigResponse(BaseModel):
    strategy_config_id: str
    version: int
    name: str
    description: str = ""
    strategy_id: str
    universe_id: str | None = None
    symbols: list[str] = Field(default_factory=list)
    factor_ids: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    lookback: int
    top_n: int
    rebalance_frequency: str
    max_weight_per_symbol: float
    min_order_value: float
    data_provider: str
    execution_timing: str
    created_at: str
    updated_at: str
    archived: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategySleeveResponse(BaseModel):
    sleeve_id: str
    account_id: str
    strategy_config_id: str
    strategy_config_version: int
    mode: Literal["signal_only", "allocated"]
    status: Literal["running", "paused", "stopped"]
    initial_allocated_cash: float
    cash: float
    created_at: str
    updated_at: str
    paused_at: str | None = None
    stopped_at: str | None = None
    stop_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SleeveLotResponse(BaseModel):
    lot_id: str
    account_id: str
    sleeve_id: str
    symbol: str
    quantity: float
    avg_cost: float
    opened_at: str
    updated_at: str
    source: str


class StrategySignalResponse(BaseModel):
    signal_id: str
    sleeve_id: str
    strategy_config_id: str
    strategy_config_version: int
    signal_date: str
    generated_at: str
    data_provider: str
    data_as_of: str | None = None
    target_weights: dict[str, float] = Field(default_factory=dict)
    proposed_orders: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: Literal["generated", "data_unavailable", "invalid"]
    execution_blocked_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyExecutionOrderResponse(BaseModel):
    symbol: str
    side: str
    target_weight: float | None = None
    current_value: float | None = None
    target_value: float | None = None
    notional_delta: float | None = None
    reference_price: float | None = None
    estimated_quantity: float | None = None
    reason: str | None = None
    account_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyExecutionFillResponse(BaseModel):
    fill_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    gross_value: float
    price_kind: str
    filled_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyExecutionPlanResponse(BaseModel):
    execution_id: str
    sleeve_id: str
    account_id: str
    signal_id: str
    strategy_config_id: str
    strategy_config_version: int
    execution_window: str
    target_date: str | None = None
    created_at: str
    updated_at: str
    status: Literal[
        "pending",
        "filled",
        "partially_filled",
        "skipped",
        "blocked",
        "missed_window",
        "failed",
        "cancelled",
    ]
    blocked_reason: str | None = None
    orders: list[StrategyExecutionOrderResponse] = Field(default_factory=list)
    fills: list[StrategyExecutionFillResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyConfigCreateRequest(BaseModel):
    name: str
    description: str = ""
    strategy_id: str
    universe_id: str | None = None
    symbols: list[str] = Field(default_factory=list)
    factor_ids: list[str] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    lookback: int = Field(default=20, gt=0)
    top_n: int = Field(default=3, gt=0)
    rebalance_frequency: str = "daily"
    max_weight_per_symbol: float = Field(default=1.0, gt=0)
    min_order_value: float = Field(default=0.0, ge=0)
    data_provider: Literal["futu", "tiingo"] = "futu"
    execution_timing: str = "next_open"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategyConfigMutationResponse(BaseModel):
    config: StrategyConfigResponse


class StrategyConfigsResponse(BaseModel):
    configs: list[StrategyConfigResponse]


class StrategySleeveCreateRequest(BaseModel):
    strategy_config_id: str
    strategy_config_version: int | None = Field(default=None, ge=1)
    mode: Literal["signal_only", "allocated"]
    allocated_cash: float = Field(default=0.0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StrategySleevesResponse(BaseModel):
    sleeves: list[StrategySleeveResponse]


class StrategySleeveDetailResponse(BaseModel):
    sleeve: StrategySleeveResponse
    lots: list[SleeveLotResponse]
    signals: list[StrategySignalResponse]
    executions: list[StrategyExecutionPlanResponse] = Field(default_factory=list)


class StrategySleeveStopRequest(BaseModel):
    reason: str | None = None


class StrategySignalGenerateRequest(BaseModel):
    signal_date: str | None = None
    history_days: int = Field(default=180, gt=0)


class StrategySignalMutationResponse(BaseModel):
    signal: StrategySignalResponse


class StrategyExecutionCreateRequest(BaseModel):
    signal_id: str
    execution_window: Literal["next_open"] = "next_open"
    target_date: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_date")
    @classmethod
    def validate_target_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class StrategyExecutionMutationResponse(BaseModel):
    execution: StrategyExecutionPlanResponse


class StrategyExecutionProcessRequest(BaseModel):
    sleeve_id: str | None = None
    execution_window: Literal["next_open"] = "next_open"
    target_date: str | None = None
    limit: int = Field(default=50, gt=0, le=500)

    @field_validator("target_date")
    @classmethod
    def validate_target_date(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class StrategyExecutionProcessResponse(BaseModel):
    processed_count: int
    filled_count: int
    blocked_count: int
    executions: list[StrategyExecutionPlanResponse]
    account: PaperAccountResponse


def _validate_iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("target_date must be an ISO date in YYYY-MM-DD format") from exc
    return parsed.isoformat()


class PaperRunsResponse(BaseModel):
    paper_runs: list[PaperRunSummary]


class PaperRunRequestEchoResponse(BaseModel):
    symbols: list[str]
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"]
    initial_cash: float
    lookback: int
    top_n: int
    max_fill_ratio_per_tick: float
    enable_kill_switch: bool


class PaperRunPathsResponse(BaseModel):
    orders: str
    order_events: str
    trades: str
    risk_breaches: str
    report: str


class PaperRunResponse(BaseModel):
    run_id: str
    kind: str = "paper"
    status: str = "completed"
    created_at: str | None = None
    source: str
    signal_count: int
    order_count: int
    trade_count: int
    risk_breach_count: int
    final_equity: float
    execution_status: str
    execution_note: str | None = None
    request: PaperRunRequestEchoResponse
    paths: PaperRunPathsResponse


class AccountPositionResponse(BaseModel):
    symbol: str
    quantity: float
    avg_cost: float
    last_price: float
    market_value: float
    weight: float
    unrealized_pnl: float
    source_breakdown: dict[str, float] = Field(default_factory=dict)
    price_kind: str
    price_as_of: str | None = None


class PendingAccountOrderResponse(BaseModel):
    order_id: str
    created_at: str
    symbol: str
    side: str
    quantity: float
    limit_price: float
    reserved_cash: float = 0.0
    reserved_quantity: float = 0.0
    source: str
    reason: str
    last_checked_price: float | None = None
    last_checked_price_kind: str | None = None
    last_checked_at: str | None = None


class PaperAccountPriceSourceResponse(BaseModel):
    kind: str
    as_of: str | None = None


class PaperAccountResponse(BaseModel):
    account_id: str
    base_currency: str
    initial_cash: float
    cash: float
    reserved_cash: float = 0.0
    available_cash: float
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    pnl_abs: float
    pnl_pct: float
    invested_pct: float
    kill_switch: bool
    price_source: PaperAccountPriceSourceResponse
    positions: list[AccountPositionResponse]
    pending_orders: list[PendingAccountOrderResponse]
    created_at: str
    updated_at: str


class StrategySleeveMutationResponse(BaseModel):
    sleeve: StrategySleeveResponse
    account: PaperAccountResponse


class PaperAccountOrderOutcomeResponse(BaseModel):
    order_id: str | None = None
    status: str
    symbol: str
    side: str
    requested_quantity: float
    filled_quantity: float
    price: float | None = None
    price_kind: str | None = None
    rejected_reason: str | None = None


class PaperAccountOrderResponse(BaseModel):
    order: PaperAccountOrderOutcomeResponse
    account: PaperAccountResponse


class PaperAccountOrdersProcessResponse(BaseModel):
    orders: list[PaperAccountOrderOutcomeResponse]
    account: PaperAccountResponse


class PaperAccountRebalanceSummaryResponse(BaseModel):
    strategy_id: str
    as_of: str | None = None
    aborted: bool
    target_weights: dict[str, float]
    note: str | None = None
    orders: list[PaperAccountOrderOutcomeResponse]


class PaperAccountRebalanceResponse(BaseModel):
    rebalance: PaperAccountRebalanceSummaryResponse
    account: PaperAccountResponse


class LedgerEntryResponse(BaseModel):
    entry_id: str
    timestamp: str
    kind: str
    source: str
    symbol: str | None = None
    side: str | None = None
    quantity: float | None = None
    price: float | None = None
    gross_value: float | None = None
    commission: float = 0.0
    price_kind: str | None = None
    realized_pnl_delta: float = 0.0
    cash_after: float | None = None
    note: str | None = None


class PaperLedgerResponse(BaseModel):
    total: int
    limit: int
    offset: int
    entries: list[LedgerEntryResponse]


PaperRunRecord = dict[str, Any]


class PaperRunDetailResponse(BaseModel):
    id: str
    metadata: dict[str, Any]
    orders: list[PaperRunRecord]
    order_events: list[PaperRunRecord]
    trades: list[PaperRunRecord]
    risk_breaches: list[PaperRunRecord]


class PaperRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    start: str
    end: str
    provider: Literal["sample", "futu", "tiingo"] = "futu"
    enable_kill_switch: bool = True
    initial_cash: float = Field(default=100_000.0, ge=0)
    lookback: int = Field(default=20, gt=0)
    top_n: int = Field(default=2, gt=0)
    max_fill_ratio_per_tick: float = Field(default=1.0, gt=0, le=1)


class AccountResetRequest(BaseModel):
    initial_cash: float = Field(default=1_000_000.0, ge=0)


class ManualOrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float | None = Field(default=None, gt=0)
    notional: float | None = Field(default=None, gt=0)
    limit_price: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _exactly_one_size(self) -> ManualOrderRequest:
        if (self.quantity is None) == (self.notional is None):
            raise ValueError("provide exactly one of quantity or notional")
        return self


class AccountRebalanceRequest(BaseModel):
    strategy_id: str = "cross_sectional_top_n"
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA"])
    lookback: int = Field(default=20, gt=0)
    top_n: int = Field(default=3, gt=0)
    provider: Literal["futu", "tiingo"] | None = None


class KillSwitchRequest(BaseModel):
    enabled: bool
