"""Sealed hand-checkable vectors for the active-return sibling block.

No provider, account, storage or scheduler is touched; every expectation is
recomputed independently inside the test (closed form, ``lstsq``, or an explicit
per-seed loop) rather than copied from the implementation.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import quant_system
from quant_system.backtest.metrics import PerformanceMetrics
from quant_system.research import active_metrics as module
from quant_system.research.active_metrics import (
    BOOTSTRAP_BLOCK_LENGTH,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    MIN_OBSERVATIONS,
    _daily_returns,
    active_metrics,
    active_return_block,
    beta_alpha,
    information_ratio,
    paired_block_bootstrap,
    sharpe_se_ci,
    sleeve_active_metrics,
    tracking_error,
)


def sessions(periods, start="2015-01-05"):
    return pd.date_range(start, periods=periods, freq="B", tz="UTC")


def returns_pair(periods=260, start="2015-01-05"):
    index = sessions(periods, start)
    reference = pd.Series(np.sin(np.arange(periods) / 6.0) * 0.008, index=index)
    noise = pd.Series(np.where(np.arange(periods) % 2 == 0, 1.0, -1.0) * 0.002, index=index)
    return reference + 0.0004 + noise, reference


def curve_from(strategy, reference, *, peer=None):
    equity = 100_000.0 * (1.0 + strategy).cumprod()
    benchmark = 100_000.0 * (1.0 + reference).cumprod()
    frame = pd.DataFrame(
        {
            "timestamp": strategy.index,
            "equity": equity.to_numpy(),
            "benchmark": benchmark.to_numpy(),
        }
    )
    if peer is not None:
        frame["peer"] = (100_000.0 * (1.0 + peer).cumprod()).to_numpy()
    return frame


def independent_percentile_bounds(strategy, reference, *, seed, n_resamples, block_length=21):
    """Re-run the moving-block resampling from the seed, return the raw percentile bounds.

    This is the withdrawn interval: the test only needs it as a negative control
    proving the shipped bounds are the studentized ones, not the percentile ones.
    """
    values_s = strategy.to_numpy(dtype=float)
    values_r = reference.to_numpy(dtype=float)
    n = len(values_s)
    blocks = math.ceil(n / block_length)
    generator = np.random.default_rng(seed)
    starts = generator.integers(0, n, size=(n_resamples, blocks))
    offsets = np.arange(block_length)
    index = (starts[:, :, None] + offsets[None, None, :]) % n
    index = index.reshape(n_resamples, -1)[:, :n]

    def sharpe(rows):
        std = rows.std(axis=1, ddof=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(std > 1e-12, rows.mean(axis=1) / std, 0.0)
        return ratio * math.sqrt(252)

    statistics = sharpe(values_s[index]) - sharpe(values_r[index])
    low, high = np.quantile(statistics, [0.025, 0.975])
    return float(low), float(high)


def observation_series(nav, spy, *, allocated_cash):
    """A ``HungSleeveEffectResponse.series``-shaped row list for the sleeve adapter."""
    return [
        {
            "date": day.date().isoformat(),
            "sleeve_equity": float(equity),
            "spy_close": float(close),
            "allocated_cash": allocated_cash,
            "filled": True,
            "covered_sleeve_count": 1,
        }
        for day, equity, close in zip(nav.index, nav.to_numpy(), spy.to_numpy(), strict=True)
    ]


# ---------------------------------------------------------------------------------------
# Case 1 -- active return, tracking error and IR by hand
# ---------------------------------------------------------------------------------------


def test_active_return_tracking_error_and_ir_match_closed_form():
    reference, _ = returns_pair()
    constant = 0.0004
    n = len(reference)
    strategy = reference + constant

    block = active_return_block(strategy, reference, annualization=252)
    assert block["daily_mean"] == pytest.approx(constant, rel=1e-12)
    assert block["annualized"] == pytest.approx(constant * 252, rel=1e-12)
    assert block["cumulative_geometric"] == pytest.approx(
        float((1 + strategy).prod()) / float((1 + reference).prod()) - 1.0, rel=1e-12
    )
    assert block["n_observations"] == n and block["reason"] is None

    flat = tracking_error(strategy - reference, annualization=252)
    assert flat["daily"] == pytest.approx(0.0, abs=1e-15)
    assert flat["annualized"] == pytest.approx(0.0, abs=1e-15)
    zero = information_ratio(strategy - reference, annualization=252)
    assert zero["value"] is None and zero["reason"] == "zero_tracking_error"

    noise = pd.Series(np.where(np.arange(n) % 2 == 0, 1.0, -1.0) * 0.002, index=reference.index)
    strategy = reference + constant + noise
    active = strategy - reference
    expected_mean, expected_std = float(active.mean()), float(active.std(ddof=0))
    assert expected_mean == pytest.approx(constant, rel=1e-12)

    tracking = tracking_error(active, annualization=252)
    assert tracking["daily"] == pytest.approx(expected_std, rel=1e-12)
    assert tracking["annualized"] == pytest.approx(expected_std * math.sqrt(252), rel=1e-12)
    ratio = information_ratio(active, annualization=252)
    assert ratio["value"] == pytest.approx(expected_mean / expected_std * math.sqrt(252), rel=1e-12)
    assert ratio["nw_lag"] == module.newey_west_lag_rule(n, horizon=1)
    assert ratio["se_iid"] is not None and ratio["ci95_low"] < ratio["value"] < ratio["ci95_high"]


# ---------------------------------------------------------------------------------------
# Case 2 -- beta, alpha and alpha(t) against independent least squares
# ---------------------------------------------------------------------------------------


def test_beta_alpha_and_rolling_alpha_match_independent_least_squares():
    periods = 320
    index = sessions(periods)
    reference = pd.Series(np.sin(np.arange(periods) / 7.0) * 0.008, index=index)
    residual = pd.Series(np.where(np.arange(periods) % 2 == 0, 1.0, -1.0) * 0.0005, index=index)
    strategy = 0.0003 + 0.7 * reference + residual

    block = beta_alpha(strategy, reference)
    design = np.column_stack([np.ones(periods), reference.to_numpy()])
    coefficients, *_ = np.linalg.lstsq(design, strategy.to_numpy(), rcond=None)
    assert block["beta"] == pytest.approx(float(coefficients[1]), abs=1e-10)
    assert block["alpha_daily"] == pytest.approx(float(coefficients[0]), abs=1e-10)
    assert block["alpha_annualized"] == pytest.approx(float(coefficients[0]) * 252, abs=1e-8)
    assert block["beta_estimation"] == "full_sample_ols"
    assert (block["window"], block["min_periods"]) == (252, 126)
    assert block["beta_neutral_reason"] is None

    rows = {row["date"]: row["alpha"] for row in block["alpha_t"]}
    assert len(rows) == periods - 126 + 1
    for position in (125, 126, 251, 260, periods - 1):
        start = max(0, position - 251)
        y = strategy.to_numpy()[start : position + 1]
        x = reference.to_numpy()[start : position + 1]
        window_design = np.column_stack([np.ones(len(y)), x])
        window_coefficients, *_ = np.linalg.lstsq(window_design, y, rcond=None)
        assert rows[index[position].date().isoformat()] == pytest.approx(
            float(window_coefficients[0]), abs=1e-10
        )


# ---------------------------------------------------------------------------------------
# Case 3 -- Lo (2002) Sharpe standard error, closed form and deterministic
# ---------------------------------------------------------------------------------------


def test_sharpe_standard_error_and_interval_are_lo2002_closed_form():
    periods = 200
    values = np.tile([0.01, -0.004, 0.006, -0.002], periods // 4)
    series = pd.Series(values, index=pd.RangeIndex(periods))
    block = sharpe_se_ci(series, annualization=252)

    daily = float(series.mean()) / float(series.std(ddof=0))
    annual = daily * math.sqrt(252)
    expected_se = math.sqrt(252) * math.sqrt((1 + daily**2 / 2.0) / periods)
    assert block["sharpe"] == pytest.approx(annual, rel=1e-12)
    assert block["se_iid"] == pytest.approx(expected_se, rel=1e-12)
    assert block["ci95_low"] == pytest.approx(annual - 1.96 * expected_se, rel=1e-12)
    assert block["ci95_high"] == pytest.approx(annual + 1.96 * expected_se, rel=1e-12)
    assert block["method"] == "lo2002_iid" and block["reason"] is None

    short = sharpe_se_ci(series.iloc[: MIN_OBSERVATIONS - 1], annualization=252)
    assert short["sharpe"] is None and short["se_iid"] is None
    assert short["ci95_low"] is None and short["ci95_high"] is None
    assert short["reason"] == "insufficient_observations"
    assert short["method"] == "lo2002_iid"


# ---------------------------------------------------------------------------------------
# Case 4 -- seeded bootstrap determinism and no legacy global RNG anywhere
# ---------------------------------------------------------------------------------------


def test_block_bootstrap_is_seeded_and_never_touches_the_legacy_global_rng(monkeypatch):
    strategy, reference = returns_pair(periods=300)
    first = paired_block_bootstrap(strategy, reference, seed=1234, n_resamples=400)
    twice = paired_block_bootstrap(strategy, reference, seed=1234, n_resamples=400)
    other = paired_block_bootstrap(strategy, reference, seed=4321, n_resamples=400)

    assert first["status"] == "ready"
    assert (first["value"], twice["value"], other["value"]) == (
        first["value"],
        first["value"],
        first["value"],
    )
    assert (first["ci95_low"], first["ci95_high"]) == (twice["ci95_low"], twice["ci95_high"])
    assert (first["ci95_low"], first["ci95_high"]) != (other["ci95_low"], other["ci95_high"])
    assert first["seed"] == 1234 and first["n_resamples"] == 400
    assert first["block_length"] == BOOTSTRAP_BLOCK_LENGTH
    assert first["rng"] == "numpy.random.Generator(PCG64)"
    assert first["method"] == "moving_block_bootstrap_studentized"
    assert first["studentization"] == "delete_one_block_jackknife_se"
    assert first["nominal_coverage"] == 0.95
    assert first["studentized_resamples"] <= 400
    assert first["se"] is not None and first["se"] > 0
    t_low, t_high = first["studentized_quantiles"]
    # The interval is re-derived here from the echoed seed, not copied: the
    # studentized bounds must differ from the raw percentile bounds the same
    # resamples would give (that under-covering interval was withdrawn).
    assert first["ci95_low"] == pytest.approx(first["value"] - t_high * first["se"], rel=1e-12)
    assert first["ci95_high"] == pytest.approx(first["value"] - t_low * first["se"], rel=1e-12)
    raw_low, raw_high = independent_percentile_bounds(
        strategy, reference, seed=1234, n_resamples=400
    )
    assert not np.isclose(first["ci95_low"], raw_low) or not np.isclose(
        first["ci95_high"], raw_high
    )
    assert first["statistic"] == "paired_sharpe_difference"
    assert 0.0 <= first["fraction_bootstrap_positive"] <= 1.0

    guarded_curve = curve_from(strategy, reference)
    replay = active_metrics(
        guarded_curve,
        initial_cash=100_000.0,
        benchmark_symbol="QQQ",
        include_peer=False,
        bootstrap_seed=1234,
        bootstrap_resamples=400,
    )["vs_benchmark"]["block_bootstrap"]
    assert replay["status"] == "ready" and replay["seed"] == 1234
    # The curve round-trip re-derives returns from equity, so only the last bits
    # move; the same route replayed is bit-for-bit identical.
    assert replay["ci95_low"] == pytest.approx(first["ci95_low"], abs=1e-12)
    assert replay["ci95_high"] == pytest.approx(first["ci95_high"], abs=1e-12)
    replayed = active_metrics(
        curve_from(strategy, reference),
        initial_cash=100_000.0,
        benchmark_symbol="QQQ",
        include_peer=False,
        bootstrap_seed=1234,
        bootstrap_resamples=400,
    )["vs_benchmark"]["block_bootstrap"]
    assert (replayed["value"], replayed["ci95_low"], replayed["ci95_high"]) == (
        replay["value"],
        replay["ci95_low"],
        replay["ci95_high"],
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy global numpy.random must not be used")

    for name in ("random", "randint", "normal", "uniform", "choice", "shuffle", "seed"):
        monkeypatch.setattr(np.random, name, forbidden)
    guarded = active_metrics(
        curve_from(strategy, reference),
        initial_cash=100_000.0,
        benchmark_symbol="QQQ",
        include_peer=False,
        bootstrap_seed=1234,
        bootstrap_resamples=400,
    )["vs_benchmark"]["block_bootstrap"]
    assert (guarded["value"], guarded["ci95_low"], guarded["ci95_high"]) == (
        replay["value"],
        replay["ci95_low"],
        replay["ci95_high"],
    )


# ---------------------------------------------------------------------------------------
# Case 5 -- interval coverage and the 21-session block structure
# ---------------------------------------------------------------------------------------


def paired_draw(seed, periods=252):
    rng = np.random.default_rng(seed)
    index = sessions(periods)
    reference = pd.Series(rng.normal(0.0, 0.01, periods), index=index)
    strategy = pd.Series(reference.to_numpy() + rng.normal(0.0, 0.002, periods), index=index)
    return strategy, reference


def test_studentized_interval_coverage_beats_the_withdrawn_percentile_interval():
    """The shipped 95% label must be backed by measurement, not by hope.

    At n=126 the paired bootstrap's spread is ~20% too narrow, so the raw
    percentile interval covered a true zero Sharpe difference only ~0.88 of the
    time. The studentized interval must clear 0.90 on the same trials (the full
    grid, seeds and trial counts live in the T2.2 coverage calibration note;
    this is the regression tripwire, not the calibration itself).
    """
    trials = studentized_covered = percentile_covered = 0
    for trial in range(300):
        strategy, reference = paired_draw(10_000 + trial, periods=126)
        block = paired_block_bootstrap(strategy, reference, seed=500 + trial, n_resamples=1000)
        assert block["status"] == "ready"
        raw_low, raw_high = independent_percentile_bounds(
            strategy, reference, seed=500 + trial, n_resamples=1000
        )
        trials += 1
        studentized_covered += bool(block["ci95_low"] <= 0.0 <= block["ci95_high"])
        percentile_covered += bool(raw_low <= 0.0 <= raw_high)
    assert studentized_covered / trials >= 0.90
    # Negative control: the interval this method replaced must NOT be the one
    # passing, and it must still under-cover at this sample size.
    assert percentile_covered / trials < 0.90
    assert studentized_covered > percentile_covered


def test_block_length_and_sample_floor_are_enforced_exactly():
    """Both boundaries are exact: the 2*block rule and the published sample floor."""
    strategy, reference = returns_pair(periods=MIN_OBSERVATIONS)
    assert paired_block_bootstrap(strategy, reference, block_length=21)["status"] == "ready"
    assert paired_block_bootstrap(strategy, reference, block_length=63)["status"] == "ready"
    # n < 2 * block_length: 126 < 128 must fail by name, not raise.
    oversized = paired_block_bootstrap(strategy, reference, block_length=64)
    assert oversized["status"] == "unavailable"
    assert oversized["reason"] == "insufficient_observations_for_block_bootstrap"
    # n < MIN_BOOTSTRAP_OBSERVATIONS: 125 < 126 must fail the same way.
    thin = paired_block_bootstrap(
        strategy.iloc[: MIN_OBSERVATIONS - 1],
        reference.iloc[: MIN_OBSERVATIONS - 1],
        block_length=21,
    )
    assert thin["status"] == "unavailable"
    assert thin["reason"] == "insufficient_observations_for_block_bootstrap"
    assert thin["ci95_low"] is None and thin["ci95_high"] is None
    assert thin["block_length"] == 21 and thin["n_resamples"] == BOOTSTRAP_RESAMPLES


def test_block_length_captures_serial_dependence():
    # A persistent pairing must widen the interval only when whole 21-session runs survive.
    periods = 420
    index = sessions(periods)
    persistent = pd.Series(
        np.repeat(np.sin(np.arange(periods // 21) / 2.0) * 0.01 + 0.002, 21)[:periods], index=index
    )
    reference = pd.Series(np.sin(np.arange(periods) / 9.0) * 0.006, index=index)
    paired = persistent + np.tile(np.linspace(-0.002, 0.002, 21), periods // 21)
    wide = paired_block_bootstrap(paired, reference, block_length=21, n_resamples=1000, seed=7)
    narrow = paired_block_bootstrap(paired, reference, block_length=1, n_resamples=1000, seed=7)
    assert wide["status"] == narrow["status"] == "ready"
    assert wide["ci95_high"] - wide["ci95_low"] > 1.5 * (narrow["ci95_high"] - narrow["ci95_low"])


# ---------------------------------------------------------------------------------------
# Case 6 -- structural boundaries and named guardrails
# ---------------------------------------------------------------------------------------


def test_empty_curve_and_missing_columns_are_unavailable_without_raising():
    empty = active_metrics(pd.DataFrame(), initial_cash=100_000.0)
    assert empty["status"] == "unavailable" and empty["reason"] == "no_curve"
    assert empty["vs_benchmark"] is None and empty["vs_peer"] is None
    assert empty["schema_version"] == "active_metrics_v1"
    assert empty["disclosure"]["evaluation_only"] is True
    assert empty["disclosure"]["dsr_family_member"] is False
    assert empty["disclosure"]["tradeable_claim"] is False
    json.dumps(empty, allow_nan=False)

    blank = pd.DataFrame({"timestamp": [], "equity": [], "benchmark": []})
    assert active_metrics(blank, initial_cash=100_000.0)["reason"] == "no_curve"
    partial = pd.DataFrame({"timestamp": sessions(3), "equity": [1.0, 2.0, 3.0]})
    missing = active_metrics(partial, initial_cash=100_000.0)
    assert missing["reason"] == "active_metrics_missing_columns"


def test_short_samples_degrade_to_named_reasons_instead_of_fragile_numbers():
    strategy, reference = returns_pair(periods=100)
    ratio = information_ratio(strategy - reference)
    assert ratio["value"] is None and ratio["nw_t"] is None
    assert ratio["reason"] == "insufficient_observations"
    ci = sharpe_se_ci(strategy)
    assert ci["sharpe"] is None and ci["se_iid"] is None
    assert ci["reason"] == "insufficient_observations"

    strategy, reference = returns_pair(periods=30)
    bootstrap = paired_block_bootstrap(strategy, reference)
    assert bootstrap["status"] == "unavailable"
    assert bootstrap["reason"] == "insufficient_observations_for_block_bootstrap"
    assert bootstrap["ci95_low"] is None and bootstrap["ci95_high"] is None
    assert bootstrap["seed"] == BOOTSTRAP_SEED

    constant = pd.Series(np.full(200, 0.001), index=sessions(200))
    hedge = beta_alpha(constant + 0.0002, constant)
    assert hedge["beta"] is None and hedge["alpha_daily"] is None
    assert hedge["beta_neutral_reason"] == "zero_benchmark_variance"
    assert hedge["alpha_t"] == []


def test_returns_drop_only_the_missing_pair_and_mismatched_calendars_fail_by_name():
    index = sessions(6)
    reference = pd.Series([0.001, 0.002, 0.003, 0.004, 0.005, 0.006], index=index)
    strategy = pd.Series([0.0011, np.nan, 0.0032, 0.0041, 0.0052, 0.0061], index=index)
    block = active_return_block(strategy, reference)
    keep = [0, 2, 3, 4, 5]  # index 1 is the only dropped pair
    assert block["n_observations"] == len(keep)
    assert block["daily_mean"] == pytest.approx(
        float(np.mean(strategy.to_numpy()[keep] - reference.to_numpy()[keep])), rel=1e-12
    )
    assert block["cumulative_geometric"] == pytest.approx(
        math.prod(1 + strategy.to_numpy()[keep]) / math.prod(1 + reference.to_numpy()[keep]) - 1.0,
        rel=1e-12,
    )

    with pytest.raises(ValueError, match="active_metrics_calendar_mismatch"):
        active_return_block(strategy.iloc[:5], reference)
    with pytest.raises(ValueError, match="active_metrics_calendar_mismatch"):
        paired_block_bootstrap(strategy.iloc[:5], reference)


def test_first_day_is_funded_from_the_declared_initial_cash():
    index = sessions(3)
    equity = pd.Series([100_000.0, 101_000.0, 101_000.0], index=index)
    expected = pd.Series([0.0, 0.01, 0.0], index=index)
    pd.testing.assert_series_equal(_daily_returns(equity, 100_000.0), expected)


# ---------------------------------------------------------------------------------------
# Case 6b -- the repaired boundaries: named reasons for SF3/SF4/SF5/SF6
# ---------------------------------------------------------------------------------------


def test_alpha_path_counts_only_degenerate_windows_and_never_warm_up():
    """SF3: a flat benchmark is counted with a reason; warm-up is not."""
    periods = 400
    index = sessions(periods)
    # First 150 sessions the benchmark is flat, so the evaluated windows that
    # open inside the flat prefix have zero benchmark variance and can yield
    # neither a beta nor an alpha.
    reference = pd.Series(
        np.concatenate([np.zeros(150), np.sin(np.arange(periods - 150) / 7.0) * 0.008]),
        index=index,
    )
    noise = np.where(np.arange(periods) % 2 == 0, 1.0, -1.0) * 0.0005
    strategy = pd.Series(0.0003 + 0.7 * reference.to_numpy() + noise, index=index)
    block = beta_alpha(strategy, reference)
    assert block["alpha_t"], "the evaluable windows must still be emitted"
    dropped = block["alpha_t_dropped_zero_variance"]
    assert dropped > 0
    assert block["alpha_t_reason"] == "alpha_windows_dropped_zero_variance"
    assert block["alpha_t_windows"] == len(block["alpha_t"]) + dropped
    # Only genuinely flat windows are counted: the count equals the number of
    # evaluated positions whose window sits entirely inside the flat prefix.
    assert dropped == 26
    assert len(block["alpha_t"]) == periods - 125 - dropped

    # The ordinary case must not cry wolf: no flat stretch, no reason.
    clean_reference = pd.Series(np.sin(np.arange(320) / 7.0) * 0.008, index=sessions(320))
    clean = beta_alpha(clean_reference + 0.0003, clean_reference)
    assert clean["alpha_t_dropped_zero_variance"] == 0
    assert clean["alpha_t_reason"] is None
    assert clean["alpha_t_windows"] == len(clean["alpha_t"])


def test_beta_alpha_guards_the_strategy_leg_symmetrically():
    """SF4: a constant strategy against a moving benchmark is degenerate, not beta=0."""
    periods = 300
    index = sessions(periods)
    reference = pd.Series(np.sin(np.arange(periods) / 7.0) * 0.008, index=index)
    constant = pd.Series(np.full(periods, 0.0002), index=index)
    block = beta_alpha(constant, reference)
    assert block["beta"] is None and block["alpha_daily"] is None
    assert block["beta_neutral_reason"] == "zero_strategy_variance"
    assert block["alpha_t"] == [] and block["alpha_t_dropped_zero_variance"] == 0
    # The benchmark-side guard still wins when both legs are degenerate.
    flat = pd.Series(np.zeros(periods), index=index)
    both = beta_alpha(flat, flat)
    assert both["beta_neutral_reason"] == "zero_benchmark_variance"


def test_block_bootstrap_rejects_a_nonpositive_block_length_by_name():
    strategy, reference = returns_pair(periods=300)
    for bad in (0, -1, -21):
        guarded = paired_block_bootstrap(strategy, reference, block_length=bad)
        assert guarded["status"] == "unavailable"
        assert guarded["reason"] == "invalid_block_length"
        assert guarded["ci95_low"] is None and guarded["ci95_high"] is None
        assert guarded["block_length"] == bad
    guarded = paired_block_bootstrap(strategy, reference, n_resamples=0)
    assert guarded["reason"] == "invalid_resamples"
    # The smallest legal block still works and is what the boundary allows.
    assert paired_block_bootstrap(strategy, reference, block_length=1)["status"] == "ready"


def test_alpha_labels_follow_the_input_timezone_not_utc():
    """SF6: midnight sessions in a non-UTC zone must keep their own trading day."""
    periods = 300
    tokyo = pd.date_range("2020-01-06", periods=periods, freq="B", tz="Asia/Tokyo")
    reference = pd.Series(np.sin(np.arange(periods) / 7.0) * 0.008, index=tokyo)
    strategy = reference + 0.0004
    curve = curve_from(strategy, reference)

    block = active_metrics(
        curve, initial_cash=100_000.0, benchmark_symbol="QQQ", include_peer=False
    )
    assert block["disclosure"]["timezone"] == "Asia/Tokyo"
    assert block["start"] == tokyo[0].date().isoformat() == "2020-01-06"
    assert block["vs_benchmark"]["alpha_t"][0]["date"] == tokyo[125].date().isoformat()

    # The same instants re-expressed in UTC would label a day earlier; the
    # default keeps whatever timezone the caller handed in, so the label holds.
    utc_curve = curve.copy()
    utc_curve["timestamp"] = tokyo.tz_convert("UTC")
    utc_default = active_metrics(
        utc_curve, initial_cash=100_000.0, benchmark_symbol="QQQ", include_peer=False
    )
    assert utc_default["disclosure"]["timezone"] == "UTC"
    assert utc_default["vs_benchmark"]["alpha_t"][0]["date"] == "2020-06-28"
    assert utc_default["start"] == "2020-01-05"

    # An explicit timezone recovers the local trading day.
    explicit = active_metrics(
        utc_curve,
        initial_cash=100_000.0,
        benchmark_symbol="QQQ",
        include_peer=False,
        timezone="Asia/Tokyo",
    )
    assert explicit["vs_benchmark"]["alpha_t"][0]["date"] == tokyo[125].date().isoformat()
    assert explicit["start"] == "2020-01-06"

    # Naive input is unchanged: labels stay in UTC.
    naive = pd.date_range("2020-01-06", periods=periods, freq="B")
    naive_reference = pd.Series(np.sin(np.arange(periods) / 7.0) * 0.008, index=naive)
    naive_curve = curve_from(naive_reference + 0.0004, naive_reference)
    naive_block = active_metrics(
        naive_curve, initial_cash=100_000.0, benchmark_symbol="QQQ", include_peer=False
    )
    assert naive_block["disclosure"]["timezone"] is None
    assert naive_block["start"] == "2020-01-06"


def test_sleeve_adapter_turns_an_observation_series_into_an_active_block():
    """SF2: the two paper sleeves' NAV leg vs SPY, from the real observed shape."""
    periods = 320
    index = sessions(periods, start="2025-01-02")
    rng = np.random.default_rng(20260918)
    reference = pd.Series(rng.normal(0.0004, 0.009, periods), index=index)
    strategy = pd.Series(rng.normal(0.0006, 0.011, periods), index=index)
    nav = 10_000.0 * (1.0 + strategy).cumprod()
    spy = 500.0 * (1.0 + reference).cumprod()
    series = observation_series(nav, spy, allocated_cash=10_000.0)

    block = sleeve_active_metrics(series, benchmark_symbol="SPY")
    assert block["status"] == "ready"
    assert block["vs_benchmark"]["benchmark_symbol"] == "SPY"
    assert block["vs_peer"] is None
    assert block["n_observations"] >= 126
    assert set(block["vs_benchmark"]) >= {
        "active_return",
        "tracking_error",
        "information_ratio",
        "beta_alpha",
        "alpha_t",
        "sharpe_se_ci",
        "block_bootstrap",
    }
    assert block["vs_benchmark"]["block_bootstrap"]["status"] == "ready"
    # The NAV leg and the SPY leg are the curves the adapter built, nothing else.
    # Each leg is rebased to its own first valued mark (they are on different
    # scales, and one shared initial_cash would fund the SPY leg from the NAV).
    nav = 10_000.0 * (1.0 + strategy).cumprod()
    spy = 500.0 * (1.0 + reference).cumprod()
    expected = active_metrics(
        pd.DataFrame(
            {
                "timestamp": index,
                "equity": (nav / nav.iloc[0]).to_numpy(),
                "benchmark": (spy / spy.iloc[0]).to_numpy(),
            }
        ),
        initial_cash=1.0,
        benchmark_symbol="SPY",
        include_peer=False,
    )
    assert block["vs_benchmark"] == expected["vs_benchmark"]
    assert block["n_observations"] == expected["n_observations"]
    json.dumps(block, allow_nan=False)

    # Missing valuation days are dropped pairwise, never fabricated: the 20 hole
    # rows AND the row after the hole leave (no return can span a hole). The
    # initial-cash fallback used to inject one fabricated level-ratio return there
    # and inflated the information ratio from 1.351 to 1.634 (measured with this
    # fixture), so the band below fails loudly if the fallback ever returns.
    holed = [dict(row) for row in series]
    for row in holed[40:60]:
        row["sleeve_equity"] = None
    thinned = sleeve_active_metrics(holed)
    assert thinned["n_observations"] == block["n_observations"] - 21
    assert thinned["sessions_dropped_missing_marks"] == 21
    control_te = block["vs_benchmark"]["tracking_error"]["annualized"]
    holed_te = thinned["vs_benchmark"]["tracking_error"]["annualized"]
    assert abs(holed_te - control_te) < 0.01

    # A sparse (non-session) observation series must fail by name rather than being
    # annualized as if daily, which would inflate TE and the block bootstrap.
    weekly = [row for index, row in enumerate(series) if index % 5 == 0]
    sparse = sleeve_active_metrics(weekly)
    assert sparse["status"] == "unavailable"
    assert sparse["reason"] == "sparse_sleeve_observation_series"
    assert sparse["vs_benchmark"] is None
    # A dense series with one long hole would count a multi-week span as a single
    # session return; it is rejected by name. The gap is also reported on a ready
    # document so a reader can see the worst spacing without re-deriving it.
    holed_gap = [row for index, row in enumerate(series) if not 150 <= index < 180]
    long_gap = sleeve_active_metrics(holed_gap)
    assert long_gap["status"] == "unavailable"
    assert long_gap["reason"] == "gap_in_sleeve_observation_series"
    assert block["max_observation_gap_days"] == 3

    ambiguous = sleeve_active_metrics(series, unavailable_reason="sleeve_capital_change_ambiguous")
    assert ambiguous["status"] == "unavailable"
    assert ambiguous["reason"] == "sleeve_capital_change_ambiguous"
    assert ambiguous["vs_benchmark"] is None
    # The unavailable document must carry the same disclosure surface as a ready
    # one, so a reader never loses the methodology provenance on a degraded read.
    assert set(ambiguous["disclosure"]) == set(block["disclosure"])
    empty = sleeve_active_metrics([])
    assert empty["status"] == "unavailable" and empty["reason"] == "no_sleeve_observations"

    # The disclosure VALUE, not only the key set, survives a degraded read: a
    # tz-aware series resolves its label timezone from the data on both branches.
    tokyo = pd.date_range("2025-01-02", periods=200, freq="B", tz="Asia/Tokyo")
    tokyo_series = [
        {
            "date": day.isoformat(),
            "sleeve_equity": 10_000.0 + 12.0 * position,
            "spy_close": 500.0 + 0.4 * position,
        }
        for position, day in enumerate(tokyo)
    ]
    tz_ready = sleeve_active_metrics(tokyo_series)
    tz_degraded = sleeve_active_metrics(
        tokyo_series, unavailable_reason="sleeve_capital_change_ambiguous"
    )
    assert tz_ready["disclosure"] == tz_degraded["disclosure"]
    assert tz_degraded["disclosure"]["timezone"] == "UTC+09:00"


