from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiskDefaults:
    """Conservative Phase 0 risk-limit defaults."""

    max_position_size: float = 0.05
    max_daily_loss: float = 0.02
    max_drawdown: float = 0.10
    max_order_value: float = 10_000
    max_turnover: float = 1.0
    allowed_symbols: list[str] = field(default_factory=list)
    blocked_symbols: list[str] = field(default_factory=list)


def get_default_risk_limits() -> RiskDefaults:
    """Return a fresh set of conservative default risk limits."""
    return RiskDefaults()
