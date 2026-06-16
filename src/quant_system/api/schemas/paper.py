from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PaperRunSummary(BaseModel):
    id: str
    source: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


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
