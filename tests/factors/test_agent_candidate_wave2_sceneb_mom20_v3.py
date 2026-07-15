"""Behavioral tests for the promoted Scene-B 20-bar momentum factor."""

from __future__ import annotations

import pandas as pd
import pytest

from quant_system.factors.library.promoted.agent_candidate_wave2_sceneb_mom20_v3 import (
    AgentCandidateFactor,
)


def _synthetic_ohlcv(rows: int = 80) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=rows, freq="D", tz="UTC")
    close = 100.0 + 0.5 * pd.Series(range(rows), dtype="float64")
    return pd.DataFrame(
        {
            "symbol": ["TEST"] * rows,
            "timestamp": timestamps,
            "close": close,
            "volume": [1_000_000.0] * rows,
        }
    )


def _ohlcv_for_symbol(symbol: str, closes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "symbol": [symbol] * len(closes),
            "timestamp": timestamps,
            "close": closes,
            "volume": [1_000_000.0] * len(closes),
        }
    )


def test_agent_candidate_wave2_sceneb_mom20_v3_metadata() -> None:
    factor = AgentCandidateFactor()
    metadata = factor.metadata
    assert metadata.factor_id == "agent_candidate_wave2_sceneb_mom20_v3"
    assert metadata.factor_name == "Wave2 SceneB Momentum 20d v3"
    assert metadata.factor_version == "0.1.0-wave2-smoke"
    assert metadata.lookback == 20
    assert metadata.direction == "higher_is_better"
    assert "research only" in metadata.description


def test_agent_candidate_wave2_sceneb_mom20_v3_computes_on_synthetic_ohlcv() -> None:
    factor = AgentCandidateFactor()
    result = factor.compute(_synthetic_ohlcv())
    assert not result.empty
    assert set(result["factor_id"]) == {"agent_candidate_wave2_sceneb_mom20_v3"}
    assert result["value"].notna().all()


def test_default_signal_is_exact_20_bar_close_to_close_momentum() -> None:
    frame = _synthetic_ohlcv(rows=22)
    frame.loc[0, "close"] = 80.0
    frame.loc[20, "close"] = 120.0

    result = AgentCandidateFactor().compute(frame)

    assert len(result) == 1
    signal = result.iloc[0]
    assert signal["signal_ts"] == frame.loc[20, "timestamp"]
    assert signal["tradeable_ts"] == frame.loc[21, "timestamp"]
    assert signal["lookback"] == 20
    assert signal["value"] == pytest.approx(120.0 / 80.0 - 1.0)


def test_momentum_is_sorted_and_isolated_per_normalized_symbol() -> None:
    rising = _ohlcv_for_symbol(" aaa ", [100.0] * 20 + [125.0, 126.0])
    falling = _ohlcv_for_symbol("bbb", [200.0] * 20 + [100.0, 90.0])
    reverse_ordered = (
        pd.concat([falling, rising], ignore_index=True)
        .sort_values(["timestamp", "symbol"], ascending=[False, False])
        .reset_index(drop=True)
    )

    result = AgentCandidateFactor().compute(reverse_ordered)

    assert result["symbol"].tolist() == ["AAA", "BBB"]
    assert result["signal_ts"].tolist() == [
        rising.loc[20, "timestamp"],
        falling.loc[20, "timestamp"],
    ]
    assert result["tradeable_ts"].tolist() == [
        rising.loc[21, "timestamp"],
        falling.loc[21, "timestamp"],
    ]
    assert result["value"].tolist() == pytest.approx([0.25, -0.5])


def test_default_lookback_needs_a_later_bar_before_signal_is_actionable() -> None:
    terminal_signal_only = _ohlcv_for_symbol("TEST", [100.0] * 20 + [120.0])
    next_bar_available = _ohlcv_for_symbol("TEST", [100.0] * 20 + [120.0, 121.0])

    assert AgentCandidateFactor().compute(terminal_signal_only).empty

    actionable = AgentCandidateFactor().compute(next_bar_available)
    assert len(actionable) == 1
    assert actionable.loc[0, "signal_ts"] == next_bar_available.loc[20, "timestamp"]
    assert actionable.loc[0, "tradeable_ts"] == next_bar_available.loc[21, "timestamp"]


def test_explicit_lookback_override_controls_the_return_window() -> None:
    frame = _ohlcv_for_symbol("TEST", [100.0, 101.0, 102.0, 130.0, 131.0])

    result = AgentCandidateFactor(lookback=3).compute(frame)

    assert len(result) == 1
    assert result.loc[0, "lookback"] == 3
    assert result.loc[0, "signal_ts"] == frame.loc[3, "timestamp"]
    assert result.loc[0, "value"] == pytest.approx(130.0 / 100.0 - 1.0)


def test_signal_value_does_not_change_when_future_prices_change() -> None:
    frame = _ohlcv_for_symbol("TEST", [100.0 + index for index in range(26)])
    factor = AgentCandidateFactor()
    baseline = factor.compute(frame)
    first_signal_ts = baseline.loc[0, "signal_ts"]

    future_changed = frame.copy()
    future_changed.loc[future_changed["timestamp"] > first_signal_ts, "close"] *= 100.0
    changed = factor.compute(future_changed)

    changed_at_same_signal = changed.loc[changed["signal_ts"] == first_signal_ts].iloc[0]
    assert changed_at_same_signal["value"] == pytest.approx(baseline.loc[0, "value"])
    assert changed_at_same_signal["tradeable_ts"] == baseline.loc[0, "tradeable_ts"]


def test_missing_signal_close_is_not_forward_filled_into_a_false_signal() -> None:
    frame = _ohlcv_for_symbol("TEST", [100.0] * 23)
    missing_signal_ts = frame.loc[20, "timestamp"]
    frame.loc[20, "close"] = float("nan")

    result = AgentCandidateFactor().compute(frame)

    assert missing_signal_ts not in result["signal_ts"].tolist()
    assert result["signal_ts"].tolist() == [frame.loc[21, "timestamp"]]
