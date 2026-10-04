from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from quant_system.data.providers.futu import FutuProviderError
from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.iv_history import IvHistoryStore, compute_iv_rank
from quant_system.options.market_regime import VixRegimeSnapshot
from quant_system.options.models import OptionsScreenerCandidate, OptionsScreenerConfig
from quant_system.options.radar import (
    OptionsRadarCandidate,
    OptionsRadarConfig,
    _radar_sort_key,
    compute_global_score,
)
from quant_system.options.radar import (
    run_options_radar as _run_options_radar,
)
from quant_system.options.radar_storage import RadarSnapshotStore
from quant_system.options.seller_score import (
    SellerScoreBreakdown,
    is_us_market_session,
    latest_us_market_session,
)
from quant_system.options.universe import UniverseEntry


def run_options_radar(**kwargs):
    active_run_date = kwargs.get("run_date") or date.today().isoformat()
    provider = kwargs["provider"]
    provider._test_market_session = latest_us_market_session(  # noqa: SLF001
        date.fromisoformat(active_run_date)
    ).isoformat()
    return _run_options_radar(**kwargs)


class _RadarProvider:
    provider_name = "futu"

    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()

    @staticmethod
    def normalize_symbol(symbol: str):
        normalized = symbol.upper()
        return normalized, f"US.{normalized}"

    def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
        if underlying in self.failing:
            raise FutuProviderError("rate_limited", "Futu quote rate limit")
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
                    "symbol": (
                        f"US.{underlying}{expiration.replace('-', '')}"
                        f"{option_type[0]}{int(strike * 1000):06d}"
                    ),
                    "underlying": f"US.{underlying}",
                    "option_type": option_type,
                    "expiry": expiration,
                    "strike": strike,
                    "bid": 3.0,
                    "ask": 3.04,
                    "volume": 100,
                    "open_interest": 500,
                    "implied_volatility": 0.32,
                    "delta": -0.25 if option_type == "PUT" else 0.24,
                    "update_time": "2026-05-01T20:00:00Z",
                }
            ]
        )

    def fetch_option_quotes_range(
        self,
        underlying: str,
        *,
        start_expiration: str,
        end_expiration: str,
        option_type: str = "ALL",
    ) -> pd.DataFrame:
        if underlying in self.failing:
            raise FutuProviderError("rate_limited", "Futu quote rate limit")
        if option_type in {"CALL", "PUT"}:
            expirations = self.fetch_option_expirations(underlying)["strike_time"].astype(str)
            frames = [
                self.fetch_option_quotes(
                    underlying,
                    expiration=expiration,
                    option_type=option_type,
                )
                for expiration in expirations
                if start_expiration <= expiration <= end_expiration
            ]
            return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        assert option_type == "ALL"
        range_start = date.fromisoformat(start_expiration)
        quote_session = latest_us_market_session(range_start - timedelta(days=20))
        expiry = (range_start + timedelta(days=8)).isoformat()
        expiry_code = date.fromisoformat(expiry).strftime("%y%m%d")
        return pd.DataFrame(
            [
                {
                    "symbol": f"US.{underlying}{expiry_code}C100000",
                    "underlying": f"US.{underlying}",
                    "option_type": "CALL",
                    "expiry": expiry,
                    "strike": 100.0,
                    "bid": 3.0,
                    "ask": 3.1,
                    "implied_volatility": 0.32,
                    "update_time": f"{quote_session.isoformat()} 15:59:00",
                },
                {
                    "symbol": f"US.{underlying}{expiry_code}P100000",
                    "underlying": f"US.{underlying}",
                    "option_type": "PUT",
                    "expiry": expiry,
                    "strike": 100.0,
                    "bid": 2.9,
                    "ask": 3.0,
                    "implied_volatility": 0.32,
                    "update_time": f"{quote_session.isoformat()} 15:59:00",
                },
            ]
        )

    def fetch_underlying_snapshot(self, symbol: str):
        session = getattr(self, "_test_market_session", "2026-05-01")
        return {
            "symbol": f"US.{symbol}",
            "last": 100.0,
            "market_val": 10_000_000_000,
            "update_time": f"{session} 15:59:00",
        }

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


