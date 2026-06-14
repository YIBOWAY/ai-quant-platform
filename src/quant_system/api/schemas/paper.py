from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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
    strategy_id: Literal["cross_sectional_top_n", "mean_reversion_top_n"] = (
        "cross_sectional_top_n"
    )
    symbols: list[str] = Field(default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA"])
    lookback: int = Field(default=20, gt=0)
    top_n: int = Field(default=3, gt=0)
    provider: Literal["futu", "tiingo"] | None = None

class KillSwitchRequest(BaseModel):
    enabled: bool
