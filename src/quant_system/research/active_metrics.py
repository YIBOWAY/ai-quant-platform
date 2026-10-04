"""Active-return metrics of one evaluated leg against a benchmark or peer leg.

Pure, deterministic, read-only: the module consumes a ``curve`` frame already
assembled by an evaluation seam (``timestamp``, ``equity``, ``benchmark`` and
optionally ``peer``), recomputes no backtest and touches no storage. All blocks
are display-only research evidence -- ``evaluation_only``/``dsr_family_member``
are pinned false so these numbers can never enter the DSR trial family or a
significance verdict.

Conventions are inherited verbatim from their audited homes rather than
redefined: daily returns, ``ddof=0`` dispersion and the 252 annualization from
``research/reference_backtests.py`` and ``backtest/metrics.py``; the full-sample
OLS hedge, the 252/126 rolling beta window and the Newey-West lag rule from
``factors/scorecard.py`` and ``factors/evaluation.py``.

The paired Sharpe-difference interval is a **studentized** moving-block bootstrap
(bootstrap-t): the resampled statistics are divided by a delete-one-block
jackknife standard error, and the observed statistic is re-scaled by its own
jackknife standard error. The plain percentile interval that this module first
shipped under-covered its stated 95% level badly (measured 0.74 at n=42 and 0.89
at n=126 up to 0.93 at n=504; the bootstrap spread is ~20% too narrow there) and
was withdrawn. The calibration grid, seeds and trial counts behind the
replacement live in ``evidence/phase2-t22-2026-09-18/t22-coverage-calibration.md``;
over n=126..2016 and two DGPs (i.i.d. and AR(1)+GARCH(1,1)) the studentized
interval measures 0.943-0.950, so ``ci95_*`` is a 95% label the measurement
supports and ``MIN_BOOTSTRAP_OBSERVATIONS`` is set where that starts holding.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_system.factors.evaluation import newey_west_lag_rule, newey_west_stats

ACTIVE_METRICS_SCHEMA_VERSION = "active_metrics_v1"
ANNUALIZATION = 252
BETA_WINDOW = 252
BETA_MIN_PERIODS = 126
BOOTSTRAP_BLOCK_LENGTH = 21
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20260918
MIN_OBSERVATIONS = 126
# The bootstrap previously fired from 2*block_length = 42, which leaves only two
# delete-one-block jackknife groups and a spread that under-covers badly (the raw
# percentile interval measured 0.74 there). The floor now matches MIN_OBSERVATIONS:
# at n=126 the studentized interval measures 0.945-0.950 across both calibration
# DGPs, i.e. the "95%" label is honest everywhere the block can emit at all.
MIN_BOOTSTRAP_OBSERVATIONS = MIN_OBSERVATIONS

_ZERO_VARIANCE = 1e-12
# A sleeve hole wider than two calendar weeks cannot be annualized as a single
# session without inventing a return; holiday weeks (7 calendar days) stay inside.
_MAX_SLEEVE_GAP_DAYS = 10
_SHARPE_METHOD = "lo2002_iid"
_BOOTSTRAP_METHOD = "moving_block_bootstrap_studentized"
_BOOTSTRAP_STATISTIC = "paired_sharpe_difference"
_BOOTSTRAP_STUDENTIZATION = "delete_one_block_jackknife_se"
_NOMINAL_COVERAGE = 0.95
# Measured coverage of the studentized interval over the calibration grid
# (n=126..2016, i.e. at or above the shipped floor; i.i.d. and AR(1)+GARCH(1,1)
# DGPs; 2000 trials per cell, with a 6000-trial refinement of the mid range).
# Carried into the artifact so the "95%" label is never separated from the
# number that backs it. See evidence/phase2-t22-2026-09-18/t22-coverage-calibration.md.
_MEASURED_COVERAGE = (0.93, 0.95)
_RNG_DESCRIPTION = "numpy.random.Generator(PCG64)"
_LAG_RULE = "newey_west_lag_rule(n, horizon=1)"
_DISCLOSURE_NOTE = (
    "全样本 OLS 对冲（样本内，轻度前视）；α(t) 为 252/126 滚动截距，相邻点重叠自相关，"
    "其推断放在 hedged 残差的 NW t 上；永不输出二元显著性裁决；CI/功效需 T>=126。"
    "配对 Sharpe 差的区间为 studentized 块 bootstrap（bootstrap-t，"
    "delete-one-block jackknife 学生化）；覆盖校准见 active_metrics 模块文档。"
)
_BENCHMARK_DEFINITION = (
    "per-profile benchmark_symbol（QQQ/SPY 等）；peer=同池等权对照；非家族合成指数"
)


def _f(value: Any) -> float | None:
    """JSON-safe leaf: non-finite and non-numeric inputs collapse to None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso(value: Any, tz: Any = None) -> str:
    """Calendar day of a timestamp, in the caller's reference timezone.

    ``None`` keeps the historical behaviour (the stamp's own day, UTC for the
    internal index). A ``tz`` converts first, so a session that is stored as
    ``2020-01-02T00:00+09:00`` is labelled ``2020-01-02`` rather than the
    earlier UTC day ``2020-01-01``.
    """
    stamp = pd.Timestamp(value)
    if tz is not None:
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        stamp = stamp.tz_convert(tz)
    return stamp.date().isoformat()


