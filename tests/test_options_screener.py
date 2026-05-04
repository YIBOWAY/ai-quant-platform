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
    assert result.expiration is None
    assert result.scanned_expirations == ["2026-06-19"]
    assert result.expiration_count == 1
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


def test_options_screener_scans_all_expirations_inside_dte_window() -> None:
    class MultiExpirationProvider(_FakeProvider):
        def __init__(self) -> None:
            self.requested_expirations: list[str] = []

        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"strike_time": "2026-05-08", "option_expiry_date_distance": 5},
                    {"strike_time": "2026-05-22", "option_expiry_date_distance": 19},
                    {"strike_time": "2026-06-19", "option_expiry_date_distance": 48},
                    {"strike_time": "2026-08-21", "option_expiry_date_distance": 110},
                ]
            )

        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            self.requested_expirations.append(expiration)
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame.loc[0, "symbol"] = f"US.AAPL{expiration.replace('-', '')}P250000"
            return frame

    provider = MultiExpirationProvider()
    result = run_options_screener(
        provider=provider,
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            min_dte=10,
            max_dte=60,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert provider.requested_expirations == ["2026-05-22", "2026-06-19"]
    assert result.scanned_expirations == ["2026-05-22", "2026-06-19"]
    assert result.expiration_count == 2
    assert {candidate.expiry for candidate in result.candidates} == {"2026-05-22", "2026-06-19"}


def test_options_screener_respects_explicit_expiration_for_compatibility() -> None:
    class MultiExpirationProvider(_FakeProvider):
        def __init__(self) -> None:
            self.requested_expirations: list[str] = []

        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"strike_time": "2026-05-22", "option_expiry_date_distance": 19},
                    {"strike_time": "2026-06-19", "option_expiry_date_distance": 48},
                ]
            )

        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            self.requested_expirations.append(expiration)
            return super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )

    provider = MultiExpirationProvider()
    result = run_options_screener(
        provider=provider,
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            expiration="2026-06-19",
            min_dte=10,
            max_dte=60,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert provider.requested_expirations == ["2026-06-19"]
    assert result.expiration == "2026-06-19"
    assert result.scanned_expirations == ["2026-06-19"]


def test_options_screener_uses_range_queries_without_exceeding_30_day_span() -> None:
    class RangeProvider(_FakeProvider):
        def __init__(self) -> None:
            self.range_requests: list[tuple[str, str]] = []

        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"strike_time": "2026-05-08", "option_expiry_date_distance": 5},
                    {"strike_time": "2026-05-22", "option_expiry_date_distance": 19},
                    {"strike_time": "2026-06-05", "option_expiry_date_distance": 33},
                    {"strike_time": "2026-06-19", "option_expiry_date_distance": 47},
                ]
            )

        def fetch_option_quotes_range(
            self,
            underlying: str,
            *,
            start_expiration: str,
            end_expiration: str,
            option_type: str,
        ):
            self.range_requests.append((start_expiration, end_expiration))
            rows = []
            for expiration in pd.date_range(start_expiration, end_expiration, freq="14D"):
                expiry = expiration.strftime("%Y-%m-%d")
                rows.append(
                    {
                        "symbol": f"US.AAPL{expiry.replace('-', '')}P250000",
                        "option_type": "PUT",
                        "expiry": expiry,
                        "strike": 250.0,
                        "bid": 2.0,
                        "ask": 2.2,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.45,
                        "delta": -0.25,
                    }
                )
            return pd.DataFrame(rows)

    provider = RangeProvider()
    result = run_options_screener(
        provider=provider,
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            min_dte=5,
            max_dte=60,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert provider.range_requests == [("2026-05-08", "2026-06-05")]
    assert result.expiration_count == 4


def test_options_screener_applies_market_regime_to_sell_put() -> None:
    from quant_system.options.market_regime import VixRegimeSnapshot

    panic = VixRegimeSnapshot(
        volatility_regime="Panic",
        w_vix=0.35,
        vix_density=0.6,
        term_ratio=1.05,
        vix_mean=30.0,
        vix_threshold=22.0,
    )
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
        market_regime=panic,
    )

    assert result.market_regime == "Panic"
    assert result.market_regime_penalty == -40.0
    assert result.market_regime_w_vix == 0.35
    candidate = result.candidates[0]
    assert candidate.market_regime == "Panic"
    assert candidate.market_regime_penalty == -40.0
    # Panic + sell_put forces rating to Avoid even when other criteria pass.
    assert candidate.rating == "Avoid"
    assert any("market regime is Panic" in note for note in candidate.notes)


def test_options_screener_no_regime_means_no_penalty() -> None:
    result = run_options_screener(
        provider=_FakeProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            min_iv=0.2,
            max_delta=0.35,
            min_premium=1.0,
            max_spread_pct=0.2,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.market_regime is None
    assert result.market_regime_penalty == 0.0
    assert result.candidates[0].market_regime is None
    assert result.candidates[0].market_regime_penalty == 0.0
