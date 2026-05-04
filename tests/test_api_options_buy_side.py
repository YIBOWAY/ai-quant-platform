from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.data.providers.futu import FutuProviderError


def _chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "US.AAPL20260619C100000",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 100.0,
                "bid": 5.0,
                "ask": 5.4,
                "implied_volatility": 0.25,
                "delta": 0.56,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 800,
                "volume": 100,
                "option_expiry_date_distance": 30,
            },
            {
                "symbol": "US.AAPL20260619C110000",
                "option_type": "CALL",
                "expiry": "2026-06-19",
                "strike": 110.0,
                "bid": 1.3,
                "ask": 1.5,
                "implied_volatility": 0.24,
                "delta": 0.24,
                "gamma": 0.02,
                "theta": -0.04,
                "vega": 0.12,
                "open_interest": 500,
                "volume": 80,
                "option_expiry_date_distance": 30,
            },
        ]
    )


def test_api_buy_side_assistant_returns_recommendations(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {"symbol": "US.AAPL", "last": 100.0},
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, *, start_expiration, end_expiration, option_type="CALL": _chain(),
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "max_loss_budget": 800.0,
            "provider": "futu",
            "as_of_date": "2026-05-20",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["recommendations"]
    assert payload["recommendations"][0]["rank"] == 1
    assert payload["recommendations"][0]["legs"]
    assert payload["recommendations"][0]["net_debit"] is not None
    assert payload["recommendations"][0]["scenario_summary"]["probability_not_calculated"] is True
    assert "safety" in payload
    assert payload["safety"]["live_trading_enabled"] is False


def test_api_buy_side_assistant_accepts_scenario_grid_inputs(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {"symbol": "US.AAPL", "last": 100.0},
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        lambda self, underlying, *, start_expiration, end_expiration, option_type="CALL": _chain(),
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "max_loss_budget": 800.0,
            "provider": "futu",
            "as_of_date": "2026-05-20",
            "scenario_spot_changes": [-15, 0, 15],
            "scenario_iv_changes": [-10, 0],
            "scenario_days_passed": [0, 14],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["thesis"]["scenario_spot_changes"] == [-15.0, 0.0, 15.0]
    assert payload["thesis"]["scenario_iv_changes"] == [-10.0, 0.0]
    assert payload["thesis"]["scenario_days_passed"] == [0, 14]


def test_api_buy_side_contract_is_documented(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    operation = client.get("/openapi.json").json()["paths"][
        "/api/options/buy-side/assistant"
    ]["post"]

    request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    response_ref = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert request_ref.endswith("/BuySideAssistantRequest")
    assert response_ref.endswith("/BuySideAssistantResponse")
    assert "422" in operation["responses"]
    assert "404" in operation["responses"]
    assert "503" in operation["responses"]


def test_api_buy_side_assistant_rejects_non_futu_provider(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "sample",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_options_provider"


def test_api_buy_side_assistant_maps_missing_chain_to_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {"symbol": "US.AAPL", "last": 100.0},
    )

    def fake_fetch(self, underlying, *, start_expiration, end_expiration, option_type="CALL"):
        raise FutuProviderError("no_data", "no option chain available")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes_range",
        fake_fetch,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "no_data"


def test_api_buy_side_assistant_maps_opend_unavailable_to_503(
    tmp_path,
    monkeypatch,
) -> None:
    def fake_snapshot(self, symbol):
        raise FutuProviderError("opend_unavailable", "OpenD is not reachable")

    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        fake_snapshot,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_price": 112.0,
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "opend_unavailable"


def test_api_buy_side_assistant_invalid_thesis_returns_422(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.post(
        "/api/options/buy-side/assistant",
        json={
            "ticker": "AAPL",
            "view_type": "short_term_conservative_bullish",
            "target_date": "2026-08-21",
            "provider": "futu",
        },
    )

    assert response.status_code == 422
