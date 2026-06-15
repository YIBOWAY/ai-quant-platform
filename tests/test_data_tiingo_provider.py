import pandas as pd
import pytest

from quant_system.data.providers.tiingo import TiingoEODProvider


def test_tiingo_provider_converts_response_to_canonical_ohlcv() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        assert "AAPL/prices" in url
        assert headers["Authorization"] == "Token test-token"
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 187.15,
                "high": 188.44,
                "low": 183.89,
                "close": 185.64,
                "volume": 82488700,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert len(frame) == 1
    assert frame.loc[0, "symbol"] == "AAPL"
    assert frame.loc[0, "provider"] == "tiingo"
    assert frame.loc[0, "close"] == 185.64
    # knowledge_ts must be strictly later than event_ts so PIT replays do not
    # see EOD bars before they could have been observed.
    assert frame.loc[0, "knowledge_ts"] > frame.loc[0, "event_ts"]
    assert frame.loc[0, "knowledge_ts"] >= pd.Timestamp("2024-01-02", tz="UTC")


def test_tiingo_provider_prefers_adjusted_ohlcv_when_available() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "adjOpen": 50.0,
                "adjHigh": 55.0,
                "adjLow": 45.0,
                "adjClose": 52.5,
                "adjVolume": 2000,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert frame.loc[0, "open"] == 50.0
    assert frame.loc[0, "high"] == 55.0
    assert frame.loc[0, "low"] == 45.0
    assert frame.loc[0, "close"] == 52.5
    assert frame.loc[0, "volume"] == 2000
    assert frame.loc[0, "price_adjustment"] == "adjusted"


def test_tiingo_provider_falls_back_when_adjusted_values_are_missing() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "adjOpen": None,
                "adjHigh": None,
                "adjLow": None,
                "adjClose": None,
                "adjVolume": None,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert frame.loc[0, "open"] == 100.0
    assert frame.loc[0, "high"] == 110.0
    assert frame.loc[0, "low"] == 90.0
    assert frame.loc[0, "close"] == 105.0
    assert frame.loc[0, "volume"] == 1000
    assert frame.loc[0, "price_adjustment"] == "raw"


def test_tiingo_provider_marks_mixed_adjusted_and_raw_values() -> None:
    def fake_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "date": "2024-01-02T00:00:00.000Z",
                "open": 100.0,
                "high": 110.0,
                "low": 90.0,
                "close": 105.0,
                "volume": 1000,
                "adjOpen": 50.0,
                "adjHigh": None,
                "adjLow": 45.0,
                "adjClose": None,
                "adjVolume": 2000,
            }
        ]

    provider = TiingoEODProvider(api_token="test-token", get_json=fake_get_json)

    frame = provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")

    assert frame.loc[0, "open"] == 50.0
    assert frame.loc[0, "high"] == 110.0
    assert frame.loc[0, "low"] == 45.0
    assert frame.loc[0, "close"] == 105.0
    assert frame.loc[0, "volume"] == 2000
    assert frame.loc[0, "price_adjustment"] == "mixed"


def test_tiingo_provider_requires_api_token() -> None:
    provider = TiingoEODProvider(api_token=None)

    with pytest.raises(ValueError, match="Tiingo API token is required"):
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")


def test_tiingo_provider_rejects_intraday_interval() -> None:
    provider = TiingoEODProvider(api_token="test-token", get_json=lambda _url, _headers: [])

    with pytest.raises(ValueError, match="Tiingo provider only supports daily"):
        provider.fetch_ohlcv(
            ["AAPL"],
            start="2024-01-02",
            end="2024-01-02",
            interval="1h",
        )
