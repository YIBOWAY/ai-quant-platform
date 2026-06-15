from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class RecentRun(BaseModel):
    kind: Literal["backtest", "factor", "paper"]
    run_id: str
    source: str
    created_at: str | None = None
    summary: dict[str, Any]


class RecentRunsResponse(BaseModel):
    total: int
    generated_at: str
    runs: list[RecentRun]
