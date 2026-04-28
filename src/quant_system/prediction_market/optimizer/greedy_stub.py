from __future__ import annotations

import hashlib

from quant_system.prediction_market.models import (
    MispricingCandidate,
    ProposedLeg,
    ProposedTrade,
)


class GreedyStub:
    """Capital-limited dry proposal generator; it never submits orders."""

    def __init__(self, *, max_capital: float = 1_000.0) -> None:
        self.max_capital = max_capital

    def solve(self, opportunity: MispricingCandidate) -> ProposedTrade | None:
        if opportunity.edge_bps <= 0 or not opportunity.prices:
            return None
        side = "buy" if opportunity.direction == "underpriced_complete_set" else "sell"
        capital_per_leg = self.max_capital / len(opportunity.prices)
        legs = [
            ProposedLeg(
                token_id=name,
                side=side,
                price=price,
                size=capital_per_leg / price,
            )
            for name, price in opportunity.prices.items()
            if price > 0
        ]
        if not legs:
            return None
        raw = f"{opportunity.candidate_id}|{self.max_capital}|{side}"
        return ProposedTrade(
            proposal_id=f"proposal-{hashlib.sha256(raw.encode()).hexdigest()[:12]}",
            opportunity=opportunity,
            legs=legs,
            capital=self.max_capital,
            expected_profit=self.max_capital * opportunity.edge_bps / 10_000,
            dry_run=True,
            threshold_passed=True,
        )