def _label_timezone(raw: Any, requested: Any) -> Any:
    """Resolve the reference timezone for date labels.

    An explicit ``requested`` wins; otherwise the input's own timezone is kept,
    so already-local timestamps do not silently shift a day under a UTC
    conversion. Naive input and unparseable input both fall back to ``None``.
    """
    if requested is not None:
        return requested
    try:
        parsed = pd.to_datetime(raw, errors="raise")
    except (ValueError, TypeError):
        return None
    tz = getattr(getattr(parsed, "dt", None), "tz", None)
    if tz is None and isinstance(parsed, pd.Series):
        return None
    return tz


def _clean(values: Any) -> pd.Series:
    series = pd.to_numeric(pd.Series(values, dtype="float64"), errors="coerce")
    return series.replace([np.inf, -np.inf], np.nan).dropna()


def _daily_returns(equity: pd.Series, initial_cash: float) -> pd.Series:
    """First mark is funded from cash; interior gaps stay NaN for pairwise alignment.

    The reference seam funds *every* missing previous mark from the initial cash.
    For a curve that starts at the initial cash that fallback injects one
    fabricated level-ratio return on the first row after an interior hole (the
    rows inside the hole are dropped as NaN numerators) — measured on the sleeve
    fixture, one hole of 20 sessions inflated the information ratio from 1.351 to
    1.634 (review defect D1). Funding only position 0 leaves the gap as NaN, so
    ``_aligned`` drops the pair instead of inventing alpha.
    """
    previous = equity.shift(1)
    if len(previous) > 0:
        previous.iloc[0] = initial_cash
    return equity.div(previous).sub(1.0)


def _aligned(strategy: pd.Series, reference: pd.Series) -> pd.DataFrame:
    """Pairwise-complete joint frame; unequal calendars fail by name, never silently."""
    if not strategy.index.equals(reference.index):
        raise ValueError("active_metrics_calendar_mismatch")
    frame = pd.DataFrame({"strategy": strategy, "reference": reference}).dropna()
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("active_metrics_nonfinite_returns")
    return frame


def _annualized_sharpe(values: np.ndarray, *, annualization: int) -> float:
    std = float(values.std(ddof=0))
    if not math.isfinite(std) or std <= _ZERO_VARIANCE:
        return 0.0
    return float(values.mean()) / std * math.sqrt(annualization)


def _annualized_sharpe_matrix(values: np.ndarray, *, annualization: int) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        std = values.std(axis=1, ddof=0)
        ratio = np.where(std > _ZERO_VARIANCE, values.mean(axis=1) / std, 0.0)
    return np.asarray(ratio, dtype=float) * math.sqrt(annualization)


def _leave_one_block_sharpe_matrix(
    values: np.ndarray, *, block_length: int, annualization: int
) -> np.ndarray:
    """``(R, K)`` annualized Sharpe of every row with one of its ``K`` blocks removed.

    Exact block sums via ``reduceat`` keep this O(R*n) instead of a Python loop
    over blocks, so the studentized interval stays cheap next to the resampling.
    """
    _, n = values.shape
    starts = np.arange(0, n, int(block_length))
    counts = np.diff(np.append(starts, n))
    squared = values * values
    block_sums = np.add.reduceat(values, starts, axis=1)
    block_sumsq = np.add.reduceat(squared, starts, axis=1)
    total = values.sum(axis=1, keepdims=True)
    total_sq = squared.sum(axis=1, keepdims=True)
    remaining = n - counts
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = (total - block_sums) / remaining
        variance = (total_sq - block_sumsq) / remaining - mean * mean
        std = np.sqrt(np.maximum(variance, 0.0))
        ratio = np.where(std > _ZERO_VARIANCE, mean / std, 0.0)
    return np.asarray(ratio, dtype=float) * math.sqrt(annualization)