def _seed_iv_history(
    history: IvHistoryStore,
    ticker: str,
    *,
    base_iv: float,
    step: float,
    sample_count: int = 30,
) -> None:
    active = date(2026, 3, 2)
    index = 0
    while index < sample_count:
        if is_us_market_session(active):
            session = active.isoformat()
            history.append(
                ticker,
                current_iv=base_iv + index * step,
                run_date=session,
                quote_as_of=f"{session} 15:59:00",
                provider="futu",
            )
            index += 1
        active += timedelta(days=1)


def test_run_options_radar_keeps_successful_candidates_when_one_ticker_fails(
    tmp_path: Path,
) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)
    _seed_iv_history(history, "BBB", base_iv=0.20, step=0.002)
    calendar = EarningsCalendar(
        {
            "AAA": [date(2026, 6, 15)],
            "BBB": [date(2026, 5, 8)],
        }
    )
    progress: list[tuple[int, int]] = []

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
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=calendar,
        run_date="2026-05-03",
        progress_callback=lambda scanned, total: progress.append((scanned, total)),
    )

    assert report.universe_size == 3
    assert report.scanned_tickers == 2
    assert report.failed_tickers == [("FAIL", "FutuProviderError:rate_limited")]
    assert report.status == "available"
    assert report.candidates
    assert {candidate.ticker for candidate in report.candidates} == {"AAA"}
    assert report.shortfall_reasons["universe_scan_incomplete"] == 1
    assert report.shortfall_reasons["earnings_within_dte"] == 3
    assert progress == [(1, 3), (2, 3), (3, 3)]

    RadarSnapshotStore(tmp_path / "snapshots").write(report)
    loaded = RadarSnapshotStore(tmp_path / "snapshots").read(report.run_date)
    assert loaded.status == "available"
    assert loaded.scanned_tickers == 2
    assert loaded.failed_tickers == [("FAIL", "FutuProviderError:rate_limited")]
    assert {candidate.ticker for candidate in loaded.candidates} == {"AAA"}


def test_run_options_radar_binds_requested_universe_when_input_is_short(
    tmp_path: Path,
) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)
    _seed_iv_history(history, "BBB", base_iv=0.20, step=0.002)

    report = run_options_radar(
        provider=_RadarProvider(),
        universe=[
            UniverseEntry("AAA", "AAA ETF", "ETF", "US", "core_etf"),
            UniverseEntry("BBB", "BBB ETF", "ETF", "US", "core_etf"),
        ],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=3,
            strategies=("sell_put",),
            risk_free_rate=0.0387,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-05-03",
    )

    assert report.universe_size == 3
    assert report.expected_universe_size == 3
    assert report.scanned_tickers == 2
    assert report.status == "available"
    assert {candidate.ticker for candidate in report.candidates} == {"AAA", "BBB"}
    assert report.shortfall_reasons["universe_scan_incomplete"] == 1


def test_run_options_radar_passes_market_regime_into_screener(tmp_path: Path) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)
    report = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=7,
                max_dte=60,
                max_delta=0.8,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
        market_regime=VixRegimeSnapshot(
            volatility_regime="Elevated",
            w_vix=0.75,
            vix_density=0.4,
            term_ratio=0.98,
            vix_mean=23.0,
            vix_threshold=20.0,
        ),
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.market_regime == "Elevated"
    assert candidate.market_regime_penalty == -15.0
    assert candidate.candidate.market_regime == "Elevated"
    assert candidate.candidate.market_regime_penalty == -15.0
    assert candidate.candidate.seller_score is not None
    assert candidate.global_score == candidate.candidate.seller_score.composite


def test_friday_quote_contributes_one_iv_observation_across_weekend(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "iv_history"
    config = OptionsRadarConfig(
        base_screen_config=OptionsScreenerConfig(
            min_dte=5,
            max_dte=60,
            trend_filter=False,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        universe_top_n=1,
        strategies=("sell_put",),
        risk_free_rate=0.04,
    )
    calendar = EarningsCalendar({"AAA": [date(2026, 6, 15)]})

    friday = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=history_dir,
        earnings_calendar=calendar,
        run_date="2026-05-01",
    )
    path = history_dir / "AAA.atm30_straddle_iv_v1.sessions.jsonl"
    friday_bytes = path.read_bytes()
    friday_payload = json.loads(path.read_text(encoding="utf-8"))
    saturday = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=history_dir,
        earnings_calendar=calendar,
        run_date="2026-05-02",
    )

    assert path.read_bytes() == friday_bytes
    assert friday_payload["measure"] == "atm30_straddle_iv_v1"
    assert IvHistoryStore(history_dir).read_values("AAA") == [0.32]
    assert "quote_stale" not in friday.shortfall_reasons
    assert "quote_stale" not in saturday.shortfall_reasons
    assert "quote_future" not in saturday.shortfall_reasons


