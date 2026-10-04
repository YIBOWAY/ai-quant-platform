from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.options.earnings_calendar import EarningsCalendar
from quant_system.options.iv_history import Atm30StraddleIvObservation, IvHistoryStore
from quant_system.options.models import (
    OptionsScreenerConfig,
    OptionsScreenerResult,
    StrategyType,
)
from quant_system.options.screener import (
    _candidate_notes,
    calculate_historical_volatility,
)
from quant_system.options.screener import (
    run_options_screener as _run_options_screener,
)
from quant_system.options.seller_score import is_us_market_session, latest_us_market_session


def run_options_screener(**kwargs) -> OptionsScreenerResult:
    active_run_date = kwargs.setdefault("run_date", "2026-05-01")
    provider = kwargs.get("provider")
    if provider is not None:
        provider._test_market_session = latest_us_market_session(  # noqa: SLF001
            date.fromisoformat(active_run_date)
        ).isoformat()
    return _run_options_screener(**kwargs)


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
                    "underlying": "US.AAPL",
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
                    "update_time": "2026-05-01 15:59:00",
                }
            ]
        )

    def fetch_underlying_snapshot(self, symbol: str):
        session = getattr(self, "_test_market_session", "2026-05-01")
        return {
            "symbol": "US.AAPL",
            "last": 280.0,
            "update_time": f"{session} 15:59:00",
        }

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


class _RecommendationProvider(_FakeProvider):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "strike_time": "2026-05-31",
                    "option_expiry_date_distance": 30,
                }
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
                    **row,
                    "underlying": "US.AAPL",
                    "option_type": option_type,
                    "expiry": expiration,
                    "update_time": "2026-05-01 16:00:00",
                }
                for row in self.rows
            ]
        )

    def fetch_underlying_snapshot(self, symbol: str):
        session = getattr(self, "_test_market_session", "2026-05-01")
        return {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": f"{session} 15:59:00",
        }


class _StaleQuoteProvider(_RecommendationProvider):
    """Same chain, but option quotes carry a 7-week-stale update_time — the
    2026-08-21 incident shape, where the scan consumed an old Futu snapshot."""

    def fetch_option_quotes(
        self,
        underlying: str,
        *,
        expiration: str,
        option_type: str,
    ) -> pd.DataFrame:
        frame = super().fetch_option_quotes(
            underlying, expiration=expiration, option_type=option_type
        )
        frame["update_time"] = "2026-03-10 16:00:00"
        return frame


def _recommendation_row(
    symbol: str,
    *,
    strike: float,
    bid: float,
    ask: float,
    implied_volatility: float,
    delta: float,
    volume: float = 250,
    open_interest: float = 500,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "volume": volume,
        "open_interest": open_interest,
        "implied_volatility": implied_volatility,
        "delta": delta,
    }


