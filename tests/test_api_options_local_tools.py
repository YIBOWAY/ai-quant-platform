from __future__ import annotations

import pandas as pd
import pytest
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
                    "implied_volatility": 25 + abs(strike - 100.0) * 0.2,
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
                    "implied_volatility": 27 + abs(strike - 100.0) * 0.3,
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


def test_hedge_advisor_preserves_holding_situation_in_http_response(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.post("/api/options/tools/hedge-advisor", json={
        "ticker": "AAPL", "shares": 100, "cost_basis": 80, "spot": 100,
        "contracts": [],
    })
    assert response.status_code == 200
    assert response.json()["situation"] == "gain_protection"
    assert response.json()["rejected_legs"] == []


def test_hedge_advisor_accepts_null_contract_size_instead_of_failing(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.post("/api/options/tools/hedge-advisor", json={
        "ticker": "AAPL", "shares": 250, "cost_basis": 100, "spot": 100,
        "contracts": [
            {"option_type": "PUT", "strike": 90, "bid": 1, "ask": 1.2, "contract_size": None},
            {"option_type": "CALL", "strike": 110, "bid": 0.5, "ask": 0.7, "contract_size": None},
        ],
    })
    assert response.status_code == 200
    payload = response.json()
    assert {row["structure"] for row in payload["structures"]} == {"long_put", "collar"}
    assert payload["rejected_legs"] == []


@pytest.mark.parametrize("bad_value", ["nan", "inf", 0, 50])
def test_hedge_advisor_reports_rejected_legs_without_http_400(tmp_path, bad_value) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.post("/api/options/tools/hedge-advisor", json={
        "ticker": "AAPL", "shares": 250, "cost_basis": 100, "spot": 100,
        "contracts": [
            {"option_type": "PUT", "strike": 90, "bid": 1, "ask": 1.2,
             "contract_size": bad_value},
            {"option_type": "CALL", "strike": 110, "bid": 0.5, "ask": 0.7},
        ],
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["structures"] == []
    assert payload["rejected_legs"][0]["role"] == "protective_put"


def test_score_contracts_does_not_treat_zero_iv_as_cheap(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.post("/api/options/tools/score-contracts", json={
        "spot": 100,
        "objective": "buy_premium",
        "contracts": [
            {"symbol": "ZERO_IV", "option_type": "PUT", "strike": 95, "bid": 1.0, "ask": 1.1,
             "volume": 600, "open_interest": 1200, "implied_volatility": 0, "delta": -0.55},
            {"symbol": "CHEAP_5", "option_type": "PUT", "strike": 95, "bid": 1.0, "ask": 1.1,
             "volume": 600, "open_interest": 1200, "implied_volatility": 0.05, "delta": -0.55},
        ],
    })
    assert response.status_code == 200
    ranked = {row["symbol"]: row for row in response.json()["ranked_contracts"]}
    assert response.json()["ranked_contracts"][0]["symbol"] == "CHEAP_5"
    assert ranked["ZERO_IV"]["implied_volatility"] is None
    assert ranked["ZERO_IV"]["subscores"]["iv_value"] == 35.0
    assert "invalid_iv" in ranked["ZERO_IV"]["warnings"]


@pytest.mark.parametrize("shares", [0, -1, 1.5, True, "250"])
def test_hedge_api_rejects_invalid_share_counts_without_truncation(tmp_path, shares):
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.post("/api/options/tools/hedge-advisor", json={
        "ticker": "AAPL", "shares": shares, "cost_basis": 80, "spot": 100,
        "contracts": [],
    })
    assert response.status_code == 400
    assert "positive_integer_shares_required" in response.json()["detail"]["message"]


def test_hedge_http_preserves_per_leg_sizing_and_total_cost(tmp_path):
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    response = client.post("/api/options/tools/hedge-advisor", json={
        "ticker": "AAPL", "shares": 250, "cost_basis": 80, "spot": 100,
        "contracts": [
            {"option_type": "PUT", "strike": 90, "bid": 1, "ask": 1.2, "contract_size": 100},
            {"option_type": "CALL", "strike": 110, "bid": 0.5, "ask": 0.7, "contract_size": 100},
        ],
    })
    assert response.status_code == 200
    collar = next(row for row in response.json()["structures"] if row["structure"] == "collar")
    assert (collar["put_contracts"], collar["call_contracts"]) == (3, 2)
    assert collar["excess_put_coverage_shares"] == 50
    assert collar["estimated_net_debit"] == 210


def test_snapshot_and_chain_keep_their_declared_iv_contracts(
    tmp_path, monkeypatch,
) -> None:
    _patch_provider(monkeypatch)
    def quotes(self, underlying, *, expiration, option_type="ALL"):
        rows = _chain().loc[_chain()["expiry"] == expiration].copy()
        # Provider frames use the canonical ratio (Futu percent / 100 at the
        # provider boundary); the surfaces re-declare their own contract.
        rows["implied_volatility"] = 0.005 if expiration == "2026-07-17" else 2.14227
        return rows
    monkeypatch.setattr(
        "quant_system.api.routes.options.FutuMarketDataProvider.fetch_option_quotes", quotes,
    )
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    selected = client.get("/api/options/snapshot/AAPL?expiration=2026-07-17").json()
    assert selected["iv_expiry"] == "2026-07-17"
    assert selected["atm_iv"] == pytest.approx(0.005)  # ratio, the snapshot contract
    assert selected["iv_rank"] is None  # Equity HV is not historical option IV.
    chain = client.get("/api/options/chain?ticker=AAPL&expiration=2026-06-19").json()
    assert chain["implied_volatility_unit"] == "percent"
    assert chain["contracts"][0]["implied_volatility"] == pytest.approx(214.227)
    invalid = client.get("/api/options/snapshot/AAPL?expiration=1900-01-01")
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["message"] == "requested_expiration_unavailable"


def test_partial_signal_inputs_do_not_claim_full_market_judgments(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    fear = client.post("/api/options/tools/fear-score", json={"iv_rank": 0}).json()
    assert fear["fear_score"] is None
    assert fear["tier"] == "insufficient_inputs"
    assert fear["available_inputs"] == 1
    assert fear["total_inputs"] == 6
    assert fear["bull_put_spread_signal"] is False
    assert fear["partial_score"] == 0
    sentiment = client.post("/api/options/tools/market-sentiment", json={"vix": 15}).json()
    assert sentiment["sentiment_score"] is None
    assert sentiment["regime"] == "insufficient_inputs"
    assert sentiment["available_inputs"] == 1
    assert sentiment["total_inputs"] == 4


def test_health_check_reads_saved_profiles_and_cannot_be_filled_by_request(tmp_path) -> None:
    import json
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    forged = {"ticker": "AAPL", "profiles": [
        {"ticker": "AAPL", "updated_at": "2099-01-01", "thesis": "fine"},
    ]}
    empty = client.post("/api/options/tools/health-check", json=forged).json()
    assert empty["health_score"] is None
    assert empty["status"] == "no_saved_profile"
    path = tmp_path / "options_tools" / "watchlist.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"watchlist": [
        {"ticker": "AAPL", "thesis": "saved", "updated_at": "2020-01-01"},
    ]}))
    saved = client.post("/api/options/tools/health-check", json=forged).json()
    assert saved["profile_count"] == 1
    assert saved["stale_profiles"] == ["AAPL"]
    assert saved["health_score"] == 50


def test_health_check_missing_saved_dates_are_unknown_not_healthy(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    client.post("/api/options/tools/watchlist", json={"ticker": "AAPL"})
    result = client.post("/api/options/tools/health-check", json={"ticker": "AAPL"}).json()
    assert result["health_score"] is None
    assert result["missing_updated_at"] == ["AAPL"]
    assert result["missing_thesis"] == ["AAPL"]


def test_earnings_without_paired_event_history_has_no_forecast(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    result = client.post(
        "/api/options/tools/earnings-crush", json={"ticker": "AAPL", "current_iv": 0.4},
    ).json()
    assert result["status"] == "unavailable"
    assert result["reason"] == "event_aligned_iv_history_missing"
    assert result["sample_count"] == 0
    assert result["expected_post_event_iv"] is None


def test_tools_use_explicit_ratio_iv_even_above_five(tmp_path) -> None:
    client = TestClient(create_app(settings=Settings(), output_dir=tmp_path))
    result = client.post("/api/options/tools/earnings-crush", json={
        "ticker": "AAPL", "current_iv": 6,
        "historical_pre_post_iv": [{"pre_iv": 6, "post_iv": 3}],
    }).json()
    assert result["average_crush_pct"] == 50
    assert result["expected_post_event_iv"] == 3


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
        json={"ticker": "AAPL"},
    )
    assert health_response.status_code == 200
    assert health_response.json()["profile_count"] == 1
    assert health_response.json()["missing_updated_at"] == ["AAPL"]
    assert health_response.json()["health_score"] is None


def test_market_sentiment_empty_payload_is_insufficient(tmp_path) -> None:
    from quant_system.config.settings import OptionsRadarSettings

    client = TestClient(
        create_app(
            settings=Settings(
                options_radar=OptionsRadarSettings(
                    vix_history_path=tmp_path / "missing_vix.csv",
                )
            ),
            output_dir=tmp_path,
        )
    )
    response = client.post("/api/options/tools/market-sentiment", json={})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "insufficient_inputs"
