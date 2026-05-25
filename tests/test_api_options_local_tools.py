from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.config.settings import Settings
from quant_system.data.schema import normalize_ohlcv_dataframe


def _history() -> pd.DataFrame:
    rows = []
    dates = pd.date_range("2025-11-01", "2026-05-20", freq="B", tz="UTC")
    for index, timestamp in enumerate(dates):
        price = 100.0 + index * 0.1
        rows.append(
            {
                "symbol": "AAPL",
                "timestamp": timestamp,
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price,
                "volume": 1_000_000,
                "event_ts": timestamp,
                "knowledge_ts": timestamp,
            }
        )
    return normalize_ohlcv_dataframe(pd.DataFrame(rows), provider="futu", interval="1d")


def _expirations() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"strike_time": "2026-06-19", "option_expiry_date_distance": 30},
            {"strike_time": "2026-07-17", "option_expiry_date_distance": 58},
        ]
    )


def _chain() -> pd.DataFrame:
    rows = []
    for expiry in ("2026-06-19", "2026-07-17"):
        for strike in (90.0, 95.0, 100.0, 105.0, 110.0):
            rows.append(
                {
                    "symbol": f"US.AAPL{expiry.replace('-', '')}C{int(strike * 1000):08d}",
                    "option_type": "CALL",
                    "expiry": expiry,
                    "strike": strike,
                    "bid": max(0.5, 5.0 - abs(strike - 100.0) * 0.2),
                    "ask": max(0.7, 5.3 - abs(strike - 100.0) * 0.2),
                    "implied_volatility": 0.25 + abs(strike - 100.0) * 0.002,
                    "delta": max(0.1, min(0.9, 0.5 + (100.0 - strike) * 0.04)),
                    "gamma": 0.02,
                    "theta": -0.05,
                    "vega": 0.12,
                    "volume": 100,
                    "open_interest": 500,
                }
            )
            rows.append(
                {
                    "symbol": f"US.AAPL{expiry.replace('-', '')}P{int(strike * 1000):08d}",
                    "option_type": "PUT",
                    "expiry": expiry,
                    "strike": strike,
                    "bid": max(0.5, 5.0 - abs(strike - 100.0) * 0.2),
                    "ask": max(0.7, 5.3 - abs(strike - 100.0) * 0.2),
                    "implied_volatility": 0.27 + abs(strike - 100.0) * 0.003,
                    "delta": -max(0.1, min(0.9, 0.5 + (strike - 100.0) * 0.04)),
                    "gamma": 0.02,
                    "theta": -0.05,
                    "vega": 0.12,
                    "volume": 100,
                    "open_interest": 500,
                }
            )
    return pd.DataFrame(rows)


def _patch_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_underlying_snapshot",
        lambda self, symbol: {"symbol": "US.AAPL", "last": 100.0},
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_expirations",
        lambda self, underlying: _expirations(),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes",
        lambda self, underlying, *, expiration, option_type="ALL": _chain().loc[
            _chain()["expiry"] == expiration
        ].reset_index(drop=True),
    )
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_ohlcv",
        lambda self, symbols, *, start, end, interval="1d": _history(),
    )


def test_options_snapshot_endpoint_uses_futu_provider_shape(tmp_path, monkeypatch) -> None:
    _patch_provider(monkeypatch)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/options/snapshot/AAPL")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["source"] == "futu"
    assert payload["atm_iv"] > 0
    assert payload["hv_30d"] is not None
    assert payload["safety"]["live_trading_enabled"] is False


def test_options_vol_surface_endpoint_returns_grid(tmp_path, monkeypatch) -> None:
    _patch_provider(monkeypatch)
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    response = client.get("/api/options/tools/vol-surface/AAPL")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "AAPL"
    assert payload["surface"]["expiry_axis"] == ["2026-06-19", "2026-07-17"]
    assert payload["surface"]["moneyness_axis"]
    assert payload["surface"]["iv_grid"]


