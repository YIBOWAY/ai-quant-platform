from __future__ import annotations

import json
from datetime import date

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


def _chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "US.AAPL20260619C100000",
                "underlying": "US.AAPL",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 5.0,
                "ask": 5.4,
                "implied_volatility": 0.25,
                "delta": 0.56,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 30,
                "update_time": "2026-05-20 15:59:00",
            },
            {
                "symbol": "US.AAPL20260619C110000",
                "underlying": "US.AAPL",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 110.0,
                "bid": 1.3,
                "ask": 1.5,
                "implied_volatility": 0.24,
                "delta": 0.24,
                "gamma": 0.02,
                "theta": -0.04,
                "vega": 0.12,
                "open_interest": 500,
                "volume": 80,
                "option_expiry_date_distance": 30,
                "update_time": "2026-05-20 15:59:00",
            },
            {
                "symbol": "US.AAPL20260619P100000",
                "underlying": "US.AAPL",
                "option_type": "PUT",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 4.6,
                "ask": 4.9,
                "implied_volatility": 0.25,
                "delta": -0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 900,
                "volume": 100,
                "option_expiry_date_distance": 30,
                "update_time": "2026-05-20 15:59:00",
            },
        ]
    )


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01", periods=40, freq="B", tz="UTC"),
            "close": [100.0 + index * 0.2 for index in range(40)],
        }
    )


def test_options_buyside_screen_cli_outputs_json(monkeypatch) -> None:
    monkeypatch.setattr("quant_system.cli._options_market_session", lambda: date(2026, 5, 20))
    monkeypatch.setattr(
        "quant_system.options.daily_task.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {
            "symbol": "US.AAPL",
            "last": 100.0,
            "update_time": "2026-05-20 15:59:00",
        },
    )

    def fake_chain(
        self,
        underlying,
        *,
        start_expiration,
        end_expiration,
        option_type="CALL",
    ):
        assert option_type == "ALL"
        return _chain()

    monkeypatch.setattr(
        "quant_system.options.daily_task.FutuMarketDataProvider.fetch_option_quotes_range",
        fake_chain,
    )
    monkeypatch.setattr(
        "quant_system.options.daily_task.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    monkeypatch.setattr(
        "quant_system.options.buy_side_market_data.compute_iv_rank",
        lambda ticker, current_iv, *, history_dir, measure, as_of_session: 35.0,
    )

    result = runner.invoke(
        app,
        [
            "options",
            "buyside-screen",
            "--ticker",
            "AAPL",
            "--view",
            "short_term_conservative_bullish",
            "--target-price",
            "112",
            "--target-date",
            "2026-08-21",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ticker"] == "AAPL"
    assert payload["recommendations"]
    assert payload["recommendations"][0]["rank"] == 1
    assert payload["thesis"]["iv_rank"] == 35.0
    assert payload["thesis"]["historical_volatility"] > 0


def test_options_buyside_screen_cli_has_no_user_market_truth_flags(monkeypatch) -> None:
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("removed option must fail before provider calls")

    monkeypatch.setattr(
        "quant_system.options.daily_task.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    result = runner.invoke(
        app,
        [
            "options",
            "buyside-screen",
            "--ticker",
            "AAPL",
            "--view",
            "short_term_conservative_bullish",
            "--target-price",
            "112",
            "--target-date",
            "2026-08-21",
            "--iv-rank",
            "99",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert calls == 0


def test_options_buyside_screen_cli_has_no_client_as_of_flag(monkeypatch) -> None:
    calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("removed as-of option must fail before provider calls")

    monkeypatch.setattr(
        "quant_system.options.daily_task.FutuMarketDataProvider.fetch_underlying_snapshot",
        forbidden,
    )
    result = runner.invoke(
        app,
        [
            "options",
            "buyside-screen",
            "--ticker",
            "AAPL",
            "--view",
            "short_term_conservative_bullish",
            "--target-price",
            "112",
            "--target-date",
            "2026-12-18",
            "--as-of-date",
            "2026-05-20",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    assert calls == 0