def _run_recommendation_screen(
    tmp_path: Path,
    *,
    rows: list[dict[str, object]],
    strategy_type: StrategyType = "sell_put",
    dividend_event: tuple[date, float] | None = None,
    provider: object | None = None,
) -> OptionsScreenerResult:
    history_dir = tmp_path / "iv-history"
    _seed_formal_iv_history(history_dir, ticker="AAPL")
    return run_options_screener(
        provider=provider if provider is not None else _RecommendationProvider(rows),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type=strategy_type,
            min_dte=5,
            max_dte=60,
            include_rejected=True,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        run_date="2026-05-01",
        risk_free_rate=0.04,
        iv_history_dir=history_dir,
        iv_observation=Atm30StraddleIvObservation(
            measure="atm30_straddle_iv_v1",
            current_iv=0.245,
            expiry="2026-05-31",
            strike=100.0,
            days_to_expiry=30,
            quote_as_of="2026-05-01T20:00:00Z",
            quote_session="2026-05-01",
        ),
        earnings_calendar=EarningsCalendar({"AAPL": [date(2026, 6, 15)]}),
        dividend_event=dividend_event,
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
    assert candidate.seller_score is not None
    assert candidate.seller_score.composite >= 0
    assert candidate.quote_as_of == "2026-05-01 15:59:00"


def test_screener_uses_ticker_atm30_measure_not_candidate_leg_iv(
    tmp_path: Path,
) -> None:
    history_dir = tmp_path / "iv-history"
    _seed_formal_iv_history(history_dir, ticker="AAPL")
    observation = Atm30StraddleIvObservation(
        measure="atm30_straddle_iv_v1",
        current_iv=0.245,
        expiry="2026-05-31",
        strike=100.0,
        days_to_expiry=30,
        quote_as_of="2026-05-01T20:00:00Z",
        quote_session="2026-05-01",
    )

    result = run_options_screener(
        provider=_RecommendationProvider(
            [
                _recommendation_row(
                    "US.AAPL260531P095000",
                    strike=95.0,
                    bid=2.9,
                    ask=3.1,
                    implied_volatility=0.45,
                    delta=-0.20,
                )
            ]
        ),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            include_rejected=True,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        run_date="2026-05-01",
        risk_free_rate=0.04,
        iv_history_dir=history_dir,
        iv_observation=observation,
        earnings_calendar=EarningsCalendar({"AAPL": [date(2026, 6, 15)]}),
    )

    assert result.candidates[0].implied_volatility == pytest.approx(0.45)
    assert result.candidates[0].iv_rank == pytest.approx(50.0)
    assert result.iv_measure == "atm30_straddle_iv_v1"
    assert result.atm30_iv == pytest.approx(0.245)
    assert result.iv_rank == pytest.approx(50.0)


def test_screener_hard_gates_a_stale_quote(tmp_path: Path) -> None:
    # 2026-08-21 incident shape: the scan consumed a weeks-stale Futu snapshot
    # and kept going. A stale quote must rate "Avoid" — and disappear from the
    # default view — instead of sailing through as Strong/Watch.
    history_dir = tmp_path / "iv-history"
    _seed_formal_iv_history(history_dir, ticker="AAPL")
    rows = [
        _recommendation_row(
            "US.AAPL260531P095000",
            strike=95.0,
            bid=2.9,
            ask=3.1,
            implied_volatility=0.45,
            delta=-0.20,
        )
    ]
    iv_observation = Atm30StraddleIvObservation(
        measure="atm30_straddle_iv_v1",
        current_iv=0.245,
        expiry="2026-05-31",
        strike=100.0,
        days_to_expiry=30,
        quote_as_of="2026-05-01T20:00:00Z",
        quote_session="2026-05-01",
    )
    earnings_calendar = EarningsCalendar({"AAPL": [date(2026, 6, 15)]})

    def scan(provider: object, *, include_rejected: bool) -> OptionsScreenerResult:
        return run_options_screener(
            provider=provider,
            config=OptionsScreenerConfig(
                ticker="AAPL",
                strategy_type="sell_put",
                trend_filter=False,
                include_rejected=include_rejected,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            run_date="2026-05-01",
            risk_free_rate=0.04,
            iv_history_dir=history_dir,
            iv_observation=iv_observation,
            earnings_calendar=earnings_calendar,
        )

    fresh = scan(_RecommendationProvider(rows), include_rejected=True)
    assert fresh.candidates[0].rating != "Avoid"
    assert "stale quote" not in fresh.candidates[0].notes

    stale = scan(_StaleQuoteProvider(rows), include_rejected=True)
    assert stale.candidates[0].rating == "Avoid"
    assert "stale quote" in stale.candidates[0].notes
    assert stale.rejected_count == 1
    assert stale.rejection_summary.get("stale quote") == 1

    hidden = scan(_StaleQuoteProvider(rows), include_rejected=False)
    assert hidden.candidates == []
    assert hidden.rejected_count == 1


@pytest.mark.parametrize(
    ("quote_as_of", "expected_reason"),
    (
        (None, "quote_as_of_missing"),
        ("not-a-time", "quote_as_of_invalid"),
        ("2099-05-01 16:00:00", "quote_future"),
        ("2026-03-10 16:00:00", "quote_stale"),
    ),
)
def test_screener_quote_hard_failures_are_hidden_and_audited_as_avoid(
    tmp_path: Path,
    quote_as_of: str | None,
    expected_reason: str,
) -> None:
    history_dir = tmp_path / "iv-history"
    _seed_formal_iv_history(history_dir, ticker="AAPL")
    rows = [
        _recommendation_row(
            "US.AAPL260531P095000",
            strike=95.0,
            bid=2.9,
            ask=3.1,
            implied_volatility=0.45,
            delta=-0.20,
        )
    ]

    class QuoteProvider(_RecommendationProvider):
        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame["update_time"] = quote_as_of
            return frame

    def scan(*, include_rejected: bool) -> OptionsScreenerResult:
        return run_options_screener(
            provider=QuoteProvider(rows),
            config=OptionsScreenerConfig(
                ticker="AAPL",
                strategy_type="sell_put",
                include_rejected=include_rejected,
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            run_date="2026-05-01",
            risk_free_rate=0.04,
            iv_history_dir=history_dir,
            iv_observation=Atm30StraddleIvObservation(
                measure="atm30_straddle_iv_v1",
                current_iv=0.245,
                expiry="2026-05-31",
                strike=100.0,
                days_to_expiry=30,
                quote_as_of="2026-05-01T20:00:00Z",
                quote_session="2026-05-01",
            ),
            earnings_calendar=EarningsCalendar({"AAPL": [date(2026, 6, 15)]}),
        )

    assert scan(include_rejected=False).candidates == []
    audited = scan(include_rejected=True)
    assert audited.candidates[0].rating == "Avoid"
    assert expected_reason in audited.candidates[0].recommendation_rejection_reasons


@pytest.mark.parametrize(
    "snapshot",
    [
        {
            "symbol": "US.MSFT",
            "last": 100.0,
            "update_time": "2026-05-01 15:59:00",
        },
        {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": "2026-03-02 15:59:00",
        },
    ],
)
def test_screener_rejects_untrusted_underlying_before_atm30(
    tmp_path: Path,
    snapshot: dict[str, object],
) -> None:
    class UnderlyingEvidenceProvider(_FakeProvider):
        def fetch_underlying_snapshot(self, symbol: str):
            return snapshot

        def fetch_option_quotes_range(self, *_args, **_kwargs) -> pd.DataFrame:
            raise AssertionError("untrusted underlying must stop before ATM30 fetch")

    with pytest.raises(ValueError, match="underlying_(symbol_mismatch|quote_stale)"):
        run_options_screener(
            provider=UnderlyingEvidenceProvider(),
            config=OptionsScreenerConfig(
                ticker="AAPL",
                strategy_type="sell_put",
                history_start="2026-01-02",
                history_end="2026-05-01",
            ),
            run_date="2026-05-01",
            risk_free_rate=0.04,
            iv_history_dir=tmp_path / "iv-history",
        )


def test_saturday_screener_uses_friday_session_dte_not_provider_calendar_dte() -> None:
    class SaturdayProvider(_FakeProvider):
        def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "strike_time": "2026-08-26",
                        "option_expiry_date_distance": 4,
                    }
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
                        "symbol": "US.AAPL260826P095000",
                        "underlying": "US.AAPL",
                        "option_type": "PUT",
                        "expiry": expiration,
                        "strike": 95.0,
                        "bid": 2.9,
                        "ask": 3.1,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.30,
                        "delta": -0.20,
                        "gamma": 0.02,
                        "theta": -0.04,
                        "vega": 0.12,
                        "update_time": "2026-08-21 15:59:00",
                    }
                ]
            )

    result = run_options_screener(
        provider=SaturdayProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            min_dte=5,
            max_dte=60,
            include_rejected=True,
            history_start="2026-01-02",
            history_end="2026-08-21",
        ),
        run_date="2026-08-22",
        risk_free_rate=0.04,
    )

    assert result.scanned_expirations == ["2026-08-26"]
    assert result.candidates[0].days_to_expiry == 5
    assert "dte_inconsistent" not in result.candidates[0].recommendation_rejection_reasons