def _jackknife_standard_error(
    strategy: np.ndarray, reference: np.ndarray, *, block_length: int, annualization: int
) -> np.ndarray:
    """Delete-one-block jackknife SE of the paired Sharpe difference, per row.

    ``NaN`` marks a row whose jackknife is degenerate (fewer than two usable
    blocks, or a zero acceleration denominator); callers drop those from the
    studentized quantiles and fail closed if too few survive.
    """
    strategy_blocks = _leave_one_block_sharpe_matrix(
        strategy, block_length=block_length, annualization=annualization
    )
    reference_blocks = _leave_one_block_sharpe_matrix(
        reference, block_length=block_length, annualization=annualization
    )
    differences = strategy_blocks - reference_blocks
    count = differences.shape[1]
    if count < 2:
        return np.full(differences.shape[0], np.nan)
    mean = differences.mean(axis=1, keepdims=True)
    variance = (count - 1) / count * ((differences - mean) ** 2).sum(axis=1)
    with np.errstate(invalid="ignore"):
        error = np.sqrt(variance)
    return np.where(error > 0, error, np.nan)


def paired_block_bootstrap(
    strategy: pd.Series,
    reference: pd.Series,
    *,
    block_length: int = BOOTSTRAP_BLOCK_LENGTH,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    annualization: int = ANNUALIZATION,
    min_observations: int = MIN_BOOTSTRAP_OBSERVATIONS,
) -> dict:
    """Studentized circular moving-block bootstrap of the paired Sharpe difference.

    Both legs are resampled on the same block indices so their contemporaneous
    correlation survives; each resampled statistic is studentized by a
    delete-one-block jackknife standard error and the observed statistic is
    re-scaled by its own, which is what pulls the nominal 95% interval up to a
    measured 0.94-0.95 (the plain percentile interval covered only 0.89-0.93).
    The only randomness is an explicit PCG64 generator and every input that
    shapes the interval is echoed into the artifact.
    """
    result: dict = {
        "statistic": _BOOTSTRAP_STATISTIC,
        "status": "unavailable",
        "value": None,
        "se": None,
        "ci95_low": None,
        "ci95_high": None,
        "nominal_coverage": _NOMINAL_COVERAGE,
        "fraction_bootstrap_positive": None,
        "method": _BOOTSTRAP_METHOD,
        "studentization": _BOOTSTRAP_STUDENTIZATION,
        "block_length": int(block_length),
        "n_resamples": int(n_resamples),
        "seed": int(seed),
        "rng": _RNG_DESCRIPTION,
        "reason": None,
    }
    # A non-positive block length has no meaning (0 divides by zero, -1 asks
    # numpy for a negative axis); name it instead of raising out of the seam.
    if int(block_length) < 1:
        return {**result, "reason": "invalid_block_length"}
    if int(n_resamples) < 1:
        return {**result, "reason": "invalid_resamples"}
    frame = _aligned(strategy, reference)
    n = len(frame)
    if n < 2 * int(block_length) or n < min_observations:
        return {**result, "reason": "insufficient_observations_for_block_bootstrap"}
    strategy_values = frame["strategy"].to_numpy(dtype=float)
    reference_values = frame["reference"].to_numpy(dtype=float)
    if (
        float(strategy_values.std(ddof=0)) <= _ZERO_VARIANCE
        or float(reference_values.std(ddof=0)) <= _ZERO_VARIANCE
    ):
        return {**result, "reason": "zero_variance"}
    interval = int(block_length)
    blocks = math.ceil(n / interval)
    value = _annualized_sharpe(strategy_values, annualization=annualization) - (
        _annualized_sharpe(reference_values, annualization=annualization)
    )
    generator = np.random.default_rng(int(seed))
    starts = generator.integers(0, n, size=(int(n_resamples), blocks))
    offsets = np.arange(interval)
    index = (starts[:, :, None] + offsets[None, None, :]) % n
    index = index.reshape(int(n_resamples), -1)[:, :n]
    statistics = np.empty(int(n_resamples), dtype=float)
    step = 256
    for begin in range(0, len(index), step):
        chunk = index[begin : begin + step]
        statistics[begin : begin + len(chunk)] = _annualized_sharpe_matrix(
            strategy_values[chunk], annualization=annualization
        ) - _annualized_sharpe_matrix(reference_values[chunk], annualization=annualization)
    observed_se = float(
        _jackknife_standard_error(
            strategy_values[None, :],
            reference_values[None, :],
            block_length=interval,
            annualization=annualization,
        )[0]
    )
    if not math.isfinite(observed_se) or observed_se <= 0.0:
        return {**result, "reason": "bootstrap_standard_error_unavailable"}
    # Studentize each resample by its own jackknife SE, then re-scale by the
    # observed SE: that is the bootstrap-t interval, whose measured coverage is
    # what backs the "95%" label (see the module docstring / calibration note).
    resampled_se = _jackknife_standard_error(
        strategy_values[index],
        reference_values[index],
        block_length=interval,
        annualization=annualization,
    )
    studentized = np.divide(
        statistics - value,
        resampled_se,
        out=np.full_like(statistics, np.nan),
        where=np.isfinite(resampled_se) & (resampled_se > 0.0),
    )
    studentized = studentized[np.isfinite(studentized)]
    if len(studentized) < 0.5 * int(n_resamples):
        return {**result, "reason": "bootstrap_standard_error_unavailable"}
    t_low, t_high = (float(item) for item in np.quantile(studentized, [0.025, 0.975]))
    return {
        **result,
        "status": "ready",
        "value": _f(value),
        "se": _f(observed_se),
        "ci95_low": _f(value - t_high * observed_se),
        "ci95_high": _f(value - t_low * observed_se),
        "fraction_bootstrap_positive": _f(float((statistics > 0).mean())),
        "studentized_quantiles": [_f(t_low), _f(t_high)],
        "studentized_resamples": int(len(studentized)),
    }


