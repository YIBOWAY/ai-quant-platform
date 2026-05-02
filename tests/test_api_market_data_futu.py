from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.data.providers.futu import FutuProviderError
from quant_system.data.schema import normalize_ohlcv_dataframe


def _fake_futu_frame() -> pd.DataFrame:
    timestamp = pd.Timestamp("2024-01-02", tz="UTC")
    return normalize_ohlcv_dataframe(
        pd.DataFrame(
            [
                {
                    "symbol": "AAPL",
                    "timestamp": timestamp,
                    "open": 185.22,
                    "high": 186.50,
                    "low": 181.99,
                    "close": 183.73,
                    "volume": 82488674,
                    "event_ts": timestamp,
                    "knowledge_ts": timestamp + pd.Timedelta(minutes=1),
                }
            ]
        ),
        provider="futu",
        interval="1d",
    )


def test_market_data_history_uses_futu_provider(tmp_path, monkeypatch) -> None:
    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        assert symbols == ["AAPL"]
        assert interval == "1d"
        return _fake_futu_frame()

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv",
        fake_fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "freq": "1d",
            "provider": "futu",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "futu"
    assert payload["row_count"] == 1
    assert payload["rows"][0]["close"] == 183.73
    assert payload["safety"]["live_trading_enabled"] is False


def test_market_data_history_maps_futu_error(tmp_path, monkeypatch) -> None:
    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        raise FutuProviderError("opend_unavailable", "unable to connect to OpenD")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv",
        fake_fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["code"] == "opend_unavailable"
    assert payload["safety"]["live_trading_enabled"] is False

