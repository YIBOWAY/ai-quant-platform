from __future__ import annotations

import pandas as pd
import pytest

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
    assert result["methodology"]["scope_classification"] == "workflow_proxy"
    assert result["methodology"]["full_paper_replication"] is False
    assert result["data_evidence"] == {
        "actual_providers": ["test"],
        "provider_consistent": True,
        "sample_or_real": "sample",
    }
    assert any(
        "not a full paper replication" in warning
        for warning in result["warnings"]
    )


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


def test_reversal_momentum_replication_excludes_terminal_partial_month() -> None:
    frame = _wide_frame()
    partial_timestamp = pd.Timestamp("2024-07-15", tz="UTC")
    partial_rows = frame.loc[
        frame["timestamp"] == frame["timestamp"].max()
    ].copy()
    partial_rows["timestamp"] = partial_timestamp
    partial_rows["event_ts"] = partial_timestamp
    partial_rows["knowledge_ts"] = partial_timestamp
    partial_rows["close"] *= 1.5

    result = build_reversal_momentum_replication(
        pd.concat([frame, partial_rows], ignore_index=True),
        initial_cash=1.0,
        top_n=1,
    )

    return_dates = {
        pd.Timestamp(row["return_date"])
        for row in result["monthly_returns"]
    }
    assert pd.Timestamp("2024-07-31", tz="UTC") not in return_dates


def test_reversal_momentum_replication_keeps_complete_business_month() -> None:
    frame = _wide_frame()
    calendar_month_end = frame["timestamp"].max()
    last_trading_day = pd.Timestamp("2024-06-28", tz="UTC")
    terminal = frame["timestamp"] == calendar_month_end
    frame.loc[terminal, "timestamp"] = last_trading_day
    frame.loc[terminal, "event_ts"] = last_trading_day
    frame.loc[terminal, "knowledge_ts"] = last_trading_day

    result = build_reversal_momentum_replication(
        frame,
        initial_cash=1.0,
        top_n=1,
    )

    return_dates = {
        pd.Timestamp(row["return_date"])
        for row in result["monthly_returns"]
    }
    assert pd.Timestamp("2024-06-30", tz="UTC") in return_dates


def test_reversal_momentum_replication_checks_terminal_month_per_symbol() -> None:
    frame = _wide_frame()
    terminal_month = frame["timestamp"].max()
    partial_symbol = (frame["symbol"] == "S00") & (
        frame["timestamp"] == terminal_month
    )
    partial_timestamp = pd.Timestamp("2024-06-03", tz="UTC")
    frame.loc[partial_symbol, "timestamp"] = partial_timestamp
    frame.loc[partial_symbol, "event_ts"] = partial_timestamp
    frame.loc[partial_symbol, "knowledge_ts"] = partial_timestamp

    result = build_reversal_momentum_replication(
        frame,
        initial_cash=1.0,
        top_n=20,
    )

    may_positions = [
        row
        for row in result["positions"]
        if pd.Timestamp(row["rebalance_date"])
        == pd.Timestamp("2024-05-31", tz="UTC")
    ]
    assert "S00" not in {row["symbol"] for row in may_positions}
    assert "S01" in {row["symbol"] for row in may_positions}
    assert (
        result["methodology"]["terminal_month_completeness"]["evaluation_scope"]
        == "per_symbol"
    )


def test_reversal_momentum_turnover_uses_target_weight_changes() -> None:
    result = build_reversal_momentum_replication(
        _wide_frame(),
        initial_cash=1.0,
        top_n=2,
    )

    positions = pd.DataFrame(result["positions"])
    assert not positions.empty
    grouped = positions.groupby("rebalance_date", sort=True)
    previous_weights: dict[str, float] = {}
    expected_gross = 0.0
    rebalance_count = 0
    for _rebalance_date, group in grouped:
        current_weights = dict(
            zip(
                group["symbol"],
                group["target_weight"],
                strict=True,
            )
        )
        symbols = set(previous_weights) | set(current_weights)
        expected_gross += sum(
            abs(current_weights.get(symbol, 0.0) - previous_weights.get(symbol, 0.0))
            for symbol in symbols
        )
        previous_weights = current_weights
        rebalance_count += 1

    assert result["metrics"]["turnover_gross"] == pytest.approx(expected_gross)
    assert result["metrics"]["turnover_one_way"] == pytest.approx(expected_gross / 2.0)
    assert result["metrics"]["turnover"] == result["metrics"]["turnover_one_way"]
    assert result["metrics"]["turnover_rebalances"] == rebalance_count
    assert result["metrics"]["turnover_initial_build_gross"] == pytest.approx(2.0)
    assert result["metrics"]["turnover_initial_build_one_way"] == pytest.approx(1.0)
    assert result["methodology"]["turnover"]["initial_build_included"] is True
    assert result["methodology"]["turnover"]["legacy_metric"] == "cumulative_one_way"


def test_reversal_momentum_provider_evidence_fails_closed_for_mixed_rows() -> None:
    frame = _wide_frame()
    frame["provider"] = "futu"
    frame.loc[frame["symbol"] == "S00", "provider"] = "sample"

    result = build_reversal_momentum_replication(frame, initial_cash=1.0, top_n=1)

    assert result["data_evidence"] == {
        "actual_providers": ["futu", "sample"],
        "provider_consistent": False,
        "sample_or_real": "sample",
    }
    assert any("mixed provider" in warning.lower() for warning in result["warnings"])


def test_reversal_momentum_provider_evidence_marks_verified_real_rows() -> None:
    frame = _wide_frame()
    frame["provider"] = "futu"

    result = build_reversal_momentum_replication(frame, initial_cash=1.0, top_n=1)

    assert result["data_evidence"] == {
        "actual_providers": ["futu"],
        "provider_consistent": True,
        "sample_or_real": "real",
    }