def active_return_block(
    strategy: pd.Series, reference: pd.Series, *, annualization: int = ANNUALIZATION
) -> dict:
    """Arithmetic daily active return plus its full-window geometric wealth ratio."""
    frame = _aligned(strategy, reference)
    n = len(frame)
    if not n:
        return {
            "daily_mean": None,
            "annualized": None,
            "cumulative_geometric": None,
            "n_observations": 0,
            "reason": "insufficient_observations",
        }
    active = frame["strategy"] - frame["reference"]
    daily_mean = float(active.mean())
    reference_growth = float((1.0 + frame["reference"]).prod())
    cumulative = None
    reason = None
    if reference_growth > 0:
        cumulative = float((1.0 + frame["strategy"]).prod()) / reference_growth - 1.0
    else:
        reason = "nonpositive_reference_growth"
    return {
        "daily_mean": _f(daily_mean),
        "annualized": _f(daily_mean * annualization),
        "cumulative_geometric": _f(cumulative),
        "n_observations": n,
        "reason": reason,
    }


def tracking_error(active: pd.Series, *, annualization: int = ANNUALIZATION) -> dict:
    """``ddof=0`` dispersion of the active series, annualized exactly like volatility."""
    values = _clean(active)
    if len(values) < 2:
        return {"daily": None, "annualized": None, "reason": "insufficient_observations"}
    std = float(values.std(ddof=0))
    if not math.isfinite(std):
        return {"daily": None, "annualized": None, "reason": "insufficient_observations"}
    return {
        "daily": _f(std),
        "annualized": _f(std * math.sqrt(annualization)),
        "reason": None,
    }


def information_ratio(
    active: pd.Series,
    *,
    annualization: int = ANNUALIZATION,
    min_observations: int = MIN_OBSERVATIONS,
) -> dict:
    """Active return per unit of tracking error, with a Newey-West t and an i.i.d. CI."""
    values = _clean(active)
    result: dict = {
        "value": None,
        "nw_t": None,
        "nw_lag": None,
        "se_iid": None,
        "ci95_low": None,
        "ci95_high": None,
        "reason": None,
    }
    n = len(values)
    if n < min_observations:
        return {**result, "reason": "insufficient_observations"}
    std = float(values.std(ddof=0))
    if not math.isfinite(std) or std <= _ZERO_VARIANCE:
        return {**result, "reason": "zero_tracking_error"}
    lag = newey_west_lag_rule(n, horizon=1)
    stats = newey_west_stats(values.to_numpy(dtype=float), lag=lag, horizon=1)
    ci = sharpe_se_ci(values, annualization=annualization, min_observations=min_observations)
    return {
        "value": _f(float(values.mean()) / std * math.sqrt(annualization)),
        "nw_t": _f(stats["t_stat"]),
        "nw_lag": int(lag),
        "se_iid": ci["se_iid"],
        "ci95_low": ci["ci95_low"],
        "ci95_high": ci["ci95_high"],
        "reason": None,
    }


