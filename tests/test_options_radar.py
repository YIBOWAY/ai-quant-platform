from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.iv_history import IvHistoryStore
from quant_system.options.models import OptionsScreenerConfig
from quant_system.options.radar import (
    OptionsRadarConfig,
    OptionsRadarReport,
    compute_global_score,
    run_options_radar,
)
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.universe import UniverseEntry


class _RadarProvider:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()

    @staticmethod
    def normalize_symbol(symbol: str):
        normalized = symbol.upper()
        return normalized, f"US.{normalized}"

    def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
        if underlying in self.failing:
            raise RuntimeError("opend_unavailable")
        return pd.DataFrame(
            [
                {"strike_time": "2026-05-22", "option_expiry_date_distance": 19},
                {"strike_time": "2026-06-19", "option_expiry_date_distance": 47},
            ]
        )

    def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
        strike = 95.0 if option_type == "PUT" else 105.0
        return pd.DataFrame(
            [
                {
                    "symbol": f"US.{underlying}260522{option_type[0]}095000",
                    "option_type": option_type,
                    "expiry": expiration,
                    "strike": strike,
                    "bid": 1.0,
                    "ask": 1.1,
                    "volume": 100,
                    "open_interest": 500,
                    "implied_volatility": 0.32,
                    "delta": -0.25 if option_type == "PUT" else 0.24,
                }
            ]
        )

    def fetch_underlying_snapshot(self, symbol: str):
        return {"symbol": f"US.{symbol}", "last": 100.0, "market_val": 10_000_000_000}

    def fetch_ohlcv(self, symbols: list[str], *, start: str, end: str, interval: str = "1d"):
        rows = []
        for index, timestamp in enumerate(pd.date_range(start=start, end=end, freq="B", tz="UTC")):
            price = 90.0 + index * 0.2
            rows.append(
                {
                    "symbol": symbols[0],
                    "timestamp": timestamp,
                    "open": price,
                    "high": price + 1,
                    "low": price - 1,
                    "close": price,
                    "volume": 1_000_000,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp,
                }
            )
        return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="futu", interval=interval)


def _universe() -> list[UniverseEntry]:
    return [
        UniverseEntry("AAA", "AAA Inc.", "Technology", "US", "both"),
        UniverseEntry("BBB", "BBB Inc.", "Healthcare", "US", "sp500"),
        UniverseEntry("FAIL", "Broken Inc.", "Financials", "US", "sp500"),
    ]


def test_run_options_radar_isolates_ticker_failures_and_sorts(tmp_path: Path) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    for index in range(30):
        history.append("AAA", current_iv=0.10 + index * 0.005, run_date=f"2026-03-{index + 1:02d}")
        history.append("BBB", current_iv=0.20 + index * 0.002, run_date=f"2026-03-{index + 1:02d}")
    calendar = EarningsCalendar({"BBB": [date(2026, 5, 8)]})

    report = run_options_radar(
        provider=_RadarProvider(failing={"FAIL"}),
        universe=_universe(),
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=7,
                max_dte=60,
                min_apr=0,
                min_open_interest=1,
                avoid_earnings_within_days=10,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=3,
            top_per_ticker=1,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=calendar,
        run_date="2026-05-03",
    )

    assert report.universe_size == 3
    assert report.scanned_tickers == 2
    assert report.failed_tickers == [("FAIL", "RuntimeError")]
    assert {candidate.ticker for candidate in report.candidates} == {"AAA", "BBB"}
    assert report.candidates == sorted(
        report.candidates,
        key=lambda item: (
            -item.global_score,
            -(item.candidate.annualized_yield or 0.0),
            item.candidate.spread_pct or 0.0,
        ),
    )
    assert any(candidate.earnings_in_window for candidate in report.candidates)


def test_compute_global_score_penalizes_wide_spread_and_earnings() -> None:
    strong = compute_global_score(
        rating="Strong",
        annualized_yield=0.20,
        iv_rank=80,
        earnings_in_window=False,
        spread_pct=0.05,
    )
    risky = compute_global_score(
        rating="Strong",
        annualized_yield=0.20,
        iv_rank=80,
        earnings_in_window=True,
        spread_pct=0.20,
    )

    assert strong > risky


def test_radar_snapshot_store_writes_idempotent_jsonl(tmp_path: Path) -> None:
    report = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=7,
                max_dte=60,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=1,
            top_per_ticker=1,
            strategies=("sell_put",),
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-05-03",
    )
    store = RadarSnapshotStore(tmp_path / "scans")

    first = store.write(report)
    second = store.write(report)
    loaded = store.read("2026-05-03")

    assert first == second
    assert len(loaded.candidates) == 1
    assert loaded.candidates[0].ticker == "AAA"
    assert store.list_dates() == ["2026-05-03"]
