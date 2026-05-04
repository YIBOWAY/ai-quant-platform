from __future__ import annotations

import pandas as pd

from quant_system.options.buy_side_strategy import (
    BuySideStrategyRequest,
    generate_buy_side_candidates,
)
from quant_system.options.market_regime import VixRegimeSnapshot, buyer_regime_penalty


def _chain() -> pd.DataFrame:
    rows = []
    for expiry, dte in [("2026-06-19", 30), ("2027-06-18", 394)]:
        for strike, delta, mid, theta, vega, oi in [
            (95.0, 0.72, 8.5, -0.05, 0.18, 900),
            (100.0, 0.56, 5.25, -0.08, 0.20, 800),
            (105.0, 0.35, 2.8, -0.06, 0.16, 600),
            (110.0, 0.24, 1.4, -0.04, 0.12, 500),
        ]:
            rows.append(
                {
                    "symbol": f"US.AAPL{expiry.replace('-', '')}C{int(strike * 1000):06d}",
                    "option_type": "CALL",
                    "expiry": expiry,
                    "strike": strike,
                    "bid": mid - 0.1,
                    "ask": mid + 0.1,
                    "implied_volatility": 0.24,
                    "delta": delta,
                    "gamma": 0.03,
                    "theta": theta,
                    "vega": vega,
                    "open_interest": oi,
                    "volume": 100,
                    "update_time": "2026-05-20T20:00:00Z",
                    "option_expiry_date_distance": dte,
                }
            )
    return pd.DataFrame(rows)


def _request(**overrides) -> BuySideStrategyRequest:
    params = {
        "ticker": "AAPL",
        "spot_price": 100.0,
        "view_type": "short_term_conservative_bullish",
        "target_price": 112.0,
        "target_date": "2026-08-21",
        "max_loss_budget": 600.0,
        "risk_preference": "balanced",
        "allow_capped_upside": True,
        "avoid_high_iv": False,
        "volatility_view": "auto",
        "event_risk": "none",
        "as_of_date": "2026-05-20",
    }
    params.update(overrides)
    return BuySideStrategyRequest(**params)


def test_long_call_candidate_creation() -> None:
    result = generate_buy_side_candidates(_chain(), _request(), max_candidates=10)

    long_calls = [item for item in result.candidates if item.strategy_type == "long_call"]

    assert long_calls
    candidate = long_calls[0]
    assert len(candidate.legs) == 1
    assert candidate.max_loss is not None and candidate.max_loss <= 600
    assert candidate.breakeven is not None
    assert candidate.score.total_score > 0


def test_bull_call_spread_candidate_creation() -> None:
    result = generate_buy_side_candidates(_chain(), _request(), max_candidates=20)

    spreads = [item for item in result.candidates if item.strategy_type == "bull_call_spread"]

    assert spreads
    spread = spreads[0]
    assert len(spread.legs) == 2
    assert spread.net_debit is not None and spread.net_debit > 0
    assert spread.max_gain is not None and spread.max_gain > 0
    assert spread.max_loss is not None and spread.max_loss > 0
    assert "CAPPED_UPSIDE" in spread.warnings


def test_leaps_filtering_for_long_term_view() -> None:
    result = generate_buy_side_candidates(
        _chain(),
        _request(view_type="long_term_conservative_bullish", target_date="2027-12-17"),
        max_candidates=20,
    )

    assert {item.strategy_type for item in result.candidates} <= {
        "leaps_call",
        "leaps_call_spread",
    }
    assert all(item.legs[0].dte >= 360 for item in result.candidates)


def test_invalid_spread_is_filtered() -> None:
    chain = _chain()
    chain.loc[chain["strike"] == 105.0, ["bid", "ask"]] = [7.0, 7.2]

    result = generate_buy_side_candidates(chain, _request(), max_candidates=20)

    for item in result.candidates:
        if item.strategy_type == "bull_call_spread":
            assert item.net_debit is not None and item.net_debit > 0
            assert item.max_gain is not None and item.max_gain > 0


def test_prefer_low_iv_rewards_spreads_over_naked_calls_when_iv_rank_high() -> None:
    result = generate_buy_side_candidates(
        _chain(),
        _request(volatility_view="prefer_low_iv", avoid_high_iv=True, iv_rank=82.0),
        max_candidates=5,
    )

    assert result.candidates
    assert result.candidates[0].strategy_type == "bull_call_spread"


def test_missing_data_handling() -> None:
    chain = _chain()
    chain.loc[1, ["delta", "gamma", "theta", "vega"]] = [None, None, None, None]

    result = generate_buy_side_candidates(chain, _request(), max_candidates=20)

    assert result.candidates
    assert any("MISSING_DATA" in item.warnings for item in result.candidates)


def test_view_type_specific_filtering_for_speculative_dte() -> None:
    result = generate_buy_side_candidates(
        _chain(),
        _request(view_type="short_term_speculative_bullish"),
        max_candidates=20,
    )

    assert result.candidates
    assert all(item.legs[0].dte <= 45 for item in result.candidates)


def test_market_regime_penalty_behavior() -> None:
    panic = VixRegimeSnapshot(
        volatility_regime="Panic",
        w_vix=0.35,
        vix_density=0.9,
        term_ratio=1.1,
        vix_mean=40,
        vix_threshold=25,
    )

    result = generate_buy_side_candidates(
        _chain(),
        _request(),
        market_regime=panic,
        max_candidates=20,
    )

    assert buyer_regime_penalty("long_call", "Panic") == -40.0
    assert result.candidates
    assert all(item.market_regime == "Panic" for item in result.candidates)
    assert any("MARKET_REGIME_PANIC" in item.warnings for item in result.candidates)