def _rolling_alpha(
    frame: pd.DataFrame, *, window: int, min_periods: int, tz: Any = None
) -> tuple[list[dict], int]:
    """α(t) = mean_w(strategy) - β_t * mean_w(reference) on the 252/126 rolling window.

    Returns the labelled rows plus the number of *evaluated* windows that were
    dropped because the benchmark leg had zero variance over that window. Warm-up
    positions (fewer than ``min_periods`` observations) are not counted: they are
    the start of every series, not a degeneracy. The distinction matters because a
    flat benchmark makes β and α undefined, and the caller must say so instead of
    silently shortening the path.
    """
    reference, strategy = frame["reference"], frame["strategy"]

    def rolling(series: pd.Series) -> Any:
        return series.rolling(window, min_periods=min_periods)

    variance = rolling(reference).var()
    count = rolling(reference).count()
    beta_t = rolling(strategy).cov(reference) / variance
    alpha = rolling(strategy).mean() - beta_t * rolling(reference).mean()
    rows: list[dict] = []
    dropped = 0
    for day, value in alpha.items():
        number = _f(value)
        if number is not None:
            rows.append({"date": _iso(day, tz), "alpha": number})
            continue
        if pd.isna(count[day]):
            continue  # warm-up: the window has not reached min_periods yet
        dropped += 1  # evaluated window with a degenerate (flat) benchmark leg
    return rows, dropped


def beta_alpha(
    strategy: pd.Series,
    reference: pd.Series,
    *,
    annualization: int = ANNUALIZATION,
    window: int = BETA_WINDOW,
    min_periods: int = BETA_MIN_PERIODS,
    tz: Any = None,
) -> dict:
    """Full-sample OLS beta/alpha plus the rolling alpha path (scorecard conventions)."""
    base: dict = {
        "beta": None,
        "alpha_daily": None,
        "alpha_annualized": None,
        "alpha_nw_t": None,
        "alpha_nw_lag": None,
        "alpha_reason": None,
        "beta_estimation": "full_sample_ols",
        "window": int(window),
        "min_periods": int(min_periods),
        "beta_neutral_reason": None,
        "alpha_t": [],
        "alpha_t_windows": 0,
        "alpha_t_dropped_zero_variance": 0,
        "alpha_t_reason": None,
    }
    frame = _aligned(strategy, reference)
    n = len(frame)
    if n < 2:
        return {**base, "beta_neutral_reason": "insufficient_observations"}
    strategy_values = frame["strategy"].to_numpy(dtype=float)
    reference_values = frame["reference"].to_numpy(dtype=float)
    # A "constant" series still carries float rounding in its variance, so the
    # degeneracy test is on the dispersion, in the same units as every other guard.
    # Both legs are guarded: a constant strategy against a moving benchmark would
    # otherwise return a tidy beta=0.0 / alpha=0.0 that reads like a real hedge.
    reference_std = float(reference_values.std(ddof=0))
    strategy_std = float(strategy_values.std(ddof=0))
    variance = float(reference_values.var(ddof=0))
    if (
        not math.isfinite(reference_std)
        or reference_std <= _ZERO_VARIANCE
        or not math.isfinite(variance)
        or variance <= 0
    ):
        return {**base, "beta_neutral_reason": "zero_benchmark_variance"}
    if not math.isfinite(strategy_std) or strategy_std <= _ZERO_VARIANCE:
        return {**base, "beta_neutral_reason": "zero_strategy_variance"}
    mean_strategy = float(strategy_values.mean())
    mean_reference = float(reference_values.mean())
    covariance = float(
        ((strategy_values - mean_strategy) * (reference_values - mean_reference)).mean()
    )
    beta = covariance / variance
    alpha_daily = mean_strategy - beta * mean_reference
    lag = newey_west_lag_rule(n, horizon=1)
    stats = newey_west_stats(strategy_values - beta * reference_values, lag=lag, horizon=1)
    alpha_t, dropped = _rolling_alpha(frame, window=window, min_periods=min_periods, tz=tz)
    return {
        "beta": _f(beta),
        "alpha_daily": _f(alpha_daily),
        "alpha_annualized": _f(alpha_daily * annualization),
        "alpha_nw_t": _f(stats["t_stat"]),
        "alpha_nw_lag": int(lag),
        "alpha_reason": stats["reason"],
        "beta_estimation": "full_sample_ols",
        "window": int(window),
        "min_periods": int(min_periods),
        "beta_neutral_reason": None,
        "alpha_t": alpha_t,
        "alpha_t_windows": len(alpha_t) + dropped,
        "alpha_t_dropped_zero_variance": dropped,
        "alpha_t_reason": "alpha_windows_dropped_zero_variance" if dropped else None,
    }