def test_stale_quote_is_not_recommended_or_written_to_iv_history(
    tmp_path: Path,
) -> None:
    class StaleQuoteProvider(_RadarProvider):
        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame([{"strike_time": "2026-09-18", "option_expiry_date_distance": 28}])

        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": f"US.{underlying}260918P095000",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": 95.0,
                        "bid": 3.0,
                        "ask": 3.04,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.32,
                        "delta": -0.25,
                        "update_time": "2026-07-02 09:30:00",
                    }
                ]
            )

    history_dir = tmp_path / "iv_history"
    report = run_options_radar(
        provider=StaleQuoteProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-08-20",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=history_dir,
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 10, 15)]}),
        run_date="2026-08-21",
    )

    assert report.candidates == []
    assert report.shortfall_reasons["quote_stale"] == 1
    assert IvHistoryStore(history_dir).read_values("AAA") == []
    assert not (history_dir / "AAA.atm30_straddle_iv_v1.sessions.jsonl").exists()


def test_stale_underlying_snapshot_stops_atm30_and_history_write(
    tmp_path: Path,
) -> None:
    class StaleUnderlyingProvider(_RadarProvider):
        def fetch_underlying_snapshot(self, symbol: str):
            return {
                "symbol": f"US.{symbol}",
                "last": 100.0,
                "update_time": "2026-07-02 15:59:00",
            }

        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame([{"strike_time": "2026-09-18", "option_expiry_date_distance": 28}])

        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": f"US.{underlying}260918P095000",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": 95.0,
                        "bid": 3.0,
                        "ask": 3.04,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.32,
                        "delta": -0.25,
                        "update_time": "2026-08-21 15:59:00",
                    }
                ]
            )

    history_dir = tmp_path / "iv_history"
    report = run_options_radar(
        provider=StaleUnderlyingProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-08-20",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=history_dir,
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 10, 15)]}),
        run_date="2026-08-21",
    )

    assert report.candidates == []
    assert report.scanned_tickers == 0
    assert report.failed_tickers == [("AAA", "ValueError")]
    assert not (history_dir / "AAA.atm30_straddle_iv_v1.sessions.jsonl").exists()


def test_quote_after_scan_start_but_before_provider_response_is_valid(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class ResponseTimedProvider(_RadarProvider):
        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame([{"strike_time": "2026-09-18", "option_expiry_date_distance": 28}])

        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": f"US.{underlying}260918P095000",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": 95.0,
                        "bid": 3.0,
                        "ask": 3.04,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.32,
                        "delta": -0.25,
                        "update_time": "2026-08-21T20:01:00Z",
                    }
                ]
            )

    times = iter(
        [
            "2026-08-21T19:00:00Z",
            "2026-08-21T20:00:00Z",
            "2026-08-21T20:02:00Z",
            "2026-08-21T20:03:00Z",
        ]
    )
    monkeypatch.setattr("quant_system.options.radar._utc_now", lambda: next(times))
    history_dir = tmp_path / "iv_history"
    _seed_iv_history(
        IvHistoryStore(history_dir),
        "AAA",
        base_iv=0.10,
        step=0.005,
    )

    report = run_options_radar(
        provider=ResponseTimedProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-08-20",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=history_dir,
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 10, 15)]}),
        run_date="2026-08-21",
    )

    assert "quote_future" not in report.shortfall_reasons
    assert report.scanned_tickers == 1
    assert len(IvHistoryStore(history_dir).read_values("AAA")) == 31


def test_quote_after_provider_response_is_future_and_zero_iv_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FutureQuoteProvider(_RadarProvider):
        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame([{"strike_time": "2026-09-18", "option_expiry_date_distance": 28}])

        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": f"US.{underlying}260918P095000",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": 95.0,
                        "bid": 3.0,
                        "ask": 3.04,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.32,
                        "delta": -0.25,
                        "update_time": "2026-08-21T20:03:00Z",
                    }
                ]
            )

    times = iter(
        [
            "2026-08-21T19:00:00Z",
            "2026-08-21T20:00:00Z",
            "2026-08-21T20:02:00Z",
            "2026-08-21T20:04:00Z",
        ]
    )
    monkeypatch.setattr("quant_system.options.radar._utc_now", lambda: next(times))
    history_dir = tmp_path / "iv_history"
    report = run_options_radar(
        provider=FutureQuoteProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-08-20",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=history_dir,
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 10, 15)]}),
        run_date="2026-08-21",
    )

    assert report.candidates == []
    assert report.shortfall_reasons["quote_future"] == 1
    assert IvHistoryStore(history_dir).read_values("AAA") == []
    assert not (history_dir / "AAA.atm30_straddle_iv_v1.sessions.jsonl").exists()


