"""Scaffold test for a promoted factor (generated at Gate 3).

Extend with factor-specific assertions during the git-diff review.
"""

from __future__ import annotations

from importlib import import_module

import pandas as pd

EXPECTED_FACTOR_ID = (
    'paper_reversal_momentum_proxy_v2'
)

FACTOR_CLASS_NAME = (
    'PaperReversalMomentumProxyV2'
)


def _factor():
    factor_module = import_module(
        f"quant_system.factors.library.promoted.{EXPECTED_FACTOR_ID}"
    )
    return getattr(factor_module, FACTOR_CLASS_NAME)()


def _synthetic_ohlcv(rows: int = 272) -> pd.DataFrame:
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


def test_factor_metadata() -> None:
    factor = _factor()
    metadata = factor.metadata
    assert metadata.factor_id == EXPECTED_FACTOR_ID
    assert metadata.factor_name
    assert metadata.factor_version
    assert metadata.lookback > 0
    assert metadata.description


def test_factor_computes_on_synthetic_ohlcv() -> None:
    factor = _factor()
    result = factor.compute(_synthetic_ohlcv())
    assert not result.empty
    assert set(result["factor_id"]) == {EXPECTED_FACTOR_ID}
    assert result["value"].notna().all()