def sharpe_se_ci(
    returns: pd.Series,
    *,
    annualization: int = ANNUALIZATION,
    min_observations: int = MIN_OBSERVATIONS,
) -> dict:
    """Lo (2002) i.i.d. standard error and 95% interval for an annualized Sharpe ratio."""
    result: dict = {
        "sharpe": None,
        "se_iid": None,
        "ci95_low": None,
        "ci95_high": None,
        "method": _SHARPE_METHOD,
        "reason": None,
    }
    values = _clean(returns)
    n = len(values)
    if n < min_observations:
        return {**result, "reason": "insufficient_observations"}
    std = float(values.std(ddof=0))
    if not math.isfinite(std) or std <= _ZERO_VARIANCE:
        return {**result, "reason": "zero_variance"}
    daily = float(values.mean()) / std
    daily_se = math.sqrt((1.0 + daily * daily / 2.0) / n)
    scale = math.sqrt(annualization)
    sharpe, se = daily * scale, scale * daily_se
    return {
        "sharpe": _f(sharpe),
        "se_iid": _f(se),
        "ci95_low": _f(sharpe - 1.96 * se),
        "ci95_high": _f(sharpe + 1.96 * se),
        "method": _SHARPE_METHOD,
        "reason": None,
    }


def _comparison_block(
    frame: pd.DataFrame,
    *,
    reference_kind: str,
    benchmark_symbol: str | None,
    annualization: int,
    bootstrap_seed: int,
    bootstrap_resamples: int,
    block_length: int,
    tz: Any = None,
) -> dict:
    strategy, reference = frame["strategy"], frame["reference"]
    active = strategy - reference
    hedge = beta_alpha(strategy, reference, annualization=annualization, tz=tz)
    return {
        "reference_kind": reference_kind,
        "benchmark_symbol": benchmark_symbol,
        "n_observations": len(frame),
        "reason": None,
        "active_return": active_return_block(strategy, reference, annualization=annualization),
        "tracking_error": tracking_error(active, annualization=annualization),
        "information_ratio": information_ratio(active, annualization=annualization),
        "beta_alpha": {key: value for key, value in hedge.items() if key != "alpha_t"},
        "alpha_t": hedge["alpha_t"],
        "sharpe_se_ci": sharpe_se_ci(strategy, annualization=annualization),
        "block_bootstrap": paired_block_bootstrap(
            strategy,
            reference,
            block_length=block_length,
            n_resamples=bootstrap_resamples,
            seed=bootstrap_seed,
            annualization=annualization,
        ),
    }


def _leg(curve: pd.DataFrame, column: str, index: pd.Index) -> pd.Series:
    values = pd.to_numeric(pd.Series(curve[column].to_numpy()), errors="coerce").astype("float64")
    values.index = index
    return values


