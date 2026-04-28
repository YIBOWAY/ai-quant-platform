from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentTaskRequest(BaseModel):
    task_type: Literal[
        "propose-factor",
        "propose-experiment",
        "summarize",
        "audit-leakage",
    ]
    goal: str = ""
    universe: list[str] = Field(default_factory=lambda: ["SPY", "QQQ"])
    experiment_id: str | None = None
    factor_id: str | None = None


class AgentReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    note: str