def test_weekend_raw_window_keeps_session_dte_five_and_rejects_four(
    tmp_path: Path,
) -> None:
    class WeekendBoundaryProvider(_RadarProvider):
        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {"strike_time": "2026-08-25", "option_expiry_date_distance": 3},
                    {"strike_time": "2026-08-26", "option_expiry_date_distance": 4},
                ]
            )

        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": f"US.{underlying}{expiration.replace('-', '')}P095000",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": 95.0,
                        "bid": 3.0,
                        "ask": 3.04,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.30,
                        "delta": -0.20,
                        "update_time": "2026-08-21 12:00:00",
                    }
                ]
            )

    history_dir = tmp_path / "iv_history"
    _seed_iv_history(
        IvHistoryStore(history_dir),
        "AAA",
        base_iv=0.10,
        step=0.005,
    )
    report = run_options_radar(
        provider=WeekendBoundaryProvider(),
        universe=[UniverseEntry("AAA", "AAA ETF", "ETF", "US", "core_etf")],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-08-20",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.0387,
        ),
        iv_history_dir=history_dir,
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-08-22",
    )

    assert [item.candidate.expiry for item in report.candidates] == ["2026-08-26"]
    assert report.candidates[0].candidate.days_to_expiry == 5


def _candidate_with_seller_score(
    *,
    composite: float,
    rating: str = "Watch",
) -> OptionsScreenerCandidate:
    return OptionsScreenerCandidate(
        symbol="US.AAA260522P095000",
        underlying="AAA",
        strategy_type="sell_put",
        option_type="PUT",
        expiry="2026-05-22",
        strike=95.0,
        underlying_price=100.0,
        rating=rating,
        seller_score=SellerScoreBreakdown(
            composite=composite,
            weights_used={"yield": 0.30, "liquidity": 0.25},
        ),
    )


def test_compute_global_score_uses_seller_composite_minus_earnings() -> None:
    candidate = _candidate_with_seller_score(composite=80.0)
    assert candidate.seller_score is not None
    assert (
        compute_global_score(
            seller_composite=candidate.seller_score.composite,
            earnings_in_window=True,
        )
        == 65.0
    )
    assert (
        compute_global_score(
            seller_composite=candidate.seller_score.composite,
            earnings_in_window=False,
        )
        == 80.0
    )


def test_radar_sort_uses_recommendation_score_not_legacy_rating() -> None:
    avoid = OptionsRadarCandidate(
        ticker="ZZZ",
        sector=None,
        strategy="sell_put",
        candidate=_candidate_with_seller_score(composite=90.0, rating="Avoid"),
        iv_rank=80.0,
        earnings_in_window=False,
        global_score=90.0,
        iv_history_samples=30,
        iv_rank_status="ready",
        recommendation_score=0.20,
    )
    watch = OptionsRadarCandidate(
        ticker="AAA",
        sector=None,
        strategy="sell_put",
        candidate=_candidate_with_seller_score(composite=40.0, rating="Watch"),
        iv_rank=20.0,
        earnings_in_window=False,
        global_score=40.0,
        iv_history_samples=30,
        iv_rank_status="ready",
        recommendation_score=0.10,
    )

    ranked = sorted([avoid, watch], key=_radar_sort_key)

    assert [row.candidate.rating for row in ranked] == ["Avoid", "Watch"]


