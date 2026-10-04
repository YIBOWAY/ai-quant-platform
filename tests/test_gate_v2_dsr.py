"""DSR v2: same math, new inputs; small-family conservative path; monotonicity.

Every expectation is recomputed independently (closed form via ``NormalDist``),
never copied from the implementation.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pandas as pd
import pytest

from quant_system.research import gate_v2 as g
from quant_system.research.active_metrics import active_metrics
from quant_system.research.trials import deflated_sharpe_ratio, performance_from_daily_returns
from tests.gate_v2_fixtures import active_series_from, balanced_returns, curve_rows, noise_returns


def _family(sharpes, *, n_periods: int = 200) -> dict:
    return {
        "members": [
            {"trial_id": f"t{index}", "n_periods": n_periods, "recomputed_sharpe": float(value)}
            for index, value in enumerate(sharpes)
        ],
        "family_digest": "fixture",
    }


def test_small_family_path_is_probabilistic_sharpe_against_zero() -> None:
    returns = balanced_returns(periods=200, mean=0.001, spread=0.01)
    active = active_series_from(returns)
    result = g.evaluate_dsr_v2(
        active=active, family=_family([]), dsr_min=g.DSR_V2_MIN, config=g.GATE_V2_CONFIG
    )
    perf = performance_from_daily_returns(returns)
    denominator = (
        1.0
        - perf["skewness"] * perf["sharpe_period"]
        + (perf["kurtosis"] - 1) / 4 * perf["sharpe_period"] ** 2
    )
    z = perf["sharpe_period"] * math.sqrt(perf["n_periods"] - 1) / math.sqrt(denominator)
    assert abs(result["value"] - NormalDist().cdf(z)) < 1e-12
    assert result["path"] == "small_family_fixed"
    assert result["n_trials"] == 0
    assert result["dsr_min_used"] == g.DSR_V2_SMALL_FAMILY_PASS_MIN


def test_the_sealed_moment_identity_from_the_design_holds_on_the_shared_math() -> None:
    # Bailey-Lopez de Prado PSR at SR*=0 with SR=0.10, n=200, skew=0, kurt=3.
    result = deflated_sharpe_ratio(
        sharpe=0.10, n_periods=200, skewness=0.0, kurtosis=3.0, trial_sharpes=[]
    )
    z = 0.10 * math.sqrt(199) / math.sqrt(1.0 + 0.5 * 0.01)
    assert abs(result["value"] - NormalDist().cdf(z)) < 1e-12


def test_small_family_pass_line_is_the_fixed_conservative_threshold() -> None:
    returns = balanced_returns(periods=260, mean=0.001, spread=0.004)  # SR ~ 0.25, strong
    active = active_series_from(returns)
    strong = g.evaluate_dsr_v2(
        active=active,
        family=_family([0.01, 0.02, 0.03], n_periods=200),
        dsr_min=g.DSR_V2_MIN,
        config=g.GATE_V2_CONFIG,
    )
    assert strong["value"] > g.DSR_V2_SMALL_FAMILY_PASS_MIN
    assert strong["passed"] is True
    assert strong["dsr_min_used"] == g.DSR_V2_SMALL_FAMILY_PASS_MIN


@pytest.mark.parametrize(
    "n_members,reason",
    [(0, "family_too_small"), (1, "family_too_small"), (2, "family_too_small")],
)
def test_fewer_than_three_members_is_insufficient(n_members: int, reason: str) -> None:
    returns = balanced_returns(periods=260, mean=0.001, spread=0.004)
    active = active_series_from(returns)
    result = g.evaluate_dsr_v2(
        active=active,
        family=_family([0.1] * n_members),
        dsr_min=g.DSR_V2_MIN,
        config=g.GATE_V2_CONFIG,
    )
    assert result["passed"] is False
    assert result["reason"] == reason


def test_family_members_below_sixty_periods_are_rejected() -> None:
    returns = balanced_returns(periods=260, mean=0.001, spread=0.004)
    active = active_series_from(returns)
    result = g.evaluate_dsr_v2(
        active=active,
        family=_family([0.1, 0.1, 0.1], n_periods=30),
        dsr_min=g.DSR_V2_MIN,
        config=g.GATE_V2_CONFIG,
    )
    assert result["passed"] is False
    assert result["reason"] == "family_member_short_window"


def test_short_candidate_window_blocks_even_a_strong_series() -> None:
    returns = balanced_returns(periods=100, mean=0.001, spread=0.004)
    active = active_series_from(returns)
    result = g.evaluate_dsr_v2(
        active=active,
        family=_family([0.01, 0.02, 0.03], n_periods=200),
        dsr_min=g.DSR_V2_MIN,
        config=g.GATE_V2_CONFIG,
    )
    assert result["passed"] is False
    assert result["reason"] == "candidate_window_too_short"


def test_data_driven_path_delegates_to_the_v1_formula_with_recomputed_family() -> None:
    returns = balanced_returns(periods=260, mean=0.0015, spread=0.004)
    active = active_series_from(returns)
    sharpes = [0.02 * ((index % 5) - 2) for index in range(12)]
    result = g.evaluate_dsr_v2(
        active=active, family=_family(sharpes), dsr_min=g.DSR_V2_MIN, config=g.GATE_V2_CONFIG
    )
    perf = performance_from_daily_returns(returns)
    expected = deflated_sharpe_ratio(
        sharpe=perf["sharpe_period"],
        n_periods=perf["n_periods"],
        skewness=perf["skewness"],
        kurtosis=perf["kurtosis"],
        trial_sharpes=sharpes,
        dsr_min=g.DSR_V2_MIN,
    )
    assert result["path"] == "data_driven"
    assert result["value"] == expected["value"]
    assert result["threshold_sr"] == expected["threshold_sr"]
    assert result["n_trials"] == len(sharpes)


def test_threshold_rises_with_family_length_at_constant_dispersion() -> None:
    returns = balanced_returns(periods=260, mean=0.0015, spread=0.004)
    active = active_series_from(returns)
    short = g.evaluate_dsr_v2(
        active=active, family=_family([0.1, 0.2] * 5), dsr_min=g.DSR_V2_MIN, config=g.GATE_V2_CONFIG
    )
    long = g.evaluate_dsr_v2(
        active=active,
        family=_family([0.1, 0.2] * 25),
        dsr_min=g.DSR_V2_MIN,
        config=g.GATE_V2_CONFIG,
    )
    assert short["path"] == long["path"] == "data_driven"
    assert long["threshold_sr"] > short["threshold_sr"]


def test_wiring_identity_between_v2_sharpe_and_the_recorded_information_ratio() -> None:
    periods = 200
    benchmark_returns = balanced_returns(periods=periods, mean=0.0002, spread=0.008)
    alpha = noise_returns(periods, seed=11, vol=0.002, mean=0.0005)
    equity_returns = [left + right for left, right in zip(benchmark_returns, alpha, strict=True)]
    rows = curve_rows(
        equity_returns=equity_returns, benchmark_returns=benchmark_returns, initial_cash=100_000.0
    )
    active = g.recompute_active_returns(rows, initial_cash=100_000.0)
    frame = pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp(row["date"], tz="UTC"),
                "equity": row["equity"],
                "benchmark": row["benchmark"],
                "peer": row["peer"],
            }
            for row in rows
        ]
    )
    document = active_metrics(
        frame, initial_cash=100_000.0, benchmark_symbol="SPY", include_peer=False
    )
    ir = document["vs_benchmark"]["information_ratio"]["value"]
    assert ir is not None
    n = active["n_periods"]
    sharpe_v2 = performance_from_daily_returns(active["active_returns"])["sharpe_period"]
    expected = ir / math.sqrt(252) * math.sqrt((n - 1) / n)
    assert abs(sharpe_v2 - expected) < 1e-12
