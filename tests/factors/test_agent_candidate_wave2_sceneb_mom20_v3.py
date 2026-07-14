"""Scaffold test for promoted factor 'agent_candidate_wave2_sceneb_mom20_v3' (generated at Gate 3).

Extend with factor-specific assertions during the git-diff review.
"""

from __future__ import annotations

import pandas as pd

from quant_system.factors.library.promoted.agent_candidate_wave2_sceneb_mom20_v3 import AgentCandidateFactor


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


def test_agent_candidate_wave2_sceneb_mom20_v3_metadata() -> None:
    factor = AgentCandidateFactor()
    metadata = factor.metadata
    assert metadata.factor_id == "agent_candidate_wave2_sceneb_mom20_v3"
    assert metadata.factor_name
    assert metadata.factor_version
    assert metadata.lookback > 0
    assert metadata.description


def test_agent_candidate_wave2_sceneb_mom20_v3_computes_on_synthetic_ohlcv() -> None:
    factor = AgentCandidateFactor()
    result = factor.compute(_synthetic_ohlcv())
    assert not result.empty
    assert set(result["factor_id"]) == {"agent_candidate_wave2_sceneb_mom20_v3"}
    assert result["value"].notna().all()