def active_metrics(
    curve: pd.DataFrame,
    *,
    initial_cash: float,
    benchmark_symbol: str | None = None,
    annualization: int = ANNUALIZATION,
    include_peer: bool = True,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    block_length: int = BOOTSTRAP_BLOCK_LENGTH,
    timezone: Any = None,
) -> dict:
    """Active-return evidence for one assembled ``curve`` frame.

    ``curve`` is read-only and already session-aligned by the caller. The result
    is a self-describing sibling block: ``vs_benchmark`` (and ``vs_peer`` when the
    frame carries a ``peer`` column) hold the metric blocks, while the existing
    ``metrics``/``platform_metrics`` dictionaries are never touched.

    ``timezone`` is the reference timezone for the ``alpha_t`` date labels. It
    defaults to the input column's own timezone, so a session stamped
    ``2020-01-02T00:00+09:00`` keeps its trading day instead of being pulled back
    to the earlier UTC day; naive input labels in UTC exactly as before.
    """
    tz = timezone
    if isinstance(curve, pd.DataFrame) and "timestamp" in getattr(curve, "columns", []):
        tz = _label_timezone(curve["timestamp"], timezone)
    disclosure = {
        "evaluation_only": True,
        "dsr_family_member": False,
        "tradeable_claim": False,
        "benchmark_definition": _BENCHMARK_DEFINITION,
        "note": _DISCLOSURE_NOTE,
        "annualization_factor": int(annualization),
        "beta_window": BETA_WINDOW,
        "beta_min_periods": BETA_MIN_PERIODS,
        "min_observations": MIN_OBSERVATIONS,
        "min_bootstrap_observations": MIN_BOOTSTRAP_OBSERVATIONS,
        "bootstrap_block_length": int(block_length),
        "bootstrap_resamples": int(bootstrap_resamples),
        "bootstrap_seed": int(bootstrap_seed),
        "bootstrap_method": _BOOTSTRAP_METHOD,
        "bootstrap_nominal_coverage": _NOMINAL_COVERAGE,
        "bootstrap_measured_coverage": list(_MEASURED_COVERAGE),
        "bootstrap_studentization": _BOOTSTRAP_STUDENTIZATION,
        "lag_rule": _LAG_RULE,
        "rng": _RNG_DESCRIPTION,
        "timezone": str(tz) if tz is not None else None,
    }
    document: dict = {
        "schema_version": ACTIVE_METRICS_SCHEMA_VERSION,
        "status": "unavailable",
        "reason": None,
        "annualization_factor": int(annualization),
        "n_observations": 0,
        "sessions_dropped_missing_marks": 0,
        "start": None,
        "end": None,
        "disclosure": disclosure,
        "vs_benchmark": None,
        "vs_peer": None,
    }
    if not isinstance(curve, pd.DataFrame) or curve.empty:
        return {**document, "reason": "no_curve"}
    if not {"timestamp", "equity", "benchmark"}.issubset(curve.columns):
        return {**document, "reason": "active_metrics_missing_columns"}
    if include_peer and "peer" not in curve.columns:
        raise ValueError("active_metrics_peer_missing")
    try:
        timestamps = pd.to_datetime(curve["timestamp"], utc=True, errors="raise")
    except (ValueError, TypeError):
        return {**document, "reason": "active_metrics_timestamp_invalid"}
    if timestamps.isna().any():
        return {**document, "reason": "active_metrics_timestamp_invalid"}
    if bool(timestamps.duplicated().any()):
        raise ValueError("active_metrics_duplicate_timestamps")
    index = pd.DatetimeIndex(timestamps)
    strategy_returns = _daily_returns(_leg(curve, "equity", index), initial_cash)
    benchmark_returns = _daily_returns(_leg(curve, "benchmark", index), initial_cash)
    peer_returns = (
        _daily_returns(_leg(curve, "peer", index), initial_cash) if include_peer else None
    )
    benchmark_frame = _aligned(strategy_returns, benchmark_returns)
    document["n_observations"] = len(benchmark_frame)
    # "missing marks" means every leg the document publishes comparisons for: a
    # peer-leg gap shrinks the peer comparison too and must not read as zero.
    dropped_mask = strategy_returns.isna() | benchmark_returns.isna()
    if peer_returns is not None:
        dropped_mask = dropped_mask | peer_returns.isna()
    document["sessions_dropped_missing_marks"] = int(dropped_mask.sum())
    if len(benchmark_frame):
        document["start"] = _iso(benchmark_frame.index[0], tz)
        document["end"] = _iso(benchmark_frame.index[-1], tz)
    if len(benchmark_frame) < 2:
        return {**document, "reason": "insufficient_observations"}
    document["status"] = "ready"
    document["vs_benchmark"] = _comparison_block(
        benchmark_frame,
        reference_kind="benchmark",
        benchmark_symbol=benchmark_symbol,
        annualization=annualization,
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
        block_length=block_length,
        tz=tz,
    )
    if include_peer:
        peer_frame = _aligned(strategy_returns, peer_returns)
        document["vs_peer"] = _comparison_block(
            peer_frame,
            reference_kind="peer",
            benchmark_symbol="peer",
            annualization=annualization,
            bootstrap_seed=bootstrap_seed,
            bootstrap_resamples=bootstrap_resamples,
            block_length=block_length,
            tz=tz,
        )
    return document