def test_radar_keeps_two_best_contracts_per_ticker_before_global_limit(tmp_path: Path) -> None:
    class ManyContracts(_RadarProvider):
        def fetch_option_quotes(self, underlying, *, expiration, option_type):
            original = super().fetch_option_quotes(
                underlying, expiration=expiration, option_type=option_type,
            )
            rows = []
            for strike in (95.0, 94.0, 93.0, 92.0):
                row = original.iloc[0].to_dict()
                row.update(
                    strike=strike,
                    symbol=f"US.{underlying}{date.fromisoformat(expiration):%y%m%d}"
                    f"P{int(strike * 1000)}",
                )
                rows.append(row)
            return pd.DataFrame(rows)

    report = run_options_radar(
        provider=ManyContracts(),
        universe=[
            UniverseEntry(ticker, ticker, "ETF", "US", "core_etf") for ticker in ("AAA", "BBB")
        ],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(min_dte=5, max_dte=60, trend_filter=False),
            universe_top_n=2,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv",
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-05-03",
    )

    assert report.status == "available"
    assert len(report.candidates) == 4
    assert all(
        sum(row.ticker == ticker for row in report.candidates) == 2 for ticker in ("AAA", "BBB")
    )
    assert report.candidates == sorted(report.candidates, key=_radar_sort_key)
    assert report.shortfall_count == 16


def test_radar_snapshot_store_commits_new_generation_for_same_day(tmp_path: Path) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)
    report = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=7,
                max_dte=60,
                max_delta=0.8,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )
    store = RadarSnapshotStore(tmp_path / "scans")

    first = store.write(report)
    second = store.write(report)
    loaded = store.read("2026-05-03")

    assert first[0] != second[0]
    assert first[1] == second[1]
    assert first[0].exists()
    assert second[0].exists()
    current_meta = json.loads(second[1].read_text(encoding="utf-8"))
    assert current_meta["data_file"] == second[0].name
    assert len(loaded.candidates) == 1
    assert loaded.candidates[0].ticker == "AAA"
    assert store.list_dates() == ["2026-05-03"]


def test_radar_snapshot_store_replaces_same_day_snapshot(tmp_path: Path) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)
    _seed_iv_history(history, "BBB", base_iv=0.20, step=0.002)
    config = OptionsRadarConfig(
        base_screen_config=OptionsScreenerConfig(
            min_dte=7,
            max_dte=60,
            max_delta=0.8,
            trend_filter=False,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        universe_top_n=1,
        strategies=("sell_put",),
        risk_free_rate=0.04,
    )
    store = RadarSnapshotStore(tmp_path / "scans")
    first = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )
    second = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[1:2],
        config=config,
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"BBB": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )

    store.write(first)
    store.write(second)
    loaded = store.read("2026-05-03")

    assert len(loaded.candidates) == 1
    assert loaded.candidates[0].ticker == "BBB"


def test_radar_without_risk_free_rate_is_unavailable_without_provider_calls(
    tmp_path: Path,
) -> None:
    class ProviderMustNotRun:
        provider_name = "futu"

        def __getattr__(self, name: str):
            raise AssertionError(f"provider call was not expected: {name}")

    report = run_options_radar(
        provider=ProviderMustNotRun(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(risk_free_rate=None),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-05-03",
    )

    assert report.provider == "futu"
    assert report.status == "unavailable"
    assert report.risk_free_rate is None
    assert report.as_of is None
    assert report.scanned_tickers == 0
    assert report.candidates == []
    assert report.shortfall_count == 20
    assert report.shortfall_reasons == {"risk_free_rate_missing": 1}


def test_radar_returns_only_hard_gate_passed_ev_recommendations(tmp_path: Path) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)

    report = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                max_delta=0.35,
                min_open_interest=100,
                max_spread_pct=0.05,
                min_mid_price=0.05,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )

    assert report.provider == "futu"
    assert report.status == "available"
    assert report.risk_free_rate == 0.04
    assert len(report.candidates) == 1
    recommendation = report.candidates[0]
    assert recommendation.hard_gate_passed is True
    assert recommendation.recommendation_score is not None
    assert recommendation.recommendation_score_model == "seller_ev_liquidity_v1"
    assert recommendation.gross_annualized_yield is not None
    assert recommendation.pop == 0.75
    assert recommendation.otm_pct == 0.05
    assert recommendation.manage_at_21_dte == "2026-05-01"
    assert recommendation.candidate.seller_score is not None
    assert recommendation.global_score == recommendation.candidate.seller_score.composite


