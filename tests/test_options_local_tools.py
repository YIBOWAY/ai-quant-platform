from __future__ import annotations

import pytest

from quant_system.options.local_research import (
    LocalWatchlistStore,
    _normalize_iv,
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
    black_scholes_price,
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


def test_black_scholes_price_matches_reference_call_and_put_values() -> None:
    call = black_scholes_price(
        spot=100.0,
        strike=100.0,
        expiry_days=365,
        iv=0.20,
        option_type="call",
        rate=0.05,
    )
    put = black_scholes_price(
        spot=100.0,
        strike=100.0,
        expiry_days=365,
        iv=0.20,
        option_type="put",
        rate=0.05,
    )

    assert call == pytest.approx(10.45058357, abs=1e-8)
    assert put == pytest.approx(5.57352602, abs=1e-8)
    assert call - put == pytest.approx(
        100.0 - 100.0 * 2.718281828459045 ** -0.05,
        abs=1e-8,
    )


def test_black_scholes_greeks_match_reference_values() -> None:
    call = calculate_greeks(
        spot=100.0,
        strike=100.0,
        expiry_days=365,
        iv=0.20,
        option_type="call",
        rate=0.05,
    )
    put = calculate_greeks(
        spot=100.0,
        strike=100.0,
        expiry_days=365,
        iv=0.20,
        option_type="put",
        rate=0.05,
    )

    assert call["delta"] == pytest.approx(0.636830651, abs=1e-9)
    assert put["delta"] == pytest.approx(-0.363169349, abs=1e-9)
    assert call["gamma"] == pytest.approx(0.018762018, abs=1e-9)
    assert put["gamma"] == pytest.approx(0.018762018, abs=1e-9)
    assert call["vega"] == pytest.approx(0.375240347, abs=1e-9)
    assert put["vega"] == pytest.approx(0.375240347, abs=1e-9)
    assert call["theta"] == pytest.approx(-0.017572678, abs=1e-9)
    assert put["theta"] == pytest.approx(-0.004542138, abs=1e-9)
    assert call["rho"] == pytest.approx(0.532324816, abs=2e-9)
    assert put["rho"] == pytest.approx(-0.418904609, abs=2e-9)


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


def test_implied_volatility_solver_rejects_no_arbitrage_violations() -> None:
    with pytest.raises(ValueError, match="below no-arbitrage lower bound"):
        implied_volatility(
            market_price=0.25,
            spot=100.0,
            strike=90.0,
            expiry_days=365,
            option_type="call",
            rate=0.05,
        )

    with pytest.raises(ValueError, match="above no-arbitrage upper bound"):
        implied_volatility(
            market_price=100.0,
            spot=100.0,
            strike=90.0,
            expiry_days=365,
            option_type="put",
            rate=0.05,
        )


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


@pytest.mark.parametrize("raw, expected", [
    (0.0, None),
    (0, None),
    (-0.1, None),
    (float("inf"), None),
    (float("-inf"), None),
    (float("nan"), None),
    (None, None),
    (0.5, 0.5),
    (1.25, 1.25),
])
def test_normalize_iv_rejects_unusable_values(raw, expected) -> None:
    assert _normalize_iv(raw) == expected


def test_rank_option_contracts_does_not_score_zero_iv_as_cheap_premium() -> None:
    result = rank_option_contracts(
        contracts=[
            {
                "symbol": "ZERO_IV",
                "option_type": "PUT",
                "strike": 95,
                "bid": 1.0,
                "ask": 1.1,
                "volume": 600,
                "open_interest": 1200,
                "implied_volatility": 0.0,
                "delta": -0.55,
            },
            {
                "symbol": "CHEAP_5",
                "option_type": "PUT",
                "strike": 95,
                "bid": 1.0,
                "ask": 1.1,
                "volume": 600,
                "open_interest": 1200,
                "implied_volatility": 0.05,
                "delta": -0.55,
            },
        ],
        spot=100,
        objective="buy_premium",
    )

    ranked = {item["symbol"]: item for item in result["ranked_contracts"]}
    # A zero IV must not be scored as the cheapest possible premium (100).
    assert result["ranked_contracts"][0]["symbol"] == "CHEAP_5"
    assert ranked["ZERO_IV"]["implied_volatility"] is None
    assert ranked["ZERO_IV"]["subscores"]["iv_value"] == pytest.approx(35.0)
    assert ranked["CHEAP_5"]["subscores"]["iv_value"] == pytest.approx(90.0)
    assert "invalid_iv" in ranked["ZERO_IV"]["warnings"]
    assert "missing_iv" not in ranked["ZERO_IV"]["warnings"]


def test_rank_option_contracts_flags_absent_iv_as_missing() -> None:
    result = rank_option_contracts(
        contracts=[
            {
                "symbol": "NO_IV",
                "option_type": "PUT",
                "strike": 95,
                "bid": 1.0,
                "ask": 1.1,
                "volume": 600,
                "open_interest": 1200,
                "delta": -0.55,
            },
        ],
        spot=100,
        objective="buy_premium",
    )

    warnings = result["ranked_contracts"][0]["warnings"]
    assert "missing_iv" in warnings
    assert "invalid_iv" not in warnings


def test_iv_rank_dashboard_treats_zero_current_iv_as_unavailable() -> None:
    result = compute_iv_rank_dashboard(
        ticker="AAPL",
        current_iv=0.0,
        history=[0.3, 0.4, 0.5],
    )

    assert result["current_iv"] is None
    assert result["iv_rank"] is None
    assert result["zone"] == "unknown"


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


def test_compute_market_sentiment_zero_inputs_is_insufficient() -> None:
    with pytest.raises(ValueError, match="insufficient_inputs"):
        compute_market_sentiment()


def test_compute_market_sentiment_all_none_is_insufficient() -> None:
    with pytest.raises(ValueError, match="insufficient_inputs"):
        compute_market_sentiment(
            vix=None,
            put_call_ratio=None,
            advance_decline_ratio=None,
            percent_above_200dma=None,
        )

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


def _hedge_contracts():
    return [
        {"symbol": "AAPL.P", "option_type": "PUT", "strike": 90, "bid": 1.0, "ask": 1.2},
        {"symbol": "AAPL.C", "option_type": "CALL", "strike": 110, "bid": 0.5, "ask": 0.7},
    ]


@pytest.mark.parametrize("shares", [0, -1, 1.5, True])
def test_hedge_rejects_nonpositive_or_fractional_share_counts(shares):
    with pytest.raises(ValueError, match="positive_integer_shares_required"):
        build_hedge_advisor(ticker="AAPL", shares=shares, cost_basis=100, spot=100,
                           purpose="protect", contracts=_hedge_contracts())


@pytest.mark.parametrize("shares, puts, calls", [(50, 1, 0), (100, 1, 1), (250, 3, 2), (300, 3, 3)])
def test_hedge_leg_counts_and_costs_match_actual_whole_contract_sizes(shares, puts, calls):
    result = build_hedge_advisor(ticker="AAPL", shares=shares, cost_basis=100, spot=100,
                                purpose="protect", contracts=_hedge_contracts())
    structures = {row["structure"]: row for row in result["structures"]}
    protection = structures["long_put"]
    assert protection["put_contracts"] == puts
    assert protection["estimated_debit_per_contract"] == pytest.approx(110)
    assert protection["estimated_debit"] == pytest.approx(110 * puts)
    if calls == 0:
        assert "collar" not in structures
    else:
        collar = structures["collar"]
        assert collar["put_contracts"] == puts
        assert collar["call_contracts"] == calls
        assert collar["call_covered_shares"] == calls * 100 <= shares
        assert collar["additional_put_contracts"] == puts - calls
        assert collar["estimated_net_debit_per_pair"] == pytest.approx(50)
        assert collar["estimated_net_debit"] == pytest.approx(110 * puts - 60 * calls)


def test_hedge_drops_nonstandard_contract_leg_and_reports_reason():
    contracts = _hedge_contracts()
    contracts[0]["contract_size"] = 50
    result = build_hedge_advisor(ticker="AAPL", shares=250, cost_basis=100, spot=100,
                                 purpose="protect", contracts=contracts)
    assert result["success"] is True
    assert result["structures"] == []
    assert [leg["role"] for leg in result["rejected_legs"]] == ["protective_put"]
    assert result["rejected_legs"][0]["field"] == "contract_size"
    assert result["rejected_legs"][0]["reason"] == "nonstandard_option_contract_unsupported"


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), 0, -5])
def test_hedge_drops_leg_with_unusable_contract_size_instead_of_failing(bad_value):
    contracts = [
        {"symbol": "AAPL.P", "option_type": "PUT", "strike": 90, "bid": 1.0, "ask": 1.2,
         "contract_size": bad_value},
        {"symbol": "AAPL.C", "option_type": "CALL", "strike": 110, "bid": 0.5, "ask": 0.7},
    ]
    result = build_hedge_advisor(ticker="AAPL", shares=250, cost_basis=100, spot=100,
                                 purpose="protect", contracts=contracts)
    assert result["success"] is True
    assert result["structures"] == []
    assert result["rejected_legs"][0]["role"] == "protective_put"
    assert result["rejected_legs"][0]["reason"] == "invalid_contract_size"


