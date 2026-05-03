from __future__ import annotations

import math

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe


class SampleOptionsProvider:
    provider_name = "sample"

    @staticmethod
    def normalize_symbol(symbol: str) -> tuple[str, str]:
        normalized = symbol.upper().strip()
        return normalized, f"US.{normalized}"

    def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"strike_time": "2026-05-22", "option_expiry_date_distance": 19},
                {"strike_time": "2026-06-19", "option_expiry_date_distance": 47},
                {"strike_time": "2026-07-17", "option_expiry_date_distance": 75},
            ]
        )

    def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str = "ALL"):
        plain, futu_symbol = self.normalize_symbol(underlying)
        price = self._base_price(plain)
        wanted = option_type.upper()
        option_types = ["PUT", "CALL"] if wanted == "ALL" else [wanted]
        rows = []
        for active_type in option_types:
            multipliers = [0.90, 0.95, 1.00, 1.05, 1.10]
            for multiplier in multipliers:
                strike = round(price * multiplier, 2)
                distance = abs(strike / price - 1.0)
                mid = max(0.12, 1.8 * math.exp(-distance * 8))
                spread = max(0.02, mid * 0.08)
                bid = round(mid - spread / 2, 2)
                ask = round(mid + spread / 2, 2)
                rows.append(
                    {
                        "symbol": _sample_option_symbol(
                            futu_symbol,
                            expiration,
                            active_type,
                            strike,
                        ),
                        "underlying": futu_symbol,
                        "option_type": active_type,
                        "expiry": expiration,
                        "strike": strike,
                        "bid": max(bid, 0.01),
                        "ask": max(ask, 0.02),
                        "volume": 100,
                        "open_interest": 250,
                        "implied_volatility": 0.28 + distance,
                        "delta": _sample_delta(active_type, strike, price),
                        "gamma": 0.02,
                        "theta": -0.01,
                        "vega": 0.10,
                    }
                )
        return pd.DataFrame(rows)

    def fetch_underlying_snapshot(self, symbol: str) -> dict[str, object]:
        plain, futu_symbol = self.normalize_symbol(symbol)
        return {
            "symbol": futu_symbol,
            "last": self._base_price(plain),
            "market_val": 25_000_000_000,
        }

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        rows = []
        for symbol in symbols:
            plain, _futu_symbol = self.normalize_symbol(symbol)
            base = self._base_price(plain) * 0.9
            dates = pd.date_range(start=start, end=end, freq="B", tz="UTC")
            for index, timestamp in enumerate(dates):
                close = base + index * 0.12
                rows.append(
                    {
                        "symbol": plain,
                        "timestamp": timestamp,
                        "open": close - 0.1,
                        "high": close + 0.8,
                        "low": close - 0.8,
                        "close": close,
                        "volume": 1_500_000,
                        "event_ts": timestamp,
                        "knowledge_ts": timestamp,
                    }
                )
        return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="sample", interval=interval)

    @staticmethod
    def _base_price(symbol: str) -> float:
        return 80.0 + (sum(symbol.encode("utf-8")) % 180)


def _sample_delta(option_type: str, strike: float, underlying_price: float) -> float:
    distance = strike / underlying_price - 1.0
    if option_type == "PUT":
        return round(min(max(-0.50 + distance * 2.5, -0.95), -0.05), 3)
    return round(min(max(0.50 - distance * 2.5, 0.05), 0.95), 3)


def _sample_option_symbol(
    futu_symbol: str,
    expiration: str,
    option_type: str,
    strike: float,
) -> str:
    code = option_type[0]
    date_part = expiration.replace("-", "")[2:]
    strike_part = f"{int(round(strike * 1000)):08d}"
    return f"{futu_symbol}{date_part}{code}{strike_part}"
