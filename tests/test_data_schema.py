import pandas as pd
import pytest

from quant_system.data.schema import REQUIRED_OHLCV_COLUMNS, normalize_ohlcv_dataframe


def test_normalize_ohlcv_dataframe_adds_phase_1_metadata() -> None:
    raw = pd.DataFrame(
        {
            "symbol": ["spy"],
            "timestamp": ["2024-01-02"],
            "open": [100],
            "high": [101],
            "low": [99],
            "close": [100.5],
            "volume": [1_000],
        }
    )

    normalized = normalize_ohlcv_dataframe(raw, provider="sample", interval="1d")

    assert set(REQUIRED_OHLCV_COLUMNS).issubset(normalized.columns)
    assert normalized.loc[0, "symbol"] == "SPY"
    assert normalized.loc[0, "provider"] == "sample"
    assert normalized.loc[0, "interval"] == "1d"
    assert normalized.loc[0, "event_ts"] == normalized.loc[0, "timestamp"]
    assert "knowledge_ts" in normalized.columns


def test_normalize_ohlcv_dataframe_rejects_missing_required_columns() -> None:
    raw = pd.DataFrame({"symbol": ["SPY"], "close": [100.0]})

    with pytest.raises(ValueError, match="missing required OHLCV columns"):
        normalize_ohlcv_dataframe(raw, provider="sample", interval="1d")

