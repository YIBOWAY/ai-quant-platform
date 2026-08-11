from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class EffectivePaperSafetyResponse(BaseModel):
    owner_user_id: str = Field(min_length=1, max_length=64)
    workspace_id: str = Field(min_length=1, max_length=200)
    global_kill_switch: bool
    canonical_account_count: int | None = Field(default=None, ge=0)
    canonical_account_frozen: bool | None = None
    current_paper_authority_epoch: int | None = Field(
        default=None,
        ge=1,
        le=2**63 - 1,
    )
    effective: bool
    blockers: list[str]


class D34MandateSafety(BaseModel):
    mandate_id: str
    status: str
    expires_at: datetime
    remaining_seconds: int = Field(ge=0)
    paper_execution_allowed: bool


class D34EmergencySafety(BaseModel):
    active: bool
    reason: str | None
    created_at: datetime | None


class D34LegacySafety(BaseModel):
    mode_enabled: bool
    auto_land_enabled: bool


class D34AutomationSafety(BaseModel):
    mandate_active: bool
    queued_jobs: int = Field(ge=0)
    running_jobs: int = Field(ge=0)
    active_canaries: int = Field(ge=0)


class D34BudgetSafety(BaseModel):
    limit_usd: str | None
    spent_usd: str | None
    remaining_usd: str | None
    warning_fraction: str | None
    warning: bool


class D34QuotaSafety(BaseModel):
    new_canaries_today: int = Field(ge=0)
    max_new_canaries_per_day: int = Field(ge=1)


class D34CanarySafety(BaseModel):
    active_count: int = Field(ge=0)
    allocated_cash: str


class D34RiskSafety(BaseModel):
    max_sleeve_cash: str
    max_sleeve_nav_fraction: float = Field(ge=0, le=1)
    max_total_nav_fraction: float = Field(ge=0, le=1)
    max_symbol_nav_fraction: float = Field(ge=0, le=1)
    max_daily_loss: float = Field(ge=0, le=1)
    max_drawdown: float = Field(ge=0, le=1)


class EffectiveD34SafetyResponse(BaseModel):
    contract: str = Field(pattern=r"^hqa\.effective_paper_safety/v2$")
    workspace_id: str
    active_mandate: D34MandateSafety | None
    research_execution_enabled: bool
    research_blockers: list[str]
    paper_execution_enabled: bool
    blockers: list[str]
    emergency_stop: D34EmergencySafety
    d33: D34LegacySafety
    d34: D34AutomationSafety
    budget: D34BudgetSafety
    quota: D34QuotaSafety
    canaries: D34CanarySafety
    risk: D34RiskSafety
    live_execution_enabled: bool


class D34EmergencyStopRequest(BaseModel):
    workspace_id: str = Field(default="default", min_length=1, max_length=128)
    enabled: bool
    reason: str = Field(min_length=1, max_length=1000)