def _fixture_historical_volatility() -> float:
    # Same deterministic series as _FakeProvider.fetch_ohlcv: business days
    # 2026-01-02..2026-05-01 with close = 220 + 0.2 * index.
    timestamps = pd.date_range(start="2026-01-02", end="2026-05-01", freq="B", tz="UTC")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "close": [220.0 + index * 0.2 for index in range(len(timestamps))],
        }
    )
    hv = calculate_historical_volatility(frame)
    assert hv is not None
    return hv


def _physical_payout(
    *,
    strike: float,
    spot: float,
    sigma: float,
    mu: float,
    dte: int,
) -> float:
    # Closed-form lognormal E[max(K - S_T, 0)] for a short put, matching the
    # seller EV kernel: sigma = min(IV, HV), mu = risk_free_rate + ERP.
    time_years = dte / 365
    vol_sqrt_t = sigma * math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (mu + sigma * sigma / 2) * time_years) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    cdf = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    return strike * cdf(-d2) - spot * math.exp(mu * time_years) * cdf(-d1)


def test_options_screener_reuses_recommendation_kernel_for_displayed_ev_fields(
    tmp_path: Path,
) -> None:
    result = _run_recommendation_screen(
        tmp_path,
        rows=[
            _recommendation_row(
                "US.AAPL260531P95000",
                strike=95.0,
                bid=2.97,
                ask=3.03,
                implied_volatility=0.30,
                delta=-0.20,
            )
        ],
    )

    candidate = result.candidates[0]
    sigma = min(0.30, _fixture_historical_volatility())
    payout = _physical_payout(strike=95.0, spot=100.0, sigma=sigma, mu=0.04 + 0.04, dte=30)
    expected_value = 3.0 - payout
    annualized_ev = expected_value / 95.0 * 365 / 30
    expected_excess = annualized_ev - 0.04

    assert candidate.hard_gate_passed is True
    assert candidate.recommendation_rejection_reasons == []
    assert candidate.extrinsic_value == pytest.approx(3.0)
    assert candidate.gross_annualized_yield == pytest.approx(3 / 95 * 365 / 30)
    assert candidate.pop == pytest.approx(0.80)
    assert candidate.otm_pct == pytest.approx(0.05)
    assert candidate.breakeven == pytest.approx(92.0)
    assert candidate.take_profit_50_price == pytest.approx(1.50)
    assert candidate.manage_at_21_dte == "2026-05-10"
    assert candidate.expected_value == pytest.approx(expected_value)
    assert candidate.excess_annualized_ev == pytest.approx(expected_excess)
    assert candidate.liquidity_factor == pytest.approx(1.0)
    assert candidate.recommendation_score == pytest.approx(annualized_ev)
    assert candidate.earnings_date == "2026-06-15"
    assert candidate.earnings_in_window is False
    assert candidate.ex_dividend_date is None
    assert candidate.ex_dividend_in_window is False