def test_radar_recommends_while_iv_rank_history_is_warming(tmp_path: Path) -> None:
    report = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                max_delta=0.35,
                min_open_interest=100,
                max_spread_pct=0.05,
                min_mid_price=0.05,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )

    assert report.status == "available"
    assert len(report.candidates) == 1
    recommendation = report.candidates[0]
    assert recommendation.iv_rank is None
    assert recommendation.candidate.iv_rank is None
    assert recommendation.iv_history_samples == 1
    assert recommendation.iv_rank_status == "warming"

    RadarSnapshotStore(tmp_path / "snapshots").write(report)
    loaded = RadarSnapshotStore(tmp_path / "snapshots").read(report.run_date)
    assert loaded.status == "available"
    assert loaded.candidates[0].iv_rank is None
    assert loaded.candidates[0].iv_history_samples == 1
    assert loaded.candidates[0].iv_rank_status == "warming"


def test_radar_marks_iv_rank_ready_on_the_thirtieth_session(tmp_path: Path) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(
        history,
        "AAA",
        base_iv=0.10,
        step=0.005,
        sample_count=29,
    )

    report = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )

    recommendation = report.candidates[0]
    assert recommendation.iv_history_samples == 30
    assert recommendation.iv_rank_status == "ready"
    assert recommendation.iv_rank is not None


def test_same_session_refresh_uses_monotonic_effective_iv_history(tmp_path: Path) -> None:
    class RefreshProvider(_RadarProvider):
        def __init__(self, *, atm_iv: float, atm_quote_as_of: str) -> None:
            super().__init__()
            self.atm_iv = atm_iv
            self.atm_quote_as_of = atm_quote_as_of

        def fetch_option_quotes_range(
            self,
            underlying: str,
            *,
            start_expiration: str,
            end_expiration: str,
            option_type: str = "ALL",
        ) -> pd.DataFrame:
            if option_type != "ALL":
                return super().fetch_option_quotes_range(
                    underlying,
                    start_expiration=start_expiration,
                    end_expiration=end_expiration,
                    option_type=option_type,
                )
            return pd.DataFrame(
                [
                    {
                        "symbol": f"US.{underlying}260522C100000",
                        "underlying": f"US.{underlying}",
                        "option_type": "CALL",
                        "expiry": "2026-05-22",
                        "strike": 100.0,
                        "bid": 3.0,
                        "ask": 3.1,
                        "implied_volatility": self.atm_iv,
                        "update_time": self.atm_quote_as_of,
                    },
                    {
                        "symbol": f"US.{underlying}260522P100000",
                        "underlying": f"US.{underlying}",
                        "option_type": "PUT",
                        "expiry": "2026-05-22",
                        "strike": 100.0,
                        "bid": 2.9,
                        "ask": 3.0,
                        "implied_volatility": self.atm_iv,
                        "update_time": self.atm_quote_as_of,
                    },
                ]
            )

    history_dir = tmp_path / "iv_history"
    history = IvHistoryStore(history_dir)
    _seed_iv_history(
        history,
        "AAA",
        base_iv=0.10,
        step=0.005,
        sample_count=29,
    )
    config = OptionsRadarConfig(
        base_screen_config=OptionsScreenerConfig(
            min_dte=5,
            max_dte=60,
            trend_filter=False,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        universe_top_n=1,
        strategies=("sell_put",),
        risk_free_rate=0.04,
    )
    calendar = EarningsCalendar({"AAA": [date(2026, 6, 15)]})

    first = run_options_radar(
        provider=RefreshProvider(
            atm_iv=0.30,
            atm_quote_as_of="2026-05-01 15:55:00",
        ),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=history_dir,
        earnings_calendar=calendar,
        run_date="2026-05-03",
    )
    newer = run_options_radar(
        provider=RefreshProvider(
            atm_iv=0.20,
            atm_quote_as_of="2026-05-01 15:59:00",
        ),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=history_dir,
        earnings_calendar=calendar,
        run_date="2026-05-03",
    )
    older = run_options_radar(
        provider=RefreshProvider(
            atm_iv=0.35,
            atm_quote_as_of="2026-05-01 15:50:00",
        ),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=history_dir,
        earnings_calendar=calendar,
        run_date="2026-05-03",
    )

    assert first.candidates[0].iv_rank != newer.candidates[0].iv_rank
    effective_rank = compute_iv_rank(
        "AAA",
        0.20,
        history_dir=history_dir,
        as_of_session="2026-05-01",
    )
    assert newer.candidates[0].iv_rank == effective_rank
    assert older.candidates[0].iv_rank == effective_rank
    assert history.read_values("AAA", as_of_session="2026-05-01")[-1] == 0.20
    store = RadarSnapshotStore(tmp_path / "snapshots")
    store.write(newer)
    store.write(older)
    persisted = store.read("2026-05-03")
    assert persisted.status == "available"
    assert persisted.candidates[0].iv_rank == effective_rank


def test_radar_evaluates_full_raw_set_then_keeps_global_ev_top20(tmp_path: Path) -> None:
    class ManyContractProvider(_RadarProvider):
        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame([{"strike_time": "2026-06-02", "option_expiry_date_distance": 30}])

        def fetch_ohlcv(self, symbols: list[str], *, start: str, end: str, interval: str = "1d"):
            # Alternating +-4% closes give HV ~1.27, so the physical EV payout
            # for the IV=1.0 rows uses sigma=min(IV, HV)=1.0 and stays punitive.
            rows = []
            sessions = pd.date_range(start=start, end=end, freq="B", tz="UTC")
            for index, timestamp in enumerate(sessions):
                price = 100.0 * (1.04 if index % 2 else 1 / 1.04)
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

        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            rows = []
            for index in range(1001):
                mid = 3.0
                strike = 95.0 + index / 1000.0
                rows.append(
                    {
                        "symbol": f"US.{underlying}260602P{int(round(strike * 1000)):06d}",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": strike,
                        "bid": mid - 0.01,
                        "ask": mid + 0.01,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.05 if index == 1000 else 1.0,
                        "delta": -0.20,
                        "update_time": "2026-05-01T20:00:00Z",
                    }
                )
            return pd.DataFrame(rows)

    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)

    report = run_options_radar(
        provider=ManyContractProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            strategies=("sell_put",),
            universe_top_n=1,
            max_recommendations=20,
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )

    assert len(report.candidates) == 1
    assert report.candidates[0].candidate.symbol == "US.AAA260602P096000"
    assert report.candidates[0].candidate.implied_volatility == 0.05


