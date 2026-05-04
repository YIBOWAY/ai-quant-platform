from __future__ import annotations

import pandas as pd
import pytest

from quant_system.options.option_data import normalize_option_records


def test_normalize_option_records_computes_mid_and_normalizes_iv() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "us.aapl260508c200000",
                "underlying": "US.AAPL",
                "option_type": "CALL",
                "expiry": "2026-05-08",
                "strike": 200.0,
                "update_time": "2026-05-01T20:00:00Z",
                "last": 1.15,
                "bid": 1.1,
                "ask": 1.3,
                "bid_size": 10,
                "ask_size": 12,
                "volume": 25,
                "turnover": 1000,
                "open_interest": 500,
                "implied_volatility": 24.5,
                "delta": 0.42,
                "gamma": 0.08,
                "theta": -0.03,
                "vega": 0.11,
                "rho": 0.02,
                "contract_size": 100,
            }
        ]
    )

    records = normalize_option_records(
        frame,
        stale_after_minutes=30,
        now=pd.Timestamp("2026-05-01T20:10:00Z"),
    )

    assert len(records) == 1
    record = records[0]
    assert record.symbol == "US.AAPL260508C200000"
    assert record.option_type == "CALL"
    assert record.mid == pytest.approx(1.2)
    assert record.implied_volatility == pytest.approx(0.245)
    assert record.contract_size == 100
    assert record.data_quality_warnings == []


def test_normalize_option_records_attaches_data_quality_warnings() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "US.AAPL260508P200000",
                "underlying": "US.AAPL",
                "option_type": "PUT",
                "expiry": "2026-05-08",
                "strike": 200.0,
                "update_time": "2026-05-01T19:00:00Z",
                "bid": 1.4,
                "ask": 1.2,
                "volume": 0,
                "open_interest": 0,
            }
        ]
    )

    record = normalize_option_records(
        frame,
        stale_after_minutes=30,
        now=pd.Timestamp("2026-05-01T20:00:00Z"),
    )[0]

    assert record.mid is None
    assert set(record.data_quality_warnings) >= {
        "invalid_bid_ask",
        "missing_iv",
        "missing_delta",
        "missing_gamma",
        "missing_theta",
        "missing_vega",
        "missing_rho",
        "zero_open_interest",
        "zero_volume",
        "missing_contract_size",
        "stale_quote",
    }


def test_normalize_option_records_rejects_missing_symbol() -> None:
    frame = pd.DataFrame([{"symbol": None, "bid": 1.0, "ask": 1.1}])

    with pytest.raises(ValueError, match="option symbol is required"):
        normalize_option_records(frame)
