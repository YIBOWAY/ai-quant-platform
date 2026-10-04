from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location(
    "pilot", Path(__file__).parents[1] / "scripts/phase2_public_price_pilot.py"
)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def calendar_and_close():
    days = pd.bdate_range("2014-12-01", "2016-03-31", tz="UTC")
    values = pd.Series(
        100 + np.arange(len(days)) * 0.1 + np.sin(np.arange(len(days))) * 0.03, index=days
    )
    return days, values


def test_momentum_uses_exact_calendar_months_and_rejects_missing_month():
    days, close = calendar_and_close()
    result = pilot.monthly_signal_values(close, days)
    expected = (
        close[close.index.strftime("%Y-%m") == "2015-12"].iloc[-1]
        / close[close.index.strftime("%Y-%m") == "2015-01"].iloc[-1]
        - 1
    )
    assert np.isclose(result.loc["2016-01", "Mom12m"], expected)
    missing = close[close.index.strftime("%Y-%m") != "2015-06"]
    assert pd.isna(pilot.monthly_signal_values(missing, days).loc["2016-01", "Mom12m"])


def test_realized_volatility_uses_current_completed_month_without_missing_days():
    days, close = calendar_and_close()
    result = pilot.monthly_signal_values(close, days)
    returns = close.pct_change(fill_method=None)
    expected = -returns[returns.index.strftime("%Y-%m") == "2016-01"].std(ddof=1)
    assert np.isclose(result.loc["2016-01", "generic_monthly_realized_volatility"], expected)
    altered = close.copy()
    altered.loc[altered.index > "2016-01-31"] *= 100
    assert result.loc["2016-01"].equals(pilot.monthly_signal_values(altered, days).loc["2016-01"])
    missing = close.drop(close[close.index.strftime("%Y-%m") == "2016-01"].index[8])
    assert pd.isna(
        pilot.monthly_signal_values(missing, days).loc[
            "2016-01", "generic_monthly_realized_volatility"
        ]
    )


def test_missing_next_month_first_open_never_moves_to_second_day():
    days, close = calendar_and_close()
    first = days[days.strftime("%Y-%m") == "2016-02"][0]
    result = pilot.monthly_forward_labels(close.drop(first), days)
    assert pd.isna(result.loc["2016-01", "forward_return"])
    assert result.loc["2016-01", "label_reason"] == "entry_open_missing"


def test_groups_are_formed_before_labels_and_missing_extreme_group_is_unknown():
    scores = pd.DataFrame(
        {
            "symbol": list("ABCDEFGHIJ"),
            "entity_id": list("abcdefghij"),
            "value": np.arange(10, dtype=float),
        }
    )
    formed = pilot.assign_quintiles(scores)
    joined = formed.assign(forward_return=np.arange(10, dtype=float) / 100)
    complete = pilot.month_statistics(joined)
    missing = joined.copy()
    missing.loc[missing.symbol == "J", "forward_return"] = np.nan
    result = pilot.month_statistics(missing)
    assert joined.quintile.equals(missing.quintile)
    assert complete["q5_q1"] is not None
    assert result["q5_q1"] is None
    assert result["Q5_label_coverage"] == 0.5
