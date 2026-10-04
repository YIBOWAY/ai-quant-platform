from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import FutuSettings, Settings
from quant_system.data.providers.longbridge import LongbridgeProviderError
from quant_system.data.schema import normalize_ohlcv_dataframe


def test_explicit_longbridge_history_attributes_source(tmp_path, monkeypatch):
    def fetch(_self, symbols, *, start, end, interval):
        assert symbols == ["AAPL"]
        assert (start, end, interval) == ("2024-01-02", "2024-01-02", "1d")
        return normalize_ohlcv_dataframe(
            pd.DataFrame(
                [
                    {
                        "symbol": "AAPL",
                        "timestamp": "2024-01-02T00:00:00Z",
                        "open": 10,
                        "high": 12,
                        "low": 9,
                        "close": 11,
                        "volume": 100,
                        "knowledge_ts": "2024-01-03T00:00:00Z",
                        "price_adjustment": "forward",
                    }
                ]
            ),
            provider="longbridge",
            interval="1d",
        )

    monkeypatch.setattr(
        "quant_system.data.provider_factory.LongbridgeMarketDataProvider.fetch_ohlcv",
        fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-02",
            "provider": "longbridge",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "longbridge"
    assert payload["metadata"]["provider"] == "longbridge"
    assert payload["metadata"]["requested_provider"] == "longbridge"
    assert payload["safety"]["live_trading_enabled"] is False


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("permission_denied", 403),
        ("quota_exceeded", 429),
        ("rate_limited", 429),
        ("timeout", 503),
        ("not_installed", 503),
        ("empty", 404),
        ("incomplete_data", 502),
        ("invalid_data", 502),
        ("invalid_params", 400),
    ],
)
def test_longbridge_errors_have_safe_explicit_status(tmp_path, monkeypatch, code, status):
    def fetch(*_args, **_kwargs):
        raise LongbridgeProviderError(code, "credential-that-must-not-appear")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.LongbridgeMarketDataProvider.fetch_ohlcv",
        fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-05",
            "provider": "longbridge",
        },
    )
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["provider"] == "longbridge"
    assert "credential-that-must-not-appear" not in response.text


def test_explicit_futu_failure_does_not_call_longbridge(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("explicit Futu must not fall back to Longbridge")

    monkeypatch.setattr(
        "quant_system.data.provider_factory.LongbridgeMarketDataProvider.fetch_ohlcv",
        forbidden,
    )
    client = TestClient(
        create_app(
            settings=Settings(futu=FutuSettings(enabled=False)),
            output_dir=tmp_path,
        )
    )
    response = client.get(
        "/api/market-data/history",
        params={
            "ticker": "AAPL",
            "start": "2024-01-02",
            "end": "2024-01-05",
            "provider": "futu",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["provider"] == "futu"
