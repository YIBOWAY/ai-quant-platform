from __future__ import annotations

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.options.models import OptionsScreenerConfig
from quant_system.options.screener import run_options_screener


class _FakeProvider:
    @staticmethod
    def normalize_symbol(symbol: str):
        normalized = symbol.upper()
        return normalized, f"US.{normalized}"

    def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "strike_time": "2026-06-19",
                    "option_expiry_date_distance": 48,
                    "expiration_cycle": "MONTH",
                }
            ]
        )

    def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
        assert option_type == "PUT"
        return pd.DataFrame(
            [
                {
                    "symbol": "US.AAPL260619P250000",
                    "option_type": "PUT",
                    "expiry": expiration,
                    "strike": 250.0,
                    "bid": 2.0,
                    "ask": 2.2,
                    "volume": 100,
                    "open_interest": 500,
                    "implied_volatility": 0.45,
                    "delta": -0.25,
                    "gamma": 0.02,
                    "theta": -0.01,
                    "vega": 0.1,
                }
            ]
        )

    def fetch_underlying_snapshot(self, symbol: str):
        return {"symbol": "US.AAPL", "last": 280.0}

    def fetch_ohlcv(self, symbols: list[str], *, start: str, end: str, interval: str = "1d"):
        rows = []
        for index, timestamp in enumerate(pd.date_range(start=start, end=end, freq="B", tz="UTC")):
            price = 220.0 + index * 0.2
            rows.append(
                {
                    "symbol": symbols[0],
                    "timestamp": timestamp,
                    "open": price,
                    "high": price + 1,
                    "low": price - 1,
                    "close": price,
                    "volume": 1000,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp,
                }
            )
        return normalize_ohlcv_dataframe(
            pd.DataFrame(rows),
            provider="futu",
            interval=interval,
        )


def test_options_screener_scores_sell_put_candidate() -> None:
    result = run_options_screener(
        provider=_FakeProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            min_iv=0.2,
            max_delta=0.35,
            min_premium=1.0,
            max_spread_pct=0.2,
            trend_filter=True,
            hv_iv_filter=False,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.ticker == "AAPL"
    assert result.provider == "futu"
    assert result.underlying_price == 280.0
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.symbol == "US.AAPL260619P250000"
    assert candidate.rating == "Strong"
    assert candidate.mid == 2.1
    assert candidate.spread_pct is not None
    assert candidate.annualized_yield is not None
    assert candidate.premium_per_contract == 210.0


def test_options_screener_avoids_wide_spread() -> None:
    class WideSpreadProvider(_FakeProvider):
        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame.loc[0, "bid"] = 0.5
            frame.loc[0, "ask"] = 2.5
            return frame

    result = run_options_screener(
        provider=WideSpreadProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            max_spread_pct=0.2,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.candidates[0].rating == "Avoid"
    assert "spread too wide" in result.candidates[0].notes


def test_options_screener_applies_income_filters_and_normalizes_iv() -> None:
    class PercentIvProvider(_FakeProvider):
        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame.loc[0, "implied_volatility"] = 45.0
            frame.loc[0, "open_interest"] = 10
            return frame

    result = run_options_screener(
        provider=PercentIvProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            min_apr=100,
            min_open_interest=100,
            max_hv_iv=0.0,
            hv_iv_filter=True,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    candidate = result.candidates[0]
    assert candidate.implied_volatility == 0.45
    assert "APR below minimum" in candidate.notes
    assert "open interest below minimum" in candidate.notes
    assert "IV/HV filter failed" in candidate.notes
