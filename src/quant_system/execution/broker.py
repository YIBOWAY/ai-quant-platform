from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

import pandas as pd

from quant_system.execution.models import ExecutionFill, ManagedOrder


class BrokerAdapter(Protocol):
    def submit_order(self, order: ManagedOrder) -> ManagedOrder:
        """Submit an order to a paper or live broker adapter."""

    def cancel_order(self, order_id: str, *, timestamp: pd.Timestamp, reason: str) -> ManagedOrder:
        """Cancel an open order."""

    def process_market_data(
        self,
        *,
        timestamp: pd.Timestamp,
        prices: Mapping[str, float],
    ) -> list[ExecutionFill]:
        """Process market data and return newly generated fills."""
