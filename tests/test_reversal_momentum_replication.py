from __future__ import annotations

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.replication.reversal_momentum import build_reversal_momentum_replication


def _frame() -> pd.DataFrame:
    rows = []
    monthly_closes = {
        "AAA": [
            100, 104, 107, 111, 112, 116, 119, 121, 125,
            130, 134, 139, 144, 133, 137, 142, 148,
        ],
        "BBB": [100, 98, 97, 95, 94, 93, 92, 91, 89, 88, 86, 85, 84, 92, 89, 88, 87],
        "CCC": [
            100, 101, 103, 105, 107, 108, 110, 111, 113,
            115, 118, 120, 123, 125, 127, 128, 130,
        ],
        "DDD": [100, 99, 101, 100, 102, 101, 103, 102, 104, 103, 105, 104, 106, 103, 104, 105, 104],
    }
    dates = pd.date_range("2023-01-31", periods=17, freq="ME", tz="UTC")
    for symbol, closes in monthly_closes.items():
        for timestamp, close in zip(dates, closes, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close - 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1000,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp,
                }
            )
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="test", interval="1d")


def _wide_frame(symbol_count: int = 20) -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2023-01-31", periods=18, freq="ME", tz="UTC")
    for index in range(symbol_count):
        symbol = f"S{index:02d}"
        closes = [100 + index]
        for month in range(1, len(dates)):
            base_return = 0.01 + (index * 0.001)
            reversal_month = -0.08 if index < symbol_count // 2 else 0.08
            monthly_return = reversal_month if month == 13 else base_return
            closes.append(closes[-1] * (1.0 + monthly_return))
        for timestamp, close in zip(dates, closes, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close - 0.5,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1000,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp,
                }
            )
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="test", interval="1d")


def test_reversal_momentum_replication_builds_monthly_long_short_curve() -> None:
    result = build_reversal_momentum_replication(
        _frame(),
        initial_cash=1.0,
        top_n=1,
    )

    assert result["metrics"]["observation_months"] >= 2
    assert result["equity_curve"][0]["equity"] == 1.0
    assert result["equity_curve"][-1]["equity"] != 1.0
    assert result["legs"]
    assert {row["side"] for row in result["positions"]} == {"long", "short"}
    assert {"reversal", "momentum", "composite"} <= {
        item["strategy"] for item in result["monthly_returns"]
    }


def test_reversal_momentum_replication_rejects_too_short_history() -> None:
    cutoff = pd.Timestamp("2023-06-30", tz="UTC")
    short_frame = _frame().loc[lambda frame: frame["timestamp"] <= cutoff]

    result = build_reversal_momentum_replication(short_frame, initial_cash=1.0, top_n=1)

    assert result["metrics"]["observation_months"] == 0
    assert result["equity_curve"] == []
    assert result["positions"] == []
    assert result["warnings"]


def test_reversal_momentum_replication_defaults_to_decile_portfolios() -> None:
    result = build_reversal_momentum_replication(
        _wide_frame(),
        initial_cash=1.0,
        top_n=None,
    )

    first_composite = next(
        row for row in result["monthly_returns"] if row["strategy"] == "composite"
    )

    assert first_composite["long_count"] == 2
    assert first_composite["short_count"] == 2
    assert result["methodology"]["formation"] == "decile long-short portfolios"


def test_reversal_momentum_replication_excludes_low_price_names() -> None:
    frame = _wide_frame()
    frame.loc[frame["symbol"] == "S00", "close"] = 0.5

    result = build_reversal_momentum_replication(
        frame,
        initial_cash=1.0,
        top_n=10,
    )

    assert "S00" not in {row["symbol"] for row in result["positions"]}
    assert any("below $1" in warning for warning in result["warnings"])
