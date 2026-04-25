from __future__ import annotations

from typing import Protocol

import pandas as pd


class HistoricalDataProvider(Protocol):
    provider_name: str

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch OHLCV data in the canonical Phase 1 schema."""

