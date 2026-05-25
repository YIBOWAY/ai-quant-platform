from __future__ import annotations

import pytest

from quant_system.options.local_research import (
    LocalWatchlistStore,
    build_bull_put_spread_signal,
    build_hedge_advisor,
    compute_fear_score,
    compute_iv_rank_dashboard,
    compute_market_sentiment,
    detect_unusual_options_activity,
    evaluate_local_alerts,
    rank_option_contracts,
    rank_strategy_templates,
    research_health_check,
)
from quant_system.options.local_tools import (
    build_strategy_from_template,
    calculate_greeks,
    implied_volatility,
    simulate_option_position,
)


def test_black_scholes_greeks_are_consistent_for_atm_call() -> None:
    result = calculate_greeks(
        spot=100.0,
        strike=100.0,
        expiry_days=30,
        iv=0.25,
        option_type="call",
    )

    assert 0.50 < result["delta"] < 0.55
    assert result["gamma"] > 0
    assert result["vega"] > 0
    assert result["theta"] < 0


def test_implied_volatility_solver_recovers_market_iv() -> None:
    priced = calculate_greeks(
        spot=120.0,
        strike=125.0,
        expiry_days=45,
        iv=0.32,
        option_type="call",
    )

    solved = implied_volatility(
        market_price=priced["price"],
        spot=120.0,
        strike=125.0,
        expiry_days=45,
        option_type="call",
    )

    assert solved == pytest.approx(0.32, abs=0.001)


def test_simulate_option_position_returns_vertical_spread_bounds() -> None:
    result = simulate_option_position(
        symbol="AAPL",
        spot=100.0,
        legs=[
            {
                "action": "buy",
                "option_type": "call",
                "strike": 100.0,
                "expiry_days": 30,
                "iv": 0.25,
                "entry_price": 5.0,
            },
            {
                "action": "sell",
                "option_type": "call",
                "strike": 110.0,
                "expiry_days": 30,
                "iv": 0.25,
                "entry_price": 2.0,
            },
        ],
    )

    assert result["max_loss"] == pytest.approx(300.0)
    assert result["max_profit"] == pytest.approx(700.0)
    assert result["breakevens"] == pytest.approx([103.0])
    assert result["pnl_at_expiry"]["price_axis"]
    assert result["scenarios"]["price_up_10pct"]["pnl"] == pytest.approx(700.0)


def test_simulate_option_position_reports_unbounded_and_cash_secured_bounds() -> None:
    long_call = simulate_option_position(
        symbol="AAPL",
        spot=100.0,
        legs=[
            {
                "action": "buy",
                "option_type": "call",
                "strike": 100.0,
                "expiry_days": 30,
                "entry_price": 5.0,
                "quantity": 1,
            }
        ],
    )

    assert long_call["max_profit"] is None
    assert long_call["max_loss"] == pytest.approx(500.0)

    short_put = simulate_option_position(
        symbol="AAPL",
        spot=100.0,
        legs=[
            {
                "action": "sell",
                "option_type": "put",
                "strike": 90.0,
                "expiry_days": 30,
                "entry_price": 2.0,
                "quantity": 1,
            }
        ],
    )

    assert short_put["max_profit"] == pytest.approx(200.0)
    assert short_put["max_loss"] == pytest.approx(8800.0)


def test_build_strategy_from_template_uses_supplied_strikes() -> None:
    result = build_strategy_from_template(
        template_id="bull_call_spread",
        spot=100.0,
        expiry_days=30,
        strikes=[95.0, 100.0, 105.0, 110.0],
        iv=0.25,
    )

    assert result["strategy"] == "Bull Call Spread"
    assert [leg["action"] for leg in result["legs"]] == ["buy", "sell"]
    assert result["legs"][0]["strike"] < result["legs"][1]["strike"]
    assert result["max_loss"] is not None
    assert result["max_profit"] is not None


