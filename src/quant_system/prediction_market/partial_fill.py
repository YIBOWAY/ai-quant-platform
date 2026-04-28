from __future__ import annotations

from enum import StrEnum


class PartialFillState(StrEnum):
    NEW = "NEW"
    LEG1_FILLED = "LEG1_FILLED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    HEDGED = "HEDGED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class PartialFillManager:
    """State-machine skeleton for later multi-leg execution recovery."""

    def __init__(self) -> None:
        self.state = PartialFillState.NEW

    def mark_leg1_filled(self) -> None:
        self.state = PartialFillState.LEG1_FILLED

    def request_rollback(self) -> None:
        # TODO Phase 8+: define hedge/rollback policy after real execution modeling exists.
        if self.state == PartialFillState.LEG1_FILLED:
            self.state = PartialFillState.ROLLBACK_PENDING