# ---------------------------------------------------------------------------------------
# Case 7 -- regression seal over the frozen legacy surfaces
# ---------------------------------------------------------------------------------------


def test_frozen_metric_surfaces_keep_their_exact_keys_and_sources():
    from quant_system.research.reference_backtests import _METRIC_KEYS, INITIAL_CASH, _metrics
    from quant_system.research.strategy_library_cli import _METRICS

    assert len(_METRIC_KEYS) == 8
    curve = pd.DataFrame(
        {"timestamp": sessions(4), "equity": [100_000.0, 100_500.0, 100_200.0, 101_000.0]}
    )
    measured = _metrics(curve, pd.DataFrame(), INITIAL_CASH)
    assert set(measured) == set(_METRIC_KEYS)
    assert "active_metrics" not in measured
    assert set(_METRICS) == {
        "total_return",
        "annualized_return",
        "sharpe",
        "max_drawdown",
        "turnover",
    }
    assert set(PerformanceMetrics.model_fields) == {
        "total_return",
        "annualized_return",
        "volatility",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "turnover",
        "attribution",
    }
    frozen = Path(quant_system.backtest.metrics.__file__).read_text(encoding="utf-8")
    assert "active_metrics" not in frozen


def test_new_block_is_a_sibling_and_the_page_payload_downsamples_alpha():
    from quant_system.research.evaluation_service import _view
    from quant_system.research.strategy_library_cli import _validation

    strategy, reference = returns_pair(periods=300)
    block = active_metrics(
        curve_from(strategy, reference, peer=reference),
        initial_cash=100_000.0,
        benchmark_symbol="QQQ",
    )
    assert {"vs_benchmark", "vs_peer"} <= set(block)
    assert set(block["vs_benchmark"]) >= {
        "active_return",
        "tracking_error",
        "information_ratio",
        "beta_alpha",
        "alpha_t",
        "sharpe_se_ci",
        "block_bootstrap",
    }
    assert block["vs_peer"]["reference_kind"] == "peer"
    json.dumps(block, allow_nan=False)

    shown = _validation({"platform_metrics": {"total_return": 0.1}, "active_metrics": block})
    assert shown["active_metrics"] == block
    assert set(shown["platform_metrics"]) == {
        "total_return",
        "annualized_return",
        "sharpe",
        "max_drawdown",
        "turnover",
    }
    assert _validation({"platform_metrics": {}})["active_metrics"] == {}

    long_alpha = [{"date": f"day-{number}", "alpha": number} for number in range(900)]
    page = _view({"active_metrics": {"vs_benchmark": {"alpha_t": long_alpha}}})
    shown_alpha = page["active_metrics"]["vs_benchmark"]["alpha_t"]
    assert 0 < len(shown_alpha) <= 401
    assert shown_alpha[0] == {"date": "day-0", "alpha": 0}
    assert shown_alpha[-1] == {"date": "day-899", "alpha": 899}


