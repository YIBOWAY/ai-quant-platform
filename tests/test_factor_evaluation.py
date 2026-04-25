import pandas as pd
import pytest

from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.factors.evaluation import (
    calculate_information_coefficients,
    calculate_quantile_returns,
)


def _evaluation_frame() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-02", periods=3, freq="B", tz="UTC")
    closes = {
        "AAA": [100.0, 110.0, 120.0],
        "BBB": [100.0, 105.0, 110.0],
        "CCC": [100.0, 90.0, 80.0],
    }
    rows = []
    for symbol, values in closes.items():
        for timestamp, close in zip(timestamps, values, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1_000,
                }
            )
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="test", interval="1d")


def _factor_results() -> pd.DataFrame:
    signal_ts = pd.Timestamp("2024-01-02", tz="UTC")
    tradeable_ts = pd.Timestamp("2024-01-03", tz="UTC")
    return pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "signal_ts": [signal_ts, signal_ts, signal_ts],
            "tradeable_ts": [tradeable_ts, tradeable_ts, tradeable_ts],
            "factor_id": ["test_alpha", "test_alpha", "test_alpha"],
            "factor_version": ["0.1.0", "0.1.0", "0.1.0"],
            "factor_name": ["Test Alpha", "Test Alpha", "Test Alpha"],
            "lookback": [1, 1, 1],
            "value": [3.0, 2.0, 1.0],
        }
    )


def test_information_coefficients_compare_signal_to_future_return() -> None:
    ic = calculate_information_coefficients(_factor_results(), _evaluation_frame(), horizon=1)

    assert len(ic) == 1
    assert ic.loc[0, "ic"] > 0.95
    assert ic.loc[0, "rank_ic"] == pytest.approx(1.0)
    assert ic.loc[0, "n"] == 3


def test_quantile_returns_sort_future_returns_by_factor_value() -> None:
    quantiles = calculate_quantile_returns(
        _factor_results(),
        _evaluation_frame(),
        quantiles=3,
        horizon=1,
    )

    top = quantiles[quantiles["quantile"] == 3].iloc[0]
    bottom = quantiles[quantiles["quantile"] == 1].iloc[0]

    assert top["mean_forward_return"] > 0
    assert bottom["mean_forward_return"] < 0
