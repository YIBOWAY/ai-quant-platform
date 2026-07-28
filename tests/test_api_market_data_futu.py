from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import ApiKeySettings, DataSettings, FutuSettings, Settings
from quant_system.data.providers.futu import FutuMarketDataProvider, FutuProviderError
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


def test_futu_snapshot_preserves_previous_regular_close() -> None:
    class Context:
        def get_market_snapshot(self, symbols):
            assert symbols == ["US.AAPL"]
            return 0, pd.DataFrame(
                [
                    {
                        "code": "US.AAPL",
                        "update_time": "2026-07-28 15:59:59",
                        "last_price": 105.0,
                        "prev_close_price": 100.0,
                    }
                ]
            )

        def close(self):
            return None

    provider = FutuMarketDataProvider(
        context_factory=lambda _host, _port: Context(),
        sdk_loader=lambda: SimpleNamespace(RET_OK=0),
    )

    snapshot = provider.fetch_market_snapshots(["US.AAPL"])

    assert snapshot.loc[0, "last"] == 105.0
    assert snapshot.loc[0, "prev_close"] == 100.0


def test_market_data_history_uses_futu_provider(tmp_path, monkeypatch) -> None:
    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        assert symbols == ["AAPL"]
        assert interval == "1d"
        return _fake_futu_frame()

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv",
        fake_fetch,
    )
    client = TestClient(
        create_app(
            settings=Settings(futu=FutuSettings(enabled=True)),
            output_dir=tmp_path,
        )
    )

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
    client = TestClient(
        create_app(
            settings=Settings(futu=FutuSettings(enabled=True)),
            output_dir=tmp_path,
        )
    )

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


def test_market_data_history_rejects_unavailable_requested_provider(tmp_path) -> None:
    settings = Settings(api_keys=ApiKeySettings(tiingo_api_token=None))
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "tiingo",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "provider_unavailable"
    assert payload["detail"]["provider"] == "tiingo"
    assert payload["safety"]["live_trading_enabled"] is False


def test_market_data_history_rejects_unknown_explicit_provider(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "provider": "polygon",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "provider_unavailable"
    assert payload["detail"]["provider"] == "polygon"
    assert payload["safety"]["live_trading_enabled"] is False


def test_market_data_history_rejects_intraday_for_non_futu_provider(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "freq": "1h",
            "provider": "sample",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["detail"]["code"] == "unsupported_interval"
    assert payload["detail"]["provider"] == "sample"
    assert payload["detail"]["interval"] == "1h"
    assert payload["safety"]["live_trading_enabled"] is False


def test_market_data_history_does_not_fallback_to_sample_for_intraday_default(
    tmp_path,
    monkeypatch,
) -> None:
    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        raise FutuProviderError("opend_unavailable", "unable to connect to OpenD")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv",
        fake_fetch,
    )
    settings = Settings(
        data=DataSettings(default_data_provider="futu"),
        futu=FutuSettings(enabled=True),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-12",
            "freq": "1h",
        },
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["detail"]["code"] == "opend_unavailable"
    assert payload["safety"]["live_trading_enabled"] is False


def test_market_data_history_falls_back_when_default_futu_provider_fails(
    tmp_path,
    monkeypatch,
) -> None:
    def fake_fetch(self, symbols, *, start, end, interval="1d"):
        raise FutuProviderError("opend_unavailable", "unable to connect to OpenD")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.FutuMarketDataProvider.fetch_ohlcv",
        fake_fetch,
    )
    settings = Settings(
        data=DataSettings(default_data_provider="futu"),
        futu=FutuSettings(enabled=True),
    )
    client = TestClient(create_app(settings=settings, output_dir=tmp_path))

    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-12",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"].startswith("sample (futu failed: opend_unavailable)")
    assert payload["metadata"]["requested_provider"] == "futu"
    assert payload["rows"]