def test_fresh_eligible_quote_stays_available_with_unrelated_stale_row(
    tmp_path: Path,
) -> None:
    class MixedFreshnessProvider(_RadarProvider):
        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame([{"strike_time": "2026-06-02", "option_expiry_date_distance": 30}])

        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": "US.AAA260602P095000",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": 95.0,
                        "bid": 3.0,
                        "ask": 3.04,
                        "open_interest": 500,
                        "implied_volatility": 0.30,
                        "delta": -0.20,
                        "update_time": "2026-05-01T20:00:00Z",
                    },
                    {
                        "symbol": "US.AAA260602P094000",
                        "underlying": f"US.{underlying}",
                        "option_type": option_type,
                        "expiry": expiration,
                        "strike": 94.0,
                        "bid": 0.79,
                        "ask": 0.81,
                        "open_interest": 99,
                        "implied_volatility": 0.30,
                        "delta": -0.20,
                        "update_time": "2026-03-02T19:00:00Z",
                    },
                ]
            )

    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)

    report = run_options_radar(
        provider=MixedFreshnessProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            strategies=("sell_put",),
            universe_top_n=1,
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )

    assert len(report.candidates) == 1
    assert report.as_of == "2026-05-01T20:00:00Z"
    assert report.shortfall_reasons["quote_stale"] == 1


def test_sample_provider_report_never_claims_available(tmp_path: Path) -> None:
    class SampleNamedProvider(_RadarProvider):
        provider_name = "sample"

    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)

    report = run_options_radar(
        provider=SampleNamedProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            strategies=("sell_put",),
            universe_top_n=1,
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({"AAA": [date(2026, 6, 15)]}),
        run_date="2026-05-03",
    )

    assert report.candidates
    assert report.provider == "sample"
    assert report.status == "unavailable"
    assert len(history.read_values("AAA")) == 30


def test_all_futu_ticker_failures_are_unavailable_without_market_as_of(
    tmp_path: Path,
) -> None:
    report = run_options_radar(
        provider=_RadarProvider(failing={"AAA", "BBB", "FAIL"}),
        universe=_universe(),
        config=OptionsRadarConfig(
            strategies=("sell_put",),
            universe_top_n=3,
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-05-03",
    )

    assert report.provider == "futu"
    assert report.status == "unavailable"
    assert report.scanned_tickers == 0
    assert len(report.failed_tickers) == 3
    assert report.candidates == []
    assert report.as_of is None
    assert report.shortfall_count == 20
    assert report.shortfall_reasons["ticker_scan_failed"] == 3


def test_etf_recommendation_treats_earnings_as_not_applicable(tmp_path: Path) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)

    report = run_options_radar(
        provider=_RadarProvider(),
        universe=[UniverseEntry("AAA", "AAA ETF", "ETF", "US", "core_etf")],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            strategies=("sell_put",),
            universe_top_n=1,
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-05-03",
    )

    assert report.status == "available"
    assert report.candidates
    assert "earnings_data_missing" not in report.shortfall_reasons


