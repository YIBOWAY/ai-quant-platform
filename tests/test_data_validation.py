import pandas as pd

from quant_system.data.validation import validate_ohlcv


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["SPY", "SPY"],
            "timestamp": pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True),
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1200],
            "provider": ["sample", "sample"],
            "interval": ["1d", "1d"],
            "event_ts": pd.to_datetime(["2024-01-02", "2024-01-03"], utc=True),
            "knowledge_ts": pd.to_datetime(["2024-01-03", "2024-01-04"], utc=True),
        }
    )


def test_validate_ohlcv_accepts_clean_data() -> None:
    report = validate_ohlcv(_valid_frame())

    assert report.passed is True
    assert report.row_count == 2
    assert report.symbol_count == 1
    assert report.issue_count == 0


def test_validate_ohlcv_detects_duplicate_symbol_timestamp() -> None:
    frame = pd.concat([_valid_frame(), _valid_frame().iloc[[0]]], ignore_index=True)

    report = validate_ohlcv(frame)

    assert report.passed is False
    assert any(issue.check == "duplicate_symbol_timestamp" for issue in report.issues)


def test_validate_ohlcv_detects_invalid_price_relationship() -> None:
    frame = _valid_frame()
    frame.loc[0, "high"] = 98.0

    report = validate_ohlcv(frame)

    assert report.passed is False
    assert any(issue.check == "ohlc_price_bounds" for issue in report.issues)


def test_validate_ohlcv_detects_negative_volume() -> None:
    frame = _valid_frame()
    frame.loc[0, "volume"] = -1

    report = validate_ohlcv(frame)

    assert report.passed is False
    assert any(issue.check == "non_negative_volume" for issue in report.issues)

