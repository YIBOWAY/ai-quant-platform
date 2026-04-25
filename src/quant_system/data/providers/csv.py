from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe


class CSVDataProvider:
    provider_name = "csv"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch_ohlcv(
        self,
        symbols: list[str] | None = None,
        *,
        start: str | None = None,
        end: str | None = None,
        interval: str = "1d",
    ) -> pd.DataFrame:
        raw = pd.read_csv(self.path)
        frame = normalize_ohlcv_dataframe(raw, provider=self.provider_name, interval=interval)

        if symbols:
            normalized_symbols = {symbol.upper() for symbol in symbols}
            frame = frame[frame["symbol"].isin(normalized_symbols)]
        if start:
            frame = frame[frame["timestamp"] >= pd.Timestamp(start, tz="UTC")]
        if end:
            frame = frame[frame["timestamp"] <= pd.Timestamp(end, tz="UTC")]

        return frame.reset_index(drop=True)