# ---------------------------------------------------------------------------------------
# Case 8 -- strategy_runtime wiring (the strategy_library validation seam)
# ---------------------------------------------------------------------------------------


def test_strategy_runtime_evaluation_attaches_the_active_block():
    from quant_system.research.strategy_definition import StrategyDefinition, StrategyFactor
    from quant_system.research.strategy_runtime import _calendar, evaluate_definition

    calendar_sessions = pd.to_datetime(
        _calendar(2018, 2020).sessions_in_range("2019-01-02", "2020-04-07"), utc=True
    )
    rows = []
    for number, symbol in enumerate(("AAPL", "MSFT", "NVDA", "SPY")):
        path = 100 * np.exp(np.arange(len(calendar_sessions)) * (number + 1) / 5_000)
        rows += [
            {
                "symbol": symbol,
                "timestamp": day,
                "open": price,
                "close": price,
                "high": price * 1.01,
                "low": price * 0.99,
                "volume": 1_000_000,
                "provider": "futu",
                "price_adjustment": "qfq",
                "interval": "1d",
            }
            for day, price in zip(calendar_sessions, path, strict=True)
        ]
    definition = StrategyDefinition(
        kind="factor_blend",
        title="测试组合",
        symbols=["AAPL", "MSFT", "NVDA"],
        history_start="2019-01-02",
        benchmark_symbol="SPY",
        top_n=2,
        normalization="rank",
        factors=[
            StrategyFactor(
                factor_id="momentum", lookback=2, direction="higher_is_better", weight=1
            ),
            StrategyFactor(
                factor_id="volatility", lookback=5, direction="lower_is_better", weight=0.25
            ),
        ],
    )
    result = evaluate_definition(pd.DataFrame(rows), definition, "2019-06-03", "2020-04-07")
    assert result["status"] == "available", result
    block = result["active_metrics"]
    assert block["schema_version"] == "active_metrics_v1"
    assert block["n_observations"] >= 126
    assert block["vs_benchmark"]["benchmark_symbol"] == "SPY"
    assert block["vs_peer"]["reference_kind"] == "peer"
    assert set(result["metrics"]) == {
        "total_return",
        "annualized_return",
        "volatility",
        "sharpe",
        "sortino",
        "calmar",
        "max_drawdown",
        "turnover",
    }
    json.dumps(result, allow_nan=False)