def sleeve_active_metrics(
    observation_series: Any,
    *,
    benchmark_symbol: str = "SPY",
    unavailable_reason: str | None = None,
    annualization: int = ANNUALIZATION,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    block_length: int = BOOTSTRAP_BLOCK_LENGTH,
    timezone: Any = None,
) -> dict:
    """Active-return evidence for a paper sleeve's observed net-value leg vs SPY.

    The input is the sleeve evaluation's ``observation_series`` rows -- one per
    valued session, each carrying ``date``, ``sleeve_equity`` (the sleeve NAV leg)
    and ``spy_close`` (the SPY leg). Both legs are per-observation-day real
    marks, so a paired return series exists whenever the journal valued the
    sleeve; there is no "no continuous daily NAV" blocker, and any missing day is
    dropped pairwise by the shared alignment rather than fabricated.

    ``unavailable_reason`` short-circuits the computation for callers that
    already know the aggregate is not interpretable (e.g. capital was injected
    mid-window, so NAV ratios mix funding with performance); it is returned as a
    normal unavailable document instead of a number that reads like alpha.
    """
    rows = list(observation_series or [])
    # Resolve the label timezone from the data before any early return, so an
    # unavailable document carries the same disclosure value as a ready one.
    resolved_tz = timezone
    if rows:
        resolved_tz = _label_timezone(
            pd.Series([row.get("date") for row in rows]), timezone
        )
    if unavailable_reason is not None:
        return {
            "schema_version": ACTIVE_METRICS_SCHEMA_VERSION,
            "status": "unavailable",
            "reason": unavailable_reason,
            "annualization_factor": int(annualization),
            "n_observations": 0,
            "sessions_dropped_missing_marks": 0,
            "start": None,
            "end": None,
            "disclosure": {
                "evaluation_only": True,
                "dsr_family_member": False,
                "tradeable_claim": False,
                "benchmark_definition": _BENCHMARK_DEFINITION,
                "note": _DISCLOSURE_NOTE,
                "annualization_factor": int(annualization),
                "beta_window": BETA_WINDOW,
                "beta_min_periods": BETA_MIN_PERIODS,
                "min_observations": MIN_OBSERVATIONS,
                "min_bootstrap_observations": MIN_BOOTSTRAP_OBSERVATIONS,
                "bootstrap_block_length": int(block_length),
                "bootstrap_resamples": int(bootstrap_resamples),
                "bootstrap_seed": int(bootstrap_seed),
                "bootstrap_method": _BOOTSTRAP_METHOD,
                "bootstrap_nominal_coverage": _NOMINAL_COVERAGE,
                "bootstrap_measured_coverage": list(_MEASURED_COVERAGE),
                "bootstrap_studentization": _BOOTSTRAP_STUDENTIZATION,
                "lag_rule": _LAG_RULE,
                "rng": _RNG_DESCRIPTION,
                "timezone": str(resolved_tz) if resolved_tz is not None else None,
            },
            "vs_benchmark": None,
            "vs_peer": None,
        }
    rows = list(observation_series or [])
    if not rows:
        return sleeve_active_metrics(
            [], benchmark_symbol=benchmark_symbol,
            unavailable_reason="no_sleeve_observations",
            annualization=annualization, bootstrap_seed=bootstrap_seed,
            bootstrap_resamples=bootstrap_resamples, block_length=block_length,
            timezone=timezone,
        )
    curve = pd.DataFrame(
        {
            "timestamp": [row.get("date") for row in rows],
            "equity": [row.get("sleeve_equity") for row in rows],
            "benchmark": [row.get("spy_close") for row in rows],
        }
    )
    # The sleeve NAV and the SPY close are on different scales, and the shared
    # ``initial_cash`` funds BOTH legs' first session, so each leg is rebased to
    # its own first valued mark. Returns (and every metric derived from them) are
    # scale-invariant, so this changes nothing except removing a spurious
    # first-session jump in one leg.
    for column in ("equity", "benchmark"):
        values = pd.to_numeric(curve[column], errors="coerce")
        positive = values[values > 0]
        if len(positive):
            curve[column] = values / float(positive.iloc[0])
    # The journal values the sleeve NAV per session; a sparse series (weekly or
    # event-driven marks) would be annualized as if daily, inflating TE and the
    # block bootstrap. Fail by name instead of publishing the inflated number.
    stamps = (
        pd.to_datetime(curve["timestamp"], utc=True, errors="coerce")
        .dropna()
        .drop_duplicates()
        .sort_values()
    )
    spacing_days = (
        stamps.diff().dt.days.dropna() if len(stamps) >= 2 else pd.Series(dtype="float64")
    )
    if len(spacing_days):
        # A non-session cadence (median > 1 day) or a long hole inside an
        # otherwise dense series would be annualized as if one session per
        # return; both are rejected by name instead of publishing the inflated
        # number. Holiday weeks (5 sessions) stay below the hole bound.
        if float(spacing_days.median()) > 1.0:
            return sleeve_active_metrics(
                [],
                benchmark_symbol=benchmark_symbol,
                unavailable_reason="sparse_sleeve_observation_series",
                annualization=annualization,
                bootstrap_seed=bootstrap_seed,
                bootstrap_resamples=bootstrap_resamples,
                block_length=block_length,
                timezone=resolved_tz,
            )
        if float(spacing_days.max()) > _MAX_SLEEVE_GAP_DAYS:
            return sleeve_active_metrics(
                [],
                benchmark_symbol=benchmark_symbol,
                unavailable_reason="gap_in_sleeve_observation_series",
                annualization=annualization,
                bootstrap_seed=bootstrap_seed,
                bootstrap_resamples=bootstrap_resamples,
                block_length=block_length,
                timezone=resolved_tz,
            )
    document = active_metrics(
        curve,
        initial_cash=1.0,
        benchmark_symbol=benchmark_symbol,
        include_peer=False,
        annualization=annualization,
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
        block_length=block_length,
        timezone=resolved_tz,
    )
    document["max_observation_gap_days"] = (
        int(float(spacing_days.max())) if len(spacing_days) else 0
    )
    return document