def test_screener_accepts_source_asserted_zero_dividend(tmp_path: Path) -> None:
    result = _run_recommendation_screen(
        tmp_path,
        strategy_type="covered_call",
        dividend_event=(None, 0.0),
        rows=[_recommendation_row(
            "US.AAPL260531C105000", strike=105.0, bid=2.97, ask=3.03,
            implied_volatility=0.30, delta=0.20,
        )],
    )
    assert result.candidates[0].hard_gate_passed is True


def test_screener_summary_explains_missing_events_even_for_strong_rows() -> None:
    from quant_system.options.models import OptionsScreenerCandidate
    from quant_system.options.screener import _rejection_summary

    candidate = OptionsScreenerCandidate(
        symbol="US.DELL260918P500000", underlying="US.DELL", strategy_type="sell_put",
        option_type="PUT", expiry="2026-09-18", strike=500.0, underlying_price=524.14,
        rating="Strong", hard_gate_passed=False,
        recommendation_rejection_reasons=["earnings_data_missing"],
    )
    assert _rejection_summary([candidate]) == {"earnings_data_missing": 1}


def _seed_formal_iv_history(history_dir: Path, *, ticker: str) -> None:
    store = IvHistoryStore(history_dir)
    active_date = date(2026, 4, 30)
    sessions: list[date] = []
    while len(sessions) < 30:
        if is_us_market_session(active_date):
            sessions.append(active_date)
        active_date -= timedelta(days=1)
    for index, session in enumerate(reversed(sessions)):
        quote_at = f"{session.isoformat()}T20:00:00Z"
        store.append(
            ticker,
            current_iv=0.10 + index * 0.01,
            run_date=session.isoformat(),
            quote_as_of=quote_at,
            provider="futu",
            fetched_at=f"{session.isoformat()}T21:00:00Z",
        )


