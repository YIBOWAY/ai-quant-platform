from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReversalMomentumReplicationDetailResponse(BaseModel):
    run_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
