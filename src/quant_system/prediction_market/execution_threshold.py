from __future__ import annotations

from pydantic import BaseModel, Field

from quant_system.prediction_market.models import MispricingCandidate


class ExecutionThresholdConfig(BaseModel):
    min_edge_bps: float = Field(default=200, ge=0)
    max_capital_per_leg: float = Field(default=1_000, gt=0)
    max_legs: int = Field(default=8, gt=0)


class ProfitThresholdChecker:
    def __init__(self, config: ExecutionThresholdConfig | None = None) -> None:
        self.config = config or ExecutionThresholdConfig()

    def is_allowed(self, candidate: MispricingCandidate) -> bool:
        return (
            candidate.edge_bps >= self.config.min_edge_bps
            and len(candidate.prices) <= self.config.max_legs
        )