def test_rank_option_contracts_prefers_liquid_contract_for_sell_premium() -> None:
    result = rank_option_contracts(
        contracts=[
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
        spot=100,
        objective="sell_premium",
    )

    assert result["ranked_contracts"][0]["symbol"] == "GOOD"
    assert result["ranked_contracts"][0]["rating"] == "Strong"
    assert result["ranked_contracts"][1]["rating"] == "Avoid"
    assert "wide_spread" in result["ranked_contracts"][1]["warnings"]


def test_rank_strategy_templates_orders_bullish_structures() -> None:
    result = rank_strategy_templates(
        market_view="bullish",
        spot=100,
        expiry_days=45,
        strikes=[85, 90, 95, 100, 105, 110, 115],
        iv=0.25,
    )

    assert result["rankings"]
    scores = [item["score"] for item in result["rankings"]]
    assert scores == sorted(scores, reverse=True)
    assert {item["template_id"] for item in result["rankings"]}.issuperset(
        {"long_call", "bull_call_spread", "bull_put_spread"}
    )


def test_bull_put_spread_signal_requires_fear_and_selects_vertical_puts() -> None:
    contracts = [
        {
            "symbol": "SELL90",
            "option_type": "PUT",
            "strike": 90,
            "bid": 1.2,
            "ask": 1.3,
            "volume": 500,
            "open_interest": 1000,
            "implied_volatility": 0.46,
            "delta": -0.25,
        },
        {
            "symbol": "BUY85",
            "option_type": "PUT",
            "strike": 85,
            "bid": 0.45,
            "ask": 0.55,
            "volume": 300,
            "open_interest": 800,
            "implied_volatility": 0.48,
            "delta": -0.12,
        },
    ]

    result = build_bull_put_spread_signal(
        contracts=contracts,
        spot=100,
        fear_score=72,
    )

    assert result["enter_signal"] is True
    assert result["selected_spread"]["sell_leg"]["symbol"] == "SELL90"
    assert result["selected_spread"]["buy_leg"]["symbol"] == "BUY85"
    assert result["selected_spread"]["max_loss"] == pytest.approx(425.0)


def test_research_dashboards_compute_fear_iv_sentiment_and_activity() -> None:
    fear = compute_fear_score(
        vix=32,
        iv_rank=82,
        rsi_14=28,
        options_volume_anomaly=2.4,
        put_call_ratio=1.35,
        consecutive_down_days=4,
    )
    assert fear["fear_score"] >= 60
    assert fear["bull_put_spread_signal"] is True

    iv_rank = compute_iv_rank_dashboard(
        ticker="AAPL",
        current_iv=0.45,
        history=[0.20, 0.24, 0.30, 0.36, 0.50],
    )
    assert iv_rank["iv_rank"] == pytest.approx(83.3333)
    assert iv_rank["zone"] == "high"

    sentiment = compute_market_sentiment(
        vix=24,
        put_call_ratio=1.2,
        advance_decline_ratio=0.7,
        percent_above_200dma=38,
    )
    assert sentiment["regime"] in {"neutral", "risk_off"}

    activity = detect_unusual_options_activity(
        [
            {"symbol": "QUIET", "volume": 20, "open_interest": 400, "bid": 0.4, "ask": 0.5},
            {"symbol": "LOUD", "volume": 1200, "open_interest": 300, "bid": 1.0, "ask": 1.2},
        ]
    )
    assert activity["events"][0]["symbol"] == "LOUD"
    assert activity["events"][0]["volume_oi_ratio"] == pytest.approx(4.0)


def test_hedge_advisor_returns_research_only_structures() -> None:
    result = build_hedge_advisor(
        ticker="AAPL",
        shares=100,
        cost_basis=80,
        spot=120,
        purpose="protect_gain",
        contracts=[
            {"symbol": "PUT108", "option_type": "PUT", "strike": 108, "bid": 2.0, "ask": 2.2},
            {"symbol": "CALL132", "option_type": "CALL", "strike": 132, "bid": 1.4, "ask": 1.6},
        ],
    )

    assert result["situation"] == "gain_protection"
    assert {item["structure"] for item in result["structures"]} == {"long_put", "collar"}
    assert all("order" not in item for item in result["structures"])


def test_watchlist_alerts_and_health_check_are_file_backed(tmp_path) -> None:
    store = LocalWatchlistStore(tmp_path / "watchlist.json")
    store.add("aapl", tags=["core"])
    store.add("MSFT")

    assert [item["ticker"] for item in store.list()] == ["AAPL", "MSFT"]

    triggered = evaluate_local_alerts(
        alerts=[
            {"id": "price", "ticker": "AAPL", "type": "price_below", "threshold": 95},
            {"id": "iv", "ticker": "AAPL", "type": "iv_rank_above", "threshold": 70},
        ],
        context={"ticker": "AAPL", "price": 100, "iv_rank": 82},
    )
    assert [item["id"] for item in triggered["triggered_alerts"]] == ["iv"]

    health = research_health_check(
        profiles=[
            {"ticker": "AAPL", "updated_at": "2026-05-01", "thesis": "quality compounder"},
            {"ticker": "MSFT", "updated_at": "2026-05-20", "thesis": ""},
        ],
        today="2026-05-23",
        stale_after_days=14,
    )
    assert health["stale_profiles"] == ["AAPL"]
    assert health["missing_thesis"] == ["MSFT"]