def test_options_screener_missing_truth_never_becomes_an_ev_recommendation() -> None:
    result = run_options_screener(
        provider=_FakeProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            include_rejected=True,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        run_date="2026-05-01",
    )

    candidate = result.candidates[0]
    assert candidate.rating == "Strong"
    assert candidate.hard_gate_passed is False
    assert {
        "risk_free_rate_missing",
        "earnings_data_missing",
    }.issubset(candidate.recommendation_rejection_reasons)
    assert candidate.expected_value is None
    assert candidate.excess_annualized_ev is None
    assert candidate.liquidity_factor is None
    assert candidate.recommendation_score is None


def test_options_screener_covered_call_requires_extrinsic_above_dividend(
    tmp_path: Path,
) -> None:
    result = _run_recommendation_screen(
        tmp_path,
        rows=[
            _recommendation_row(
                "US.AAPL260531C105000",
                strike=105.0,
                bid=1.08,
                ask=1.12,
                implied_volatility=0.30,
                delta=0.20,
            )
        ],
        strategy_type="covered_call",
        dividend_event=(date(2026, 5, 15), 1.10),
    )

    candidate = result.candidates[0]
    assert candidate.hard_gate_passed is False
    assert candidate.extrinsic_value == pytest.approx(1.10)
    assert candidate.ex_dividend_date == "2026-05-15"
    assert candidate.ex_dividend_in_window is True
    assert candidate.dividend_per_share == pytest.approx(1.10)
    assert candidate.recommendation_rejection_reasons == [
        "covered_call_extrinsic_not_above_dividend"
    ]
    assert candidate.recommendation_score is None


def test_options_screener_ranks_eligible_rows_by_multiplicative_ev_score(
    tmp_path: Path,
) -> None:
    result = _run_recommendation_screen(
        tmp_path,
        rows=[
            _recommendation_row(
                "US.AAPL260531P095000",
                strike=95.0,
                bid=6.86,
                ask=7.14,
                implied_volatility=0.30,
                delta=-0.35,
                volume=100,
                open_interest=100,
            ),
            _recommendation_row(
                "US.AAPL260531P095000",
                strike=95.0,
                bid=1.485,
                ask=1.515,
                implied_volatility=0.05,
                delta=-0.15,
            ),
        ],
    )

    # Both rows share the one contract identity consistent with the scanned
    # expiry/strike, so the EV ranking is pinned by quote instead of symbol.
    # With the fixture HV near zero, sigma = min(IV, HV) shrinks the physical
    # payout towards zero for both rows, so the richer premium wins on
    # annualized EV; the 4%-spread row carries the lower liquidity factor.
    first, second = result.candidates
    assert [first.bid, second.bid] == [6.86, 1.485]
    assert first.liquidity_factor < second.liquidity_factor
    assert first.recommendation_score == pytest.approx(
        first.expected_value / 95.0 * 365 / 30 * first.liquidity_factor
    )
    assert first.recommendation_score > second.recommendation_score


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
            include_rejected=True,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.candidates[0].rating == "Avoid"
    assert "spread too wide" in result.candidates[0].notes
    assert result.rejection_summary["spread too wide"] == 1


