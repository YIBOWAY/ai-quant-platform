from __future__ import annotations


class SettlementRiskTracker:
    """Placeholder for resolution and settlement risk tracking."""

    def assess_resolution_risk(self, market_id: str) -> None:
        raise NotImplementedError(
            f"Settlement risk tracker placeholder for market {market_id!r}; "
            "resolution risk is not modeled in Phase 8."
        )
