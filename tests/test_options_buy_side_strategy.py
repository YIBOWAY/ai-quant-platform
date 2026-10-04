from __future__ import annotations

import pandas as pd
import pytest

from quant_system.options.buy_side_strategy import (
    BuySideStrategyRequest,
    generate_buy_side_candidates,
    resolve_atm_straddle_mids,
)
from quant_system.options.market_regime import VixRegimeSnapshot, buyer_regime_penalty


def _chain() -> pd.DataFrame:
    rows = []
    for expiry, dte in [("2026-06-19", 30), ("2027-06-18", 394)]:
        for strike, delta, mid, theta, vega, oi in [
            (95.0, 0.80, 8.5, -0.05, 0.18, 900),
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
        rows.append(
            {
                "symbol": f"US.AAPL{expiry.replace('-', '')}P100000",
                "option_type": "PUT",
                "expiry": expiry,
                "strike": 100.0,
                "bid": 4.6,
                "ask": 4.9,
                "implied_volatility": 0.25,
                "delta": -0.45,
                "gamma": 0.03,
                "theta": -0.08,
                "vega": 0.20,
                "open_interest": 900,
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
        "iv_rank": 35.0,
        "historical_volatility": 0.20,
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


def test_same_expiry_atm_call_and_put_mids_drive_expected_move() -> None:
    chain = _chain()

    result = generate_buy_side_candidates(chain, _request(), max_candidates=20)

    short_term = [
        item
        for item in result.candidates
        if item.strategy_type in {"long_call", "bull_call_spread"}
        and item.legs[0].expiry == "2026-06-19"
    ]
    assert short_term
    assert all(item.expected_move_pct == 0.10 for item in short_term)


def test_missing_same_expiry_atm_call_or_put_mid_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing same-expiry ATM call/put midpoint"):
        generate_buy_side_candidates(
            _chain().loc[lambda frame: frame["option_type"] == "CALL"],
            _request(),
            max_candidates=20,
        )


@pytest.mark.parametrize("column", ["option_type", "expiry", "strike", "bid", "ask"])
def test_atm_mid_required_columns_fail_closed_as_value_error(column: str) -> None:
    with pytest.raises(ValueError, match=column):
        resolve_atm_straddle_mids(
            _chain().drop(columns=[column]),
            spot_price=100.0,
        )


def test_missing_atm_pair_for_a_candidate_expiry_fails_closed() -> None:
    chain = _chain().loc[
        lambda frame: ~((frame["option_type"] == "PUT") & (frame["expiry"] == "2027-06-18"))
    ]

    with pytest.raises(ValueError, match="2027-06-18"):
        generate_buy_side_candidates(
            chain,
            _request(
                view_type="long_term_aggressive_bullish",
                target_date="2027-12-17",
                max_loss_budget=2000.0,
            ),
            max_candidates=20,
        )


@pytest.mark.parametrize(
    ("iv_rank", "historical_volatility", "missing_name"),
    [
        (None, 0.20, "iv_rank"),
        (35.0, None, "historical_volatility"),
    ],
)
def test_missing_iv_rank_or_historical_volatility_fails_closed(
    iv_rank: float | None,
    historical_volatility: float | None,
    missing_name: str,
) -> None:
    with pytest.raises(ValueError, match=missing_name):
        generate_buy_side_candidates(
            _chain(),
            _request(
                iv_rank=iv_rank,
                historical_volatility=historical_volatility,
            ),
            max_candidates=20,
        )


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


def test_buy_side_ignores_provider_dte_and_filters_from_server_session() -> None:
    chain = _chain().loc[lambda frame: frame["expiry"] == "2027-06-18"].copy()
    chain["option_expiry_date_distance"] = 30

    result = generate_buy_side_candidates(
        chain,
        _request(
            view_type="short_term_conservative_bullish",
            target_date="2026-08-21",
            as_of_date="2026-05-20",
        ),
        max_candidates=20,
    )

    assert result.candidates == []


def test_leaps_long_leg_delta_range_is_inclusive_075_to_085() -> None:
    base = _chain()
    chain = base.loc[base["option_expiry_date_distance"] == 394].copy()
    chain.loc[chain["strike"] == 95.0, "delta"] = 0.74
    chain.loc[chain["strike"] == 100.0, "delta"] = 0.75
    chain.loc[chain["strike"] == 105.0, "delta"] = 0.85
    chain.loc[chain["strike"] == 110.0, "delta"] = 0.86

    result = generate_buy_side_candidates(
        chain,
        _request(
            view_type="long_term_aggressive_bullish",
            target_date="2027-12-17",
            max_loss_budget=2000.0,
            strategy_types=("leaps_call",),
        ),
        max_candidates=20,
    )

    assert [item.legs[0].delta for item in result.candidates] == [0.75, 0.85]


def test_leaps_long_leg_missing_delta_is_excluded() -> None:
    base = _chain()
    chain = base.loc[
        (base["option_expiry_date_distance"] == 394) & (base["strike"] == 100.0)
    ].copy()
    chain.loc[chain["option_type"] == "CALL", "delta"] = None

    result = generate_buy_side_candidates(
        chain,
        _request(
            view_type="long_term_aggressive_bullish",
            target_date="2027-12-17",
            max_loss_budget=2000.0,
            strategy_types=("leaps_call",),
        ),
        max_candidates=20,
    )

    assert result.candidates == []


def test_leaps_call_spread_uses_the_same_high_delta_long_leg_window() -> None:
    base = _chain()
    chain = base.loc[
        (base["option_expiry_date_distance"] == 394) & (base["strike"].isin([100.0, 110.0]))
    ].copy()
    chain.loc[chain["strike"] == 100.0, "delta"] = 0.75
    chain.loc[chain["strike"] == 110.0, "delta"] = 0.30

    result = generate_buy_side_candidates(
        chain,
        _request(
            view_type="long_term_conservative_bullish",
            target_date="2027-12-17",
            max_loss_budget=1000.0,
            strategy_types=("leaps_call_spread",),
        ),
        max_candidates=20,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].legs[0].delta == 0.75


def test_invalid_spread_is_filtered() -> None:
    chain = _chain()
    chain.loc[chain["strike"] == 105.0, ["bid", "ask"]] = [7.0, 7.2]

    result = generate_buy_side_candidates(chain, _request(), max_candidates=20)

    for item in result.candidates:
        if item.strategy_type == "bull_call_spread":
            assert item.net_debit is not None and item.net_debit > 0
            assert item.max_gain is not None and item.max_gain > 0


def test_spread_debit_above_half_the_width_is_rejected() -> None:
    base = _chain()
    chain = base.loc[
        (base["option_expiry_date_distance"] == 30) & (base["strike"].isin([100.0, 110.0]))
    ].copy()
    chain.loc[chain["strike"] == 100.0, ["bid", "ask"]] = [5.0, 5.2]
    chain.loc[chain["strike"] == 110.0, ["bid", "ask"]] = [0.08, 0.10]

    result = generate_buy_side_candidates(chain, _request(), max_candidates=20)

    assert not [item for item in result.candidates if item.strategy_type == "bull_call_spread"]


def test_spread_debit_at_exactly_half_the_width_is_accepted() -> None:
    base = _chain()
    chain = base.loc[
        (base["option_expiry_date_distance"] == 30) & (base["strike"].isin([100.0, 110.0]))
    ].copy()
    chain.loc[chain["strike"] == 100.0, ["bid", "ask"]] = [5.0, 5.2]
    chain.loc[chain["strike"] == 110.0, ["bid", "ask"]] = [0.09, 0.11]

    result = generate_buy_side_candidates(chain, _request(), max_candidates=20)

    spreads = [item for item in result.candidates if item.strategy_type == "bull_call_spread"]
    assert len(spreads) == 1
    assert spreads[0].net_debit == 5.0
    assert spreads[0].max_gain == spreads[0].max_loss


def test_prefer_low_iv_rewards_spreads_over_naked_calls_when_iv_rank_high() -> None:
    result = generate_buy_side_candidates(
        _chain(),
        _request(volatility_view="prefer_low_iv", avoid_high_iv=True, iv_rank=82.0),
        max_candidates=5,
    )

    assert result.candidates
    assert result.candidates[0].strategy_type == "bull_call_spread"


def test_spread_volatility_bonus_is_applied_exactly_once() -> None:
    baseline = generate_buy_side_candidates(
        _chain(),
        _request(volatility_view="auto", avoid_high_iv=False),
        max_candidates=20,
    )
    preferred = generate_buy_side_candidates(
        _chain(),
        _request(volatility_view="prefer_low_iv", avoid_high_iv=False),
        max_candidates=20,
    )

    def target_score(result) -> float:
        return next(
            item.score.total_score
            for item in result.candidates
            if item.strategy_type == "bull_call_spread"
            and [leg.strike for leg in item.legs] == [100.0, 110.0]
        )

    assert target_score(preferred) - target_score(baseline) == pytest.approx(8.0)


def test_candidate_score_preserves_theta_safety_and_greek_efficiency() -> None:
    result = generate_buy_side_candidates(_chain(), _request(), max_candidates=20)

    assert result.candidates
    score = result.candidates[0].score
    assert score.theta_safety_score is not None
    assert score.greek_efficiency_score is not None
    assert "theta_safety_score" in score.model_dump()
    assert "greek_efficiency_score" in score.model_dump()


def test_missing_required_greeks_never_enter_ranked_candidate() -> None:
    chain = _chain()
    invalid_symbol = str(chain.loc[1, "symbol"])
    chain.loc[1, ["delta", "gamma", "theta", "vega"]] = [None, None, None, None]

    result = generate_buy_side_candidates(chain, _request(), max_candidates=20)

    assert result.candidates == []
    assert all(
        invalid_symbol not in {leg.symbol for leg in item.legs} for item in result.candidates
    )


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
