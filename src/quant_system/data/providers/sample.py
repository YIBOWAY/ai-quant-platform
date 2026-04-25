from __future__ import annotations

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe


class SampleOHLCVProvider:
    provider_name = "sample"

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        dates = pd.date_range(start=start, end=end, freq="B", tz="UTC")
        rows: list[dict[str, object]] = []
        for symbol_index, symbol in enumerate(symbols):
            base_price = 100.0 + symbol_index * 25.0
            for date_index, timestamp in enumerate(dates):
                open_price = base_price + date_index
                close_price = open_price + 0.5
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": timestamp,
                        "open": open_price,
                        "high": close_price + 1.0,
                        "low": open_price - 1.0,
                        "close": close_price,
                        "volume": 1_000 + date_index * 100 + symbol_index * 10,
                        "event_ts": timestamp,
                        "knowledge_ts": timestamp + pd.Timedelta(days=1),
                    }
                )

        return normalize_ohlcv_dataframe(
            pd.DataFrame(rows),
            provider=self.provider_name,
            interval=interval,
        )

