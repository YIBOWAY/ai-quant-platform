from __future__ import annotations

import pandas as pd
import pytest

from quant_system.factors.evaluation import (
    calculate_ic_decay,
    calculate_ic_ir,
    calculate_information_coefficients,
)


def _panel() -> pd.DataFrame:
    # 3 symbols × 40 days; factor = next-day return (perfect foresight-ish)
    import random as _random

    rng = _random.Random(31)
    rows = []
    for symbol, drift in [("AAA", 0.001), ("BBB", 0.002), ("CCC", 0.003)]:
        closes = [100.0]
        for _ in range(40):
            closes.append(closes[-1] * (1 + drift + rng.gauss(0, 0.0005)))
        dates = pd.date_range("2026-01-01", periods=len(closes), freq="D")
        for index, close in enumerate(closes):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": dates[index].strftime("%Y-%m-%d"),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000.0,
                }
            )
    return pd.DataFrame(rows)


def _factor_frame(ohlcv: pd.DataFrame, *, shift: int = 2) -> pd.DataFrame:
    frame = ohlcv.copy()
    frame["factor_id"] = "f_test"
    frame["signal_ts"] = frame["timestamp"]
    # open == close in this panel, so the open-to-open h=1 label c(t+2)/c(t+1) - 1 is
    # exactly pct_change().shift(-2).
    frame["value"] = frame.groupby("symbol")["close"].transform(
        lambda s: s.pct_change().shift(-shift)
    )
    return frame


def test_ic_ir_is_positive_for_predictive_factor() -> None:
    ohlcv = _panel()
    ic_frame = calculate_information_coefficients(_factor_frame(ohlcv), ohlcv)
    summary = calculate_ic_ir(ic_frame)

    assert summary["factor_id"] == "f_test"
    assert summary["ic_mean"] == pytest.approx(1.0, abs=1e-9)
    assert summary["ic_ir"] >= 5.0  # perfect rank alignment -> tiny std
    assert summary["n_signals"] > 10


def test_one_day_stale_factor_is_not_the_new_label() -> None:
    ohlcv = _panel()
    ic_frame = calculate_information_coefficients(_factor_frame(ohlcv, shift=1), ohlcv)
    summary = calculate_ic_ir(ic_frame)

    # Negative control for the rescoped seal above: the old one-day-stale factor does not
    # reproduce the forward label, so its IC must stay strictly below the perfect value.
    assert summary["ic_mean"] < 1.0


def test_ic_decay_reports_multiple_horizons() -> None:
    ohlcv = _panel()
    decay = calculate_ic_decay(_factor_frame(ohlcv), ohlcv, horizons=(1, 5))

    assert [row["horizon"] for row in decay] == [1, 5]
    assert all(row["rank_ic"] is not None for row in decay)
    assert decay[0]["rank_ic"] is not None and decay[1]["rank_ic"] is not None
