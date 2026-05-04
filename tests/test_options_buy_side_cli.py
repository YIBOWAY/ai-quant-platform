from __future__ import annotations

import json

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


def _chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "US.AAPL20260619C100000",
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
            },
            {
                "symbol": "US.AAPL20260619C110000",
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
            },
        ]
    )


def test_options_buyside_screen_cli_outputs_json(monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.cli.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {"symbol": "US.AAPL", "last": 100.0},
    )
    monkeypatch.setattr(
        "quant_system.cli.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, *, start_expiration, end_expiration, option_type="CALL": _chain(),
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
            "--as-of-date",
            "2026-05-20",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["ticker"] == "AAPL"
    assert payload["recommendations"]
    assert payload["recommendations"][0]["rank"] == 1

