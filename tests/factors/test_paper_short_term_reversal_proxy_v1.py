"""Scaffold test for promoted factor 'paper_short_term_reversal_proxy_v1' (generated at Gate 3).

Extend with factor-specific assertions during the git-diff review.
"""

from __future__ import annotations

import pandas as pd

from quant_system.factors.library.promoted.paper_short_term_reversal_proxy_v1 import PaperShortTermReversalProxy


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


def test_paper_short_term_reversal_proxy_v1_metadata() -> None:
    factor = PaperShortTermReversalProxy()
    metadata = factor.metadata
    assert metadata.factor_id == "paper_short_term_reversal_proxy_v1"
    assert metadata.factor_name
    assert metadata.factor_version
    assert metadata.lookback > 0
    assert metadata.description


def test_paper_short_term_reversal_proxy_v1_computes_on_synthetic_ohlcv() -> None:
    factor = PaperShortTermReversalProxy()
    result = factor.compute(_synthetic_ohlcv())
    assert not result.empty
    assert set(result["factor_id"]) == {"paper_short_term_reversal_proxy_v1"}
    assert result["value"].notna().all()
