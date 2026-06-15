from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class PaperRunSummary(BaseModel):
    id: str
    source: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)


class PaperRunsResponse(BaseModel):
    paper_runs: list[PaperRunSummary]


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