def test_covered_call_requires_dividend_evidence_then_applies_extrinsic_gate(
    tmp_path: Path,
) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)
    config = OptionsRadarConfig(
        base_screen_config=OptionsScreenerConfig(
            min_dte=5,
            max_dte=60,
            trend_filter=False,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        strategies=("covered_call",),
        universe_top_n=1,
        risk_free_rate=0.04,
    )
    calendar = EarningsCalendar({"AAA": [date(2026, 6, 30)]})

    missing = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=calendar,
        run_date="2026-05-03",
    )
    available = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=calendar,
        run_date="2026-05-03",
        dividend_events={"AAA": (date(2026, 5, 15), 0.50)},
    )

    assert missing.status == "empty"
    assert missing.shortfall_reasons["ex_dividend_data_missing"] == 2
    RadarSnapshotStore(tmp_path / "empty-snapshot").write(missing)
    persisted_missing = RadarSnapshotStore(tmp_path / "empty-snapshot").read(
        missing.run_date
    )
    assert persisted_missing.status == "empty"
    assert persisted_missing.shortfall_reasons["ex_dividend_data_missing"] == 2
    assert available.status == "available"
    assert len(available.candidates) == 2
    recommendation = available.candidates[0]
    assert recommendation.ex_dividend_date == "2026-05-15"
    assert recommendation.ex_dividend_in_window is True
    assert recommendation.dividend_per_share == 0.50
    assert recommendation.extrinsic_value is not None
    assert recommendation.extrinsic_value > recommendation.dividend_per_share


def test_covered_call_no_dividend_assertion_replaces_missing_evidence(
    tmp_path: Path,
) -> None:
    history = IvHistoryStore(tmp_path / "iv_history")
    _seed_iv_history(history, "AAA", base_iv=0.10, step=0.005)
    config = OptionsRadarConfig(
        base_screen_config=OptionsScreenerConfig(
            min_dte=5,
            max_dte=60,
            trend_filter=False,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        strategies=("covered_call",),
        universe_top_n=1,
        risk_free_rate=0.04,
    )
    calendar = EarningsCalendar({"AAA": [date(2026, 6, 30)]})

    asserted = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=calendar,
        run_date="2026-05-03",
        dividend_events={"AAA": (None, 0.0)},
    )
    unknown_amount = run_options_radar(
        provider=_RadarProvider(),
        universe=_universe()[:1],
        config=config,
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=calendar,
        run_date="2026-05-03",
        dividend_events={"AAA": (None, 0.50)},
    )

    assert asserted.status == "available"
    assert len(asserted.candidates) == 2
    assert all(candidate.ex_dividend_date is None for candidate in asserted.candidates)
    assert all(candidate.dividend_per_share == 0.0 for candidate in asserted.candidates)
    assert unknown_amount.candidates == []
    assert unknown_amount.shortfall_reasons["ex_dividend_data_missing"] == 2


def test_zero_screener_rows_persist_empty_with_atm_quote_watermark(tmp_path: Path) -> None:
    class NoContractRowsProvider(_RadarProvider):
        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            return pd.DataFrame(columns=["expiry"])

    report = run_options_radar(
        provider=NoContractRowsProvider(),
        universe=_universe()[:1],
        config=OptionsRadarConfig(
            base_screen_config=OptionsScreenerConfig(
                min_dte=5,
                max_dte=60,
                trend_filter=False,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            universe_top_n=1,
            strategies=("sell_put",),
            risk_free_rate=0.04,
        ),
        iv_history_dir=tmp_path / "iv_history",
        earnings_calendar=EarningsCalendar({}),
        run_date="2026-05-03",
    )

    assert report.status == "empty"
    assert report.candidates == []
    assert report.as_of == "2026-05-01T19:59:00Z"
    assert IvHistoryStore(tmp_path / "iv_history").read_values("AAA") == [0.32]
    store = RadarSnapshotStore(tmp_path / "snapshots")
    store.write(report)
    loaded = store.read(report.run_date)
    assert loaded.status == "empty"
    assert loaded.as_of == "2026-05-01T19:59:00Z"
