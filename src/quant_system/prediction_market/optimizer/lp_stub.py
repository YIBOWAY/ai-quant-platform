from __future__ import annotations

import importlib.util

from quant_system.prediction_market.models import MispricingCandidate, ProposedTrade
from quant_system.prediction_market.optimizer.greedy_stub import GreedyStub


class LPStub:
    """Optional minimal LP placeholder; not a Frank-Wolfe or IP solver."""

    def __init__(self, *, max_capital: float = 1_000.0) -> None:
        self.max_capital = max_capital

    def solve(self, opportunity: MispricingCandidate) -> ProposedTrade | None:
        if importlib.util.find_spec("scipy.optimize") is None:
            raise RuntimeError(
                "Install quant-system[prediction_market] to use LPStub."
            )
        if len(opportunity.prices) > 3:
            return None
        return GreedyStub(max_capital=self.max_capital).solve(opportunity)
