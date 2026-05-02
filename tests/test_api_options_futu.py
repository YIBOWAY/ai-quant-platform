from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.data.providers.futu import FutuProviderError
from quant_system.data.schema import normalize_ohlcv_dataframe


def _history() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2026-01-02", "2026-05-01", freq="B", tz="UTC")
    for index, timestamp in enumerate(dates):
        price = 220.0 + index * 0.2
        rows.append(
            {
                "symbol": "AAPL",
                "timestamp": timestamp,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 1000,
                "event_ts": timestamp,
                "knowledge_ts": timestamp,
            }
        )
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="futu", interval="1d")


def _option_quotes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "US.AAPL260619P250000",
                "underlying": "US.AAPL",
                "option_type": "PUT",
                "expiry": "2026-06-19",
                "strike": 250.0,
                "bid": 2.0,
                "ask": 2.2,
                "volume": 100,
                "open_interest": 500,
                "implied_volatility": 0.45,
                "delta": -0.25,
            }
        ]
    )


def test_options_chain_returns_futu_contracts(tmp_path, monkeypatch) -> None:
    def fake_fetch(self, underlying, *, expiration, option_type="ALL"):
        return _option_quotes()

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        fake_fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/options/chain",
        params={"ticker": "AAPL", "expiration": "2026-06-19", "provider": "futu"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "futu"
    assert payload["contracts"][0]["symbol"] == "US.AAPL260619P250000"
    assert payload["safety"]["live_trading_enabled"] is False


def test_options_screener_returns_candidates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_expirations",
        lambda self, underlying: pd.DataFrame(
            [{"strike_time": "2026-06-19", "option_expiry_date_distance": 48}]
        ),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        lambda self, underlying, *, expiration, option_type="ALL": _option_quotes(),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {"symbol": "US.AAPL", "last": 280.0},
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/screener",
        json={
            "ticker": "AAPL",
            "strategy_type": "sell_put",
            "min_iv": 0.2,
            "max_delta": 0.35,
            "min_premium": 1.0,
            "max_spread_pct": 0.2,
            "provider": "futu",
            "history_start": "2026-01-02",
            "history_end": "2026-05-01",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "futu"
    assert payload["candidates"][0]["rating"] == "Strong"
    assert payload["safety"]["paper_trading"] is True


def test_options_screener_rejects_non_futu_provider(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/options/chain",
        params={"ticker": "AAPL", "expiration": "2026-06-19", "provider": "sample"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_options_provider"


def test_options_route_maps_futu_error(tmp_path, monkeypatch) -> None:
    def fake_fetch(self, underlying, *, expiration, option_type="ALL"):
        raise FutuProviderError("permission_denied", "missing options permission")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        fake_fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get(
        "/api/options/chain",
        params={"ticker": "AAPL", "expiration": "2026-06-19", "provider": "futu"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"