def test_hedge_keeps_valid_leg_when_the_other_leg_is_rejected():
    contracts = [
        {"symbol": "AAPL.P", "option_type": "PUT", "strike": 90, "bid": 1.0, "ask": 1.2},
        {"symbol": "AAPL.C", "option_type": "CALL", "strike": 110, "bid": 0.5, "ask": 0.7,
         "multiplier": 50},
    ]
    result = build_hedge_advisor(ticker="AAPL", shares=250, cost_basis=100, spot=100,
                                 purpose="protect", contracts=contracts)
    assert [row["structure"] for row in result["structures"]] == ["long_put"]
    assert result["rejected_legs"][0]["role"] == "covered_call"
    assert result["rejected_legs"][0]["field"] == "multiplier"
    assert result["rejected_legs"][0]["reason"] == "nonstandard_option_contract_unsupported"


def test_hedge_treats_null_contract_size_as_standard_contract():
    contracts = [
        {"symbol": "AAPL.P", "option_type": "PUT", "strike": 90, "bid": 1.0, "ask": 1.2,
         "contract_size": None},
        {"symbol": "AAPL.C", "option_type": "CALL", "strike": 110, "bid": 0.5, "ask": 0.7,
         "contract_size": None},
    ]
    result = build_hedge_advisor(ticker="AAPL", shares=250, cost_basis=100, spot=100,
                                 purpose="protect", contracts=contracts)
    assert {row["structure"] for row in result["structures"]} == {"long_put", "collar"}
    assert result["rejected_legs"] == []


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
