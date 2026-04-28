from __future__ import annotations

from typing import Protocol

from quant_system.prediction_market.models import MispricingCandidate, ProposedTrade


class OptimizerInterface(Protocol):
    def solve(self, opportunity: MispricingCandidate) -> ProposedTrade | None:
        """Return a dry proposed trade or None."""
