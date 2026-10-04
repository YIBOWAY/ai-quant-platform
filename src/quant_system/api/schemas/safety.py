from __future__ import annotations

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