def test_options_math_tool_endpoints(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    greeks = client.post(
        "/api/options/tools/greeks",
        json={
            "spot": 100,
            "strike": 100,
            "expiry_days": 30,
            "iv": 0.25,
            "option_type": "call",
        },
    )
    assert greeks.status_code == 200
    assert greeks.json()["delta"] > 0

    simulator = client.post(
        "/api/options/tools/simulate",
        json={
            "symbol": "AAPL",
            "spot": 100,
            "legs": [
                {
                    "action": "buy",
                    "option_type": "call",
                    "strike": 100,
                    "expiry_days": 30,
                    "iv": 0.25,
                    "entry_price": 5,
                }
            ],
        },
    )
    assert simulator.status_code == 200
    assert simulator.json()["pnl_at_expiry"]["price_axis"]


def test_options_strategy_template_endpoints(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    templates = client.get("/api/options/tools/strategy/templates")
    assert templates.status_code == 200
    assert any(item["id"] == "bull_call_spread" for item in templates.json()["templates"])

    built = client.post(
        "/api/options/tools/strategy/build",
        json={
            "template_id": "bull_call_spread",
            "spot": 100,
            "expiry_days": 30,
            "strikes": [95, 100, 105, 110],
            "iv": 0.25,
        },
    )
    assert built.status_code == 200
    assert built.json()["strategy"] == "Bull Call Spread"


def test_options_local_ranking_and_research_endpoints(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    score_response = client.post(
        "/api/options/tools/score-contracts",
        json={
            "spot": 100,
            "objective": "sell_premium",
            "contracts": [
                {
                    "symbol": "BAD",
                    "option_type": "PUT",
                    "strike": 95,
                    "bid": 0.4,
                    "ask": 0.9,
                    "volume": 0,
                    "open_interest": 10,
                    "implied_volatility": 0.42,
                    "delta": -0.25,
                },
                {
                    "symbol": "GOOD",
                    "option_type": "PUT",
                    "strike": 90,
                    "bid": 1.1,
                    "ask": 1.2,
                    "volume": 600,
                    "open_interest": 1200,
                    "implied_volatility": 0.50,
                    "delta": -0.24,
                },
            ],
        },
    )
    assert score_response.status_code == 200
    assert score_response.json()["ranked_contracts"][0]["symbol"] == "GOOD"
    assert score_response.json()["safety"]["live_trading_enabled"] is False

    strategy_response = client.post(
        "/api/options/tools/strategy/rank",
        json={
            "market_view": "bullish",
            "spot": 100,
            "expiry_days": 45,
            "strikes": [85, 90, 95, 100, 105, 110, 115],
            "iv": 0.25,
        },
    )
    assert strategy_response.status_code == 200
    assert strategy_response.json()["rankings"]

    fear_response = client.post(
        "/api/options/tools/fear-score",
        json={
            "vix": 32,
            "iv_rank": 82,
            "rsi_14": 28,
            "options_volume_anomaly": 2.4,
            "put_call_ratio": 1.35,
            "consecutive_down_days": 4,
        },
    )
    assert fear_response.status_code == 200
    assert fear_response.json()["bull_put_spread_signal"] is True


def test_options_local_monitoring_endpoints_are_file_backed(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))

    add_response = client.post(
        "/api/options/tools/watchlist",
        json={"ticker": "aapl", "tags": ["core"]},
    )
    assert add_response.status_code == 200
    assert add_response.json()["watchlist"][0]["ticker"] == "AAPL"

    list_response = client.get("/api/options/tools/watchlist")
    assert list_response.status_code == 200
    assert list_response.json()["watchlist"][0]["tags"] == ["core"]

    alert_response = client.post(
        "/api/options/tools/alerts/evaluate",
        json={
            "context": {"ticker": "AAPL", "price": 100, "iv_rank": 82},
            "alerts": [
                {"id": "price", "ticker": "AAPL", "type": "price_below", "threshold": 95},
                {"id": "iv", "ticker": "AAPL", "type": "iv_rank_above", "threshold": 70},
            ],
        },
    )
    assert alert_response.status_code == 200
    assert [item["id"] for item in alert_response.json()["triggered_alerts"]] == ["iv"]

    health_response = client.post(
        "/api/options/tools/health-check",
        json={
            "today": "2026-05-23",
            "profiles": [
                {"ticker": "AAPL", "updated_at": "2026-05-01", "thesis": "long-term"},
                {"ticker": "MSFT", "updated_at": "2026-05-20", "thesis": ""},
            ],
        },
    )
    assert health_response.status_code == 200
    assert health_response.json()["stale_profiles"] == ["AAPL"]
