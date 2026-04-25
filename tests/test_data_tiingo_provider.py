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


def test_tiingo_provider_requires_api_token() -> None:
    provider = TiingoEODProvider(api_token=None)

    with pytest.raises(ValueError, match="Tiingo API token is required"):
        provider.fetch_ohlcv(["AAPL"], start="2024-01-02", end="2024-01-02")