def test_options_screener_hides_rejected_deep_itm_puts_by_default() -> None:
    class DeepItmProvider(_FakeProvider):
        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            return pd.DataFrame(
                [
                    {
                        "symbol": "US.AAPL260619P420000",
                        "underlying": "US.AAPL",
                        "option_type": "PUT",
                        "expiry": expiration,
                        "strike": 420.0,
                        "bid": 140.0,
                        "ask": 141.0,
                        "volume": 1,
                        "open_interest": 0,
                        "implied_volatility": 1.5,
                        "delta": -0.98,
                    }
                ]
            )

    result = run_options_screener(
        provider=DeepItmProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            max_delta=0.45,
            min_open_interest=50,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.candidates == []
    assert result.rejected_count == 1


def test_options_screener_can_include_rejected_rows_for_audit() -> None:
    class DeepItmProvider(_FakeProvider):
        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            return pd.DataFrame(
                [
                    {
                        "symbol": "US.AAPL260619P420000",
                        "underlying": "US.AAPL",
                        "option_type": "PUT",
                        "expiry": expiration,
                        "strike": 420.0,
                        "bid": 140.0,
                        "ask": 141.0,
                        "volume": 1,
                        "open_interest": 0,
                        "implied_volatility": 1.5,
                        "delta": -0.98,
                    }
                ]
            )

    result = run_options_screener(
        provider=DeepItmProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            max_delta=0.45,
            min_open_interest=50,
            include_rejected=True,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].rating == "Avoid"
    assert "sell put strike is above spot" in result.candidates[0].notes


def test_options_screener_uses_ema21_and_sma50_trend_check_for_covered_call() -> None:
    class CoveredCallProvider(_FakeProvider):
        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            assert option_type == "CALL"
            return pd.DataFrame(
                [
                    {
                        "symbol": "US.AAPL260619C300000",
                        "underlying": "US.AAPL",
                        "option_type": "CALL",
                        "expiry": expiration,
                        "strike": 300.0,
                        "bid": 2.0,
                        "ask": 2.2,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.45,
                        "delta": 0.25,
                        "update_time": "2026-05-01 15:59:00",
                    }
                ]
            )

    result = run_options_screener(
        provider=CoveredCallProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="covered_call",
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

    assert len(result.candidates) == 1
    assert result.underlying_price >= result.ema_21
    assert result.underlying_price >= result.sma_50
    assert result.candidates[0].rating == "Strong"
    assert result.candidates[0].trend_pass is True


def test_options_screener_enforces_enabled_trend_filter_with_ema21_and_sma50_notes() -> None:
    class WeakTrendProvider(_FakeProvider):
        def fetch_underlying_snapshot(self, symbol: str):
            session = getattr(self, "_test_market_session", "2026-05-01")
            return {
                "symbol": "US.AAPL",
                "last": 210.0,
                "update_time": f"{session} 15:59:00",
            }

        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame.loc[0, "strike"] = 190.0
            frame.loc[0, "symbol"] = "US.AAPL260619P190000"
            return frame

    result = run_options_screener(
        provider=WeakTrendProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="sell_put",
            min_iv=0.2,
            max_delta=0.35,
            min_premium=1.0,
            max_spread_pct=0.2,
            trend_filter=True,
            include_rejected=True,
            hv_iv_filter=False,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.ema_21 is not None
    assert result.sma_50 is not None
    assert result.underlying_price < result.ema_21
    assert result.underlying_price < result.sma_50
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.trend_pass is False
    assert candidate.rating == "Avoid"
    assert candidate.screen_passed is False
    assert "trend filter failed" in candidate.preference_rejection_reasons
    assert "price below EMA21" in candidate.notes
    assert "price below SMA50" in candidate.notes


def test_options_screener_avoids_itm_covered_call_when_delta_is_missing() -> None:
    class CoveredCallProvider(_FakeProvider):
        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            assert option_type == "CALL"
            return pd.DataFrame(
                [
                    {
                        "symbol": "US.AAPL260619C250000",
                        "underlying": "US.AAPL",
                        "option_type": "CALL",
                        "expiry": expiration,
                        "strike": 250.0,
                        "bid": 30.0,
                        "ask": 31.0,
                        "volume": 100,
                        "open_interest": 500,
                        "implied_volatility": 0.45,
                        "delta": 0.0,
                    }
                ]
            )

    result = run_options_screener(
        provider=CoveredCallProvider(),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            strategy_type="covered_call",
            max_delta=0.35,
            trend_filter=False,
            hv_iv_filter=False,
            include_rejected=True,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.candidates[0].rating == "Avoid"
    assert "covered call strike is below spot" in result.candidates[0].notes


def test_options_screener_applies_income_filters_and_normalizes_iv() -> None:
    class PercentIvProvider(_FakeProvider):
        def fetch_option_quotes(self, underlying: str, *, expiration: str, option_type: str):
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame.loc[0, "implied_volatility"] = 45.0
            # Declared, not magnitude-guessed: a percent frame is converted once.
            frame.attrs["implied_volatility_unit"] = "percent"
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
            include_rejected=True,
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
                        "underlying": "US.AAPL",
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
            include_rejected=True,
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


def test_options_screener_reports_hv_iv_summary_for_top_status() -> None:
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
            hv_iv_filter=True,
            max_hv_iv=1.2,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
    )

    assert result.ema_21 is not None
    assert result.sma_50 is not None
    assert result.hv_iv_threshold == 1.2
    assert result.hv_iv_contract_count == 1
    assert result.hv_iv_pass_count == 1
    assert result.hv_iv_min is not None
    assert result.hv_iv_max == result.hv_iv_min


def _apr_notes(config: OptionsScreenerConfig, annualized_yield: float) -> list[str]:
    """Drive the min_apr branch (screener._candidate_notes) in isolation.

    All other filters are made to pass so the only possible note is the APR
    one. ``annualized_yield`` is a FRACTION (0.12 = 12%); ``config.min_apr`` is
    a whole-number PERCENT (15 = 15%).
    """
    return _candidate_notes(
        config=config,
        bid=2.0,
        ask=2.2,
        mid=2.1,
        spread_pct=0.1,
        iv=0.45,
        delta=-0.25,
        annualized_yield=annualized_yield,
        days_to_expiry=30,
        open_interest=500.0,
        trend_pass=True,
        underlying_price=260.0,
        ema_21=250.0,
        sma_50=240.0,
        hv_iv_pass=True,
    )


def test_min_apr_is_percent_semantics() -> None:
    # min_apr=15 means 15% (a whole-number percent), so a 12% APR
    # (annualized_yield=0.12) is rejected and an 18% APR (0.18) is accepted.
    # This pins the contract in screener.py: annualized_yield * 100 < min_apr.
    config = OptionsScreenerConfig(min_apr=15.0)

    rejected = _apr_notes(config, 0.12)  # 12% APR
    accepted = _apr_notes(config, 0.18)  # 18% APR

    assert "APR below minimum" in rejected
    assert "APR below minimum" not in accepted


def test_min_apr_zero_disables_filter() -> None:
    # Default min_apr=0 accepts any non-negative APR (filter disabled).
    config = OptionsScreenerConfig(min_apr=0.0)
    assert "APR below minimum" not in _apr_notes(config, 0.0)
    assert "APR below minimum" not in _apr_notes(config, 0.05)


def test_screener_drops_contradictory_identity_rows_fail_closed(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Incident shape: the symbol encodes 2026-01-01 CALL strike 999 while the
    # declared fields claim 2026-05-31 PUT strike 95. The contradictory row
    # must be dropped fail-closed, never scored under the wrong identity.
    with caplog.at_level(logging.WARNING, logger="quant_system.options.screener"):
        result = _run_recommendation_screen(
            tmp_path,
            rows=[
                _recommendation_row(
                    "US.AAPL260531P095000",
                    strike=95.0,
                    bid=2.9,
                    ask=3.1,
                    implied_volatility=0.45,
                    delta=-0.20,
                ),
                _recommendation_row(
                    "US.AAPL260101C999000",
                    strike=95.0,
                    bid=2.9,
                    ask=3.1,
                    implied_volatility=0.45,
                    delta=-0.20,
                ),
            ],
        )

    assert [candidate.symbol for candidate in result.candidates] == [
        "US.AAPL260531P095000"
    ]
    assert any(
        "1 provider row(s) failed contract identity checks" in line
        for line in result.assumptions
    )
    assert "US.AAPL260101C999000" in caplog.text
    assert "contract_identity_mismatch" in caplog.text


def test_screener_drops_self_consistent_call_row_in_a_sell_put_scan(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # _build_candidate derives option_type from the strategy alone, so a
    # self-consistent CALL row inside a sell_put scan would be relabelled PUT.
    # It must be dropped instead.

    class CallRowProvider(_RecommendationProvider):
        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame["option_type"] = "CALL"
            return frame

    rows = [
        _recommendation_row(
            "US.AAPL260531C095000",
            strike=95.0,
            bid=2.9,
            ask=3.1,
            implied_volatility=0.45,
            delta=-0.20,
        )
    ]
    with caplog.at_level(logging.WARNING, logger="quant_system.options.screener"):
        result = _run_recommendation_screen(
            tmp_path,
            rows=rows,
            provider=CallRowProvider(rows),
        )

    assert result.candidates == []
    assert any(
        "1 provider row(s) failed contract identity checks" in line
        for line in result.assumptions
    )
    assert "US.AAPL260531C095000" in caplog.text
    assert "strategy_option_type_mismatch" in caplog.text


def test_screener_drops_row_whose_underlying_is_not_the_scanned_ticker(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class WrongUnderlyingProvider(_RecommendationProvider):
        def fetch_option_quotes(
            self,
            underlying: str,
            *,
            expiration: str,
            option_type: str,
        ) -> pd.DataFrame:
            frame = super().fetch_option_quotes(
                underlying,
                expiration=expiration,
                option_type=option_type,
            )
            frame["underlying"] = "US.MSFT"
            return frame

    rows = [
        _recommendation_row(
            "US.AAPL260531P095000",
            strike=95.0,
            bid=2.9,
            ask=3.1,
            implied_volatility=0.45,
            delta=-0.20,
        )
    ]
    with caplog.at_level(logging.WARNING, logger="quant_system.options.screener"):
        result = _run_recommendation_screen(
            tmp_path,
            rows=rows,
            provider=WrongUnderlyingProvider(rows),
        )

    assert result.candidates == []
    assert any(
        "1 provider row(s) failed contract identity checks" in line
        for line in result.assumptions
    )
    assert "underlying_mismatch" in caplog.text


@pytest.mark.parametrize("include_rejected", [False, True])
def test_min_apr_excludes_low_yield_from_eligible_and_preserves_observation(include_rejected):
    result = run_options_screener(
        provider=_RecommendationProvider(
            [
                _recommendation_row(
                    "US.AAPL260531P95000",
                    strike=95,
                    bid=1,
                    ask=1.02,
                    implied_volatility=0.3,
                    delta=-0.2,
                )
            ]
        ),
        config=OptionsScreenerConfig(
            ticker="AAPL",
            min_apr=15,
            trend_filter=False,
            include_rejected=include_rejected,
            history_start="2026-01-02",
            history_end="2026-05-01",
        ),
        risk_free_rate=0.04,
        is_etf=True,
    )
    assert not [
        item for item in result.candidates if item.hard_gate_passed and item.rating != "Avoid"
    ]
    assert result.eligible_count == 0
    assert result.preference_rejected_count == 1
    assert result.hard_gate_rejected_count == 0
    assert len(result.watch_candidates) == 1
    assert result.watch_candidates[0].preference_rejection_reasons == ["APR below minimum"]
    assert result.apr_alternative_max_percent < 15


def test_fee_adjusted_bid_yield_is_unknown_without_fee_and_not_strategy_return():
    config = OptionsScreenerConfig(
        ticker="AAPL", trend_filter=False, history_start="2026-01-02", history_end="2026-05-01"
    )

    def screen(active_config):
        return run_options_screener(
            provider=_FakeProvider(), config=active_config, risk_free_rate=0.04, is_etf=True
        ).candidates[0]

    unknown = screen(config)
    costed = screen(config.model_copy(update={"estimated_round_trip_fee_per_contract": 2.0}))
    assert unknown.bid_premium_per_contract == 200
    assert unknown.fee_adjusted_bid_annualized_yield is None
    assert costed.bid_annualized_yield == pytest.approx(2 / 250 * 365 / 49)
    assert costed.fee_adjusted_bid_annualized_yield == pytest.approx(1.98 / 250 * 365 / 49)
    assert costed.expected_value == unknown.expected_value


def test_panic_regime_does_not_suggest_lowering_apr_as_the_only_missing_condition():
    from quant_system.options.market_regime import VixRegimeSnapshot

    result = run_options_screener(
        provider=_RecommendationProvider([
            _recommendation_row("US.AAPL260531P95000", strike=95, bid=1, ask=1.02,
                                implied_volatility=.3, delta=-.2),
        ]),
        config=OptionsScreenerConfig(ticker="AAPL", min_apr=15, trend_filter=False),
        market_regime=VixRegimeSnapshot("Panic", .35, .6, 1.05, 30., 22.),
        risk_free_rate=.04, is_etf=True,
    )
    assert result.eligible_count == 0
    assert result.preference_rejected_count == 1
    assert result.watch_candidates == []
    assert result.apr_alternative_max_percent is None
