"""Pure factor scorecard builder: evaluation-only indicators, gross of costs.

Everything here is a function of supplied frames; there is no I/O, no provider call and
no trial accounting (the service layer owns persistence and the DSR-family tombstone).
Missing measurements are represented as ``None`` with a ``status``/``reason``; the
returned dictionary is JSON-serialisable with ``allow_nan=False``.

Cost note: no 1bp/5bp constant is referenced here. The long/short leg assumes frictionless
shorting; the frozen cost constants live in the reference backtests only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_system.factors import evaluation as evaluation_module
from quant_system.factors.evaluation import (
    FORWARD_RETURN_SCHEMA_VERSION,
    METHODOLOGY_VERSION,
    PriceBasis,
    build_price_frame,
    newey_west_lag_rule,
    newey_west_stats,
    prepare_evaluation_frames,
    summarize_ic_series,
)

SCORECARD_SCHEMA_VERSION = "factor_scorecard_v1"
BETA_WINDOW = 252
BETA_MIN_PERIODS = 126
CORRELATION_MIN_SYMBOLS = 5
CORRELATION_MIN_DAYS = 20
MARGINAL_MIN_FULL_SAMPLE = 126
MARGINAL_MIN_SHARED_DAYS = 20
DETECTABLE_SHARPE_CONSTANT = 2.80158
SLEEVE_UNAVAILABLE_REASON = "sleeve_returns_not_provided"
LIBRARY_VALUES_UNAVAILABLE_REASON = "library_factor_values_unavailable"
_SHORT_ASSUMPTION = (
    "做空腿假设无摩擦卖空（无 borrow/可得性/RegSHO）；1bp+5bp 冻结常量仅属 reference_backtests"
)


def _direction_sign(direction: str | None) -> float:
    return -1.0 if direction == "lower_is_better" else 1.0


def _spearman(left: pd.Series, right: pd.Series) -> float:
    return left.rank(method="average").corr(right.rank(method="average"), method="pearson")


def _series_summary(values: pd.Series, rank_values: pd.Series, *, horizon: int) -> dict:
    frame = pd.DataFrame({"ic": values, "rank_ic": rank_values})
    return summarize_ic_series(frame, horizon=horizon)


def _last_observed_dates(prices) -> pd.Series:
    observed = prices.observed_mask
    days = {
        column: (
            observed.index[observed[column].to_numpy()][-1] if observed[column].any() else pd.NaT
        )
        for column in observed.columns
    }
    return pd.Series(days)


# --------------------------------------------------------------------------------------
# Information coefficient
# --------------------------------------------------------------------------------------


def _daily_ic_block(
    frame: pd.DataFrame, *, factor_id: str, horizon: int, price_basis: str,
    inference_horizon: int | None = None,
) -> tuple[pd.DataFrame, dict]:
    rows: list[dict[str, Any]] = []
    for signal_ts, group in frame.groupby("signal_ts", sort=True):
        clean = group.dropna(subset=["value", "forward_return"])
        n = len(clean)
        ic = float("nan")
        rank_ic = float("nan")
        if n >= 2 and clean["value"].nunique() > 1 and clean["forward_return"].nunique() > 1:
            ic = clean["value"].corr(clean["forward_return"], method="pearson")
            rank_ic = _spearman(clean["value"], clean["forward_return"])
        rows.append(
            {
                "factor_id": factor_id,
                "signal_ts": signal_ts,
                "horizon": horizon,
                "price_basis": price_basis,
                "ic": ic,
                "rank_ic": rank_ic,
                "n": n,
            }
        )
    daily = pd.DataFrame(
        rows, columns=["factor_id", "signal_ts", "horizon", "price_basis", "ic", "rank_ic", "n"]
    )
    summary = summarize_ic_series(daily, horizon=inference_horizon or horizon)
    summary["status"] = "ready" if summary["n_days"] else "unavailable"
    if not summary["n_days"]:
        summary["reason"] = summary["reason"] or "no_cross_sectional_days"
    return daily, summary


def _rolling_betas(
    closes: pd.DataFrame,
    benchmark: pd.Series,
    *,
    window: int = BETA_WINDOW,
    min_periods: int = BETA_MIN_PERIODS,
) -> pd.DataFrame:
    returns = closes.pct_change(fill_method=None)
    bench = benchmark.pct_change(fill_method=None)
    data = {
        symbol: returns[symbol].rolling(window, min_periods=min_periods).cov(bench)
        / bench.where(returns[symbol].notna()).rolling(window, min_periods=min_periods).var()
        for symbol in returns.columns
    }
    return pd.DataFrame(data, index=returns.index)


def _benchmark_label(series: pd.Series, horizon: int) -> pd.Series:
    return series.shift(-(horizon + 1)) / series.shift(-1) - 1.0


def _residual_ic_block(
    frame: pd.DataFrame,
    *,
    factor_id: str,
    horizon: int,
    betas: pd.DataFrame | None,
    benchmark_labels: pd.Series | None,
    benchmark_symbol: str,
    close_available: bool,
    inference_horizon: int | None = None,
) -> tuple[pd.DataFrame, dict]:
    daily_columns = [
        "factor_id",
        "signal_ts",
        "horizon",
        "residual_ic",
        "residual_rank_ic",
        "residual_n",
    ]
    disclosure = {
        "beta_estimation": "rolling_252d_min126_pit",
        "beta_window": BETA_WINDOW,
        "beta_min_periods": BETA_MIN_PERIODS,
        "benchmark_symbol": benchmark_symbol,
        "note": "β 按信号日 t 之前 252 个并集日历日（min 126）滚动 OLS 估计，信息截止 t 收盘；"
        "残差假设 h 日内 β 恒定。",
    }
    if not close_available:
        return (
            pd.DataFrame(columns=daily_columns),
            {"status": "close_prices_missing", "reason": "close_prices_missing", **disclosure},
        )
    if betas is None or benchmark_labels is None:
        return (
            pd.DataFrame(columns=daily_columns),
            {"status": "benchmark_missing", "reason": "benchmark_symbol_absent", **disclosure},
        )

    # The per-day loop below reads ``residual`` with the labels of each group as
    # positions, so the frame must carry a positional index: callers hand over
    # ``subset`` frames whose labels come from the merged frame and stay
    # non-contiguous once more than one factor row set is present.
    frame = frame.reset_index(drop=True)
    beta_series = betas.stack(future_stack=True)
    beta_series.index.names = ["signal_ts", "symbol"]
    lookup = pd.MultiIndex.from_arrays([frame["signal_ts"], frame["symbol"]])
    beta_values = beta_series.reindex(lookup).to_numpy()
    benchmark_return = frame["signal_ts"].map(benchmark_labels).to_numpy()
    residual = frame["forward_return"].to_numpy() - beta_values * benchmark_return

    has_beta = np.isfinite(beta_values) & np.isfinite(benchmark_return)
    labelled = frame["value"].notna() & frame["forward_return"].notna()
    excluded_no_beta = int((labelled & ~has_beta).sum())

    rows: list[dict[str, Any]] = []
    for signal_ts, group in frame.groupby("signal_ts", sort=True):
        positions = group.index.to_numpy()
        clean = pd.DataFrame(
            {"value": group["value"].to_numpy(), "residual": residual[positions]}
        ).dropna()
        n = len(clean)
        residual_ic = float("nan")
        residual_rank_ic = float("nan")
        if n >= 2 and clean["value"].nunique() > 1 and clean["residual"].nunique() > 1:
            residual_ic = clean["value"].corr(clean["residual"], method="pearson")
            residual_rank_ic = _spearman(clean["value"], clean["residual"])
        rows.append(
            {
                "factor_id": factor_id,
                "signal_ts": signal_ts,
                "horizon": horizon,
                "residual_ic": residual_ic,
                "residual_rank_ic": residual_rank_ic,
                "residual_n": n,
            }
        )
    daily = pd.DataFrame(rows, columns=daily_columns)
    summary = _series_summary(
        daily["residual_ic"], daily["residual_rank_ic"], horizon=inference_horizon or horizon
    )
    summary["status"] = "ready" if summary["n_days"] else "unavailable"
    if not summary["n_days"]:
        summary["reason"] = summary["reason"] or "no_cross_sectional_days"
    summary["excluded_no_beta"] = excluded_no_beta
    return daily, {**summary, **disclosure}


# --------------------------------------------------------------------------------------
# Quantiles, long/short spread and turnover
# --------------------------------------------------------------------------------------


def _bucket_turnover(
    members: dict[pd.Timestamp, dict[int, set[str]]], quantiles: int, calendar: pd.DatetimeIndex
) -> dict:
    dates = sorted(members)
    if len(dates) < 2:
        return {
            "cadence": "insufficient_signal_days",
            "n_steps": 0,
            "turnover_per_step": None,
            "turnover_annualized": None,
        }
    positions = {day: index for index, day in enumerate(calendar)}
    gaps = [
        positions[dates[index + 1]] - positions[dates[index]] for index in range(len(dates) - 1)
    ]
    cadence = "irregular" if float(np.median(gaps)) > 3 else "regular"
    span_years = (dates[-1] - dates[0]).total_seconds() / (365.25 * 86_400)
    per_bucket: dict[int, float] = {}
    per_bucket_annualized: dict[int, float | None] = {}
    for bucket in range(1, quantiles + 1):
        steps: list[float] = []
        for previous_day, day in zip(dates, dates[1:], strict=False):
            previous = members[previous_day][bucket]
            current = members[day][bucket]
            weight_previous = 1.0 / len(previous) if previous else 0.0
            weight_current = 1.0 / len(current) if current else 0.0
            union = previous | current
            step = 0.5 * sum(
                abs(
                    (weight_current if symbol in current else 0.0)
                    - (weight_previous if symbol in previous else 0.0)
                )
                for symbol in union
            )
            steps.append(step)
        per_bucket[bucket] = float(np.mean(steps)) if steps else 0.0
        annualized = None
        if cadence == "regular" and span_years > 0 and steps:
            annualized = float(np.mean(steps) * len(steps) / span_years)
        per_bucket_annualized[bucket] = annualized
    mean_step = float(np.mean(list(per_bucket.values()))) if per_bucket else None
    mean_annualized = None
    if cadence == "regular" and span_years > 0 and per_bucket_annualized:
        values = [value for value in per_bucket_annualized.values() if value is not None]
        mean_annualized = float(np.mean(values)) if values else None
    return {
        "cadence": cadence,
        "n_steps": len(dates) - 1,
        "turnover_per_step": {
            "top": per_bucket.get(quantiles),
            "bottom": per_bucket.get(1),
            "mean": mean_step,
        },
        "turnover_annualized": {
            "top": per_bucket_annualized.get(quantiles),
            "bottom": per_bucket_annualized.get(1),
            "mean": mean_annualized,
        },
    }


def _quantile_ls_block(
    frame: pd.DataFrame,
    *,
    factor_id: str,
    direction: str | None,
    horizon: int,
    quantiles: int,
    benchmark_labels: pd.Series | None,
    calendar: pd.DatetimeIndex,
    inference_horizon: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict, pd.Series]:
    quantile_daily = pd.DataFrame(
        columns=[
            "factor_id",
            "signal_ts",
            "horizon",
            "quantile",
            "mean_forward_return_raw",
            "mean_forward_return_adjusted",
            "count",
        ]
    )
    long_short_daily = pd.DataFrame(
        columns=[
            "factor_id",
            "signal_ts",
            "horizon",
            "spread",
            "spread_adjusted",
            "benchmark_return",
        ]
    )
    sign = _direction_sign(direction)
    minimum_rows = 2 * quantiles
    quantile_rows: list[dict[str, Any]] = []
    long_short_rows: list[dict[str, Any]] = []
    members: dict[pd.Timestamp, dict[int, set[str]]] = {}
    skipped_thin_days = 0
    for signal_ts, group in frame.groupby("signal_ts", sort=True):
        clean = group.dropna(subset=["value", "forward_return"]).copy()
        if len(clean) < minimum_rows or clean["value"].nunique() < 2:
            skipped_thin_days += 1
            continue
        clean["quantile"] = pd.qcut(
            clean["value"].rank(method="first"),
            q=quantiles,
            labels=range(1, quantiles + 1),
        ).astype(int)
        means = clean.groupby("quantile")["forward_return"].mean()
        if len(means) < quantiles:
            skipped_thin_days += 1
            continue
        for bucket in range(1, quantiles + 1):
            quantile_rows.append(
                {
                    "factor_id": factor_id,
                    "signal_ts": signal_ts,
                    "horizon": horizon,
                    "quantile": bucket,
                    "mean_forward_return_raw": float(means[bucket]),
                    "mean_forward_return_adjusted": float(means[bucket]) * sign,
                    "count": int((clean["quantile"] == bucket).sum()),
                }
            )
        spread = float(means[quantiles] - means[1])
        benchmark_return = None
        if benchmark_labels is not None:
            candidate = benchmark_labels.get(signal_ts)
            if candidate is not None and pd.notna(candidate):
                benchmark_return = float(candidate)
        long_short_rows.append(
            {
                "factor_id": factor_id,
                "signal_ts": signal_ts,
                "horizon": horizon,
                "spread": spread,
                "spread_adjusted": spread * sign,
                "benchmark_return": benchmark_return,
            }
        )
        members[signal_ts] = {
            bucket: set(clean.loc[clean["quantile"] == bucket, "symbol"])
            for bucket in range(1, quantiles + 1)
        }

    if quantile_rows:
        quantile_daily = pd.DataFrame(quantile_rows)
        long_short_daily = pd.DataFrame(long_short_rows)
    adjusted = (
        long_short_daily.set_index("signal_ts")["spread_adjusted"].sort_index()
        if not long_short_daily.empty
        else pd.Series(dtype="float64")
    )
    raw = (
        long_short_daily.set_index("signal_ts")["spread"].sort_index()
        if not long_short_daily.empty
        else pd.Series(dtype="float64")
    )
    n_days = int(len(adjusted))
    bucket_means_raw = (
        quantile_daily.groupby("quantile")["mean_forward_return_raw"].mean().sort_index()
        if not quantile_daily.empty
        else pd.Series(dtype="float64")
    )
    bucket_means_adjusted = (
        quantile_daily.groupby("quantile")["mean_forward_return_adjusted"].mean().sort_index()
        if not quantile_daily.empty
        else pd.Series(dtype="float64")
    )
    monotonic = None
    if len(bucket_means_adjusted) == quantiles:
        diffs = np.diff(bucket_means_adjusted.to_numpy())
        monotonic = bool((diffs > 0).all() or (diffs < 0).all())
    lag = newey_west_lag_rule(n_days, horizon=inference_horizon or horizon)
    stats = newey_west_stats(adjusted.to_numpy(), lag=lag, horizon=inference_horizon or horizon)
    turnover = _bucket_turnover(members, quantiles, calendar)
    block = {
        "status": "ready" if n_days else "unavailable",
        "reason": None if n_days else "no_cross_sectional_days",
        "quantiles": quantiles,
        "minimum_rows_per_day": minimum_rows,
        "quantile_means": [float(value) for value in bucket_means_raw],
        "quantile_means_adjusted": [float(value) for value in bucket_means_adjusted],
        "quantile_monotonic": monotonic,
        # Each observation spans h sessions even when a signal is issued daily.
        # Express its arithmetic spread per session before annualizing.
        "spread_mean_daily": float(adjusted.mean() / horizon) if n_days else None,
        "spread_mean_daily_raw": float(raw.mean() / horizon) if n_days else None,
        "spread_annualized": float(adjusted.mean() * (252 / horizon)) if n_days else None,
        "spread_t_nw": stats["t_stat"],
        "spread_nw_lag": lag,
        "spread_nw_reason": stats["reason"],
        "n_days": n_days,
        "skipped_thin_days": skipped_thin_days,
        "turnover": turnover,
        "evaluation_only": True,
        "tradeable_claim": False,
        "short_assumption": _SHORT_ASSUMPTION,
    }
    return quantile_daily, long_short_daily, block, adjusted


def long_short_beta_hedge(
    spread: pd.Series,
    benchmark: pd.Series,
    *,
    horizon: int = 1,
    min_days: int = 60,
    nw_min_observations: int | None = None,
    nw_min_pairs: int = 30,
    inference_horizon: int | None = None,
) -> dict:
    """Full-sample OLS hedge of the long/short spread against the benchmark window return.

    ``hedged = spread - beta_hat * benchmark``; the mean of ``hedged`` is ``alpha_hat``.
    Published with a look-ahead disclosure (in-sample hedge). Guardrails are parameters so
    that sealed test vectors can bypass the sample-size floor explicitly.
    """
    disclosure = {
        "beta_estimation": "full_sample_ols",
        "min_days": min_days,
        "note": "全样本 OLS 对冲（样本内，轻度前视）；hedged 均值即 alpha_hat，不重复减 alpha。",
    }
    aligned = pd.DataFrame({"spread": spread, "benchmark": benchmark}).dropna()
    n_days = int(len(aligned))
    empty: dict[str, Any] = {
        "status": "unavailable",
        "beta": None,
        "alpha_annualized": None,
        "beta_neutral_spread_annualized": None,
        "beta_neutral_t": None,
        "n_days": n_days,
        **disclosure,
    }
    if n_days < min_days:
        return {**empty, "reason": "insufficient_days"}
    variance = float(aligned["benchmark"].var(ddof=0))
    if not math.isfinite(variance) or variance <= 0:
        return {**empty, "reason": "zero_benchmark_variance"}
    mean_spread = float(aligned["spread"].mean())
    mean_benchmark = float(aligned["benchmark"].mean())
    covariance = float(
        ((aligned["spread"] - mean_spread) * (aligned["benchmark"] - mean_benchmark)).mean()
    )
    beta = covariance / variance
    alpha = mean_spread - beta * mean_benchmark
    hedged = aligned["spread"] - beta * aligned["benchmark"]
    lag = newey_west_lag_rule(n_days, horizon=inference_horizon or horizon)
    stats = newey_west_stats(
        hedged.to_numpy(),
        lag=lag,
        horizon=inference_horizon or horizon,
        min_observations=nw_min_observations,
        min_pairs=nw_min_pairs,
    )
    return {
        "status": "ready",
        "beta": float(beta),
        "alpha_annualized": float(alpha * (252 / horizon)),
        "beta_neutral_spread_annualized": float(hedged.mean() * (252 / horizon)),
        "beta_neutral_t": stats["t_stat"],
        "beta_neutral_nw_lag": lag,
        "beta_neutral_reason": stats["reason"],
        "n_days": n_days,
        **disclosure,
    }


# --------------------------------------------------------------------------------------
# Sleeve marginal contribution
# --------------------------------------------------------------------------------------


def sleeve_marginal_contribution(
    candidate_spread: pd.Series,
    sleeve_returns: Mapping[str, float] | Sequence[float] | pd.Series | None,
    *,
    min_full_sample: int = MARGINAL_MIN_FULL_SAMPLE,
    min_shared_days: int = MARGINAL_MIN_SHARED_DAYS,
    horizon: int = 1,
) -> dict:
    """Point estimate plus paired-difference NW inference for adding the candidate leg.

    Never emits a binary significance verdict; the power figures say how long a sample
    would be needed to detect the observed difference.

    ``sleeve_returns`` is the documented ``date -> daily return`` mapping. A
    ``pd.Series`` is accepted as the idiomatic pandas spelling of that mapping and is
    keyed by *its own index*; a positional reading would silently drop every shared day
    (the candidate leg is date-indexed), so it is never assumed.
    """
    base: dict[str, Any] = {
        "status": "unavailable",
        "marginal_sharpe_delta": None,
        "sleeve_portfolio_correlation": None,
        "n_shared_days": 0,
        "paired_difference": None,
        "evaluation_only": True,
        "tradeable_claim": False,
    }
    if sleeve_returns is None:
        return {**base, "reason": SLEEVE_UNAVAILABLE_REASON}
    if isinstance(sleeve_returns, (pd.Series, Mapping)):
        # A Series is keyed by its own index (mirroring the Mapping contract); reading it
        # positionally would silently drop every shared day, since the candidate leg is
        # date-indexed. A non-date index therefore falls through to insufficient_shared_days.
        sleeve = pd.Series(
            {str(day)[:10]: float(value) for day, value in sleeve_returns.items()}, dtype="float64"
        )
    else:
        sleeve = pd.Series([float(value) for value in sleeve_returns], dtype="float64")
    candidate = pd.Series(candidate_spread, dtype="float64")
    candidate.index = pd.Index([str(day)[:10] for day in candidate.index])
    sleeve.index = pd.Index([str(day)[:10] for day in sleeve.index])
    aligned = pd.DataFrame({"candidate": candidate, "sleeve": sleeve}).dropna()
    n_shared = int(len(aligned))
    if n_shared < 2:
        return {**base, "n_shared_days": n_shared, "reason": "insufficient_shared_days"}

    without = aligned["sleeve"]
    with_candidate = 0.5 * (aligned["sleeve"] + aligned["candidate"])
    difference = with_candidate - without

    def _sharpe(values: pd.Series) -> float:
        std = float(values.std(ddof=0))
        if not math.isfinite(std) or std == 0:
            return 0.0
        return float(values.mean() / std * math.sqrt(252))

    delta = _sharpe(with_candidate) - _sharpe(without)
    from quant_system.research.trials import date_aligned_correlation  # noqa: PLC0415

    correlation = date_aligned_correlation(
        aligned["candidate"].tolist(),
        [str(day) for day in aligned.index],
        aligned["sleeve"].tolist(),
        [str(day) for day in aligned.index],
    )
    result: dict[str, Any] = {
        "status": "insufficient_sample_descriptive_only",
        "reason": (
            "insufficient_shared_days"
            if n_shared < min_shared_days
            else "insufficient_sample_for_inference"
        ),
        "marginal_sharpe_delta": float(delta),
        "sharpe_with": _sharpe(with_candidate),
        "sharpe_without": _sharpe(without),
        "sleeve_portfolio_correlation": correlation,
        "n_shared_days": n_shared,
        "paired_difference": None,
        "evaluation_only": True,
        "tradeable_claim": False,
        "note": "候选腿 = h=1 方向调整多空价差日序列；CI/功效需 T >= 126，永不输出二元显著性裁决。",
    }
    if n_shared < min_full_sample:
        return result

    mean_difference = float(difference.mean())
    lag = newey_west_lag_rule(n_shared, horizon=horizon)
    stats = newey_west_stats(difference.to_numpy(), lag=lag, horizon=horizon)
    lrv = stats["lrv"]
    gamma_0 = stats["gamma_0"]
    ci95 = None
    if lrv is not None and math.isfinite(float(lrv)) and float(lrv) > 0:
        half_width = 1.96 * math.sqrt(float(lrv) / n_shared)
        ci95 = [mean_difference - half_width, mean_difference + half_width]
    detectable = None
    if gamma_0 is not None and lrv is not None and float(gamma_0) > 0 and float(lrv) > 0:
        kappa = float(lrv) / float(gamma_0)
        if kappa > 0:
            detectable = float(
                DETECTABLE_SHARPE_CONSTANT * math.sqrt(252.0 / n_shared) * math.sqrt(kappa)
            )
    required_years = None
    if mean_difference > 0 and lrv is not None and float(lrv) > 0:
        required_years = float(
            (DETECTABLE_SHARPE_CONSTANT / (mean_difference / math.sqrt(float(lrv)))) ** 2 / 252.0
        )
    result["status"] = "ready"
    result["reason"] = None
    result["paired_difference"] = {
        "mean_d": mean_difference,
        "nw_t": stats["t_stat"],
        "nw_lag": lag,
        "ci95": ci95,
        "fraction_positive": float((difference > 0).mean()),
        "detectable_annualized_delta_sharpe": detectable,
        "required_years": required_years,
        "detectable_sharpe_constant": DETECTABLE_SHARPE_CONSTANT,
    }
    return result


# --------------------------------------------------------------------------------------
# Library correlation
# --------------------------------------------------------------------------------------


def _correlation_block(
    candidate_frame: pd.DataFrame,
    library_frame: pd.DataFrame | None,
    *,
    factor_id: str,
    min_symbols: int = CORRELATION_MIN_SYMBOLS,
    min_days: int = CORRELATION_MIN_DAYS,
) -> tuple[pd.DataFrame, dict]:
    columns = ["factor_id", "peer_factor_id", "signal_ts", "corr", "n"]
    empty: dict[str, Any] = {
        "status": "unavailable",
        "max_abs_factor_correlation": None,
        "max_correlation_factor_id": None,
        "mean_abs_correlation": None,
        "n_peers": 0,
        "peers": [],
        "note": "值空间相关仅作 advisory 提示；与收益空间组合层的冻结相关闸门统计对象不同。",
    }
    if library_frame is None:
        return pd.DataFrame(columns=columns), {
            **empty,
            "reason": "library_factor_results_not_provided",
        }
    required_columns = {"factor_id", "symbol", "signal_ts", "value"}
    if library_frame.empty or not required_columns.issubset(library_frame.columns):
        # The service injects the registry default set; when those values are not
        # obtainable on this panel the reason is stated explicitly rather than left as a
        # bare "unavailable".
        return pd.DataFrame(columns=columns), {
            **empty,
            "reason": LIBRARY_VALUES_UNAVAILABLE_REASON,
        }

    library = library_frame.copy()
    library["symbol"] = library["symbol"].astype(str).str.upper().str.strip()
    library["signal_ts"] = pd.to_datetime(library["signal_ts"], utc=True)
    library["value"] = pd.to_numeric(library["value"], errors="coerce")
    candidate = candidate_frame.loc[:, ["symbol", "signal_ts", "value"]].copy()
    peer_ids = sorted(set(library["factor_id"].astype(str)) - {factor_id})
    daily_rows: list[dict[str, Any]] = []
    peers: list[dict[str, Any]] = []
    for peer_id in peer_ids:
        peer = library[library["factor_id"].astype(str) == peer_id]
        merged = candidate.merge(
            peer.loc[:, ["symbol", "signal_ts", "value"]],
            on=["symbol", "signal_ts"],
            how="inner",
            suffixes=("_candidate", "_peer"),
        )
        correlations: list[float] = []
        for signal_ts, group in merged.groupby("signal_ts", sort=True):
            clean = group.dropna(subset=["value_candidate", "value_peer"])
            if len(clean) < min_symbols:
                continue
            if clean["value_candidate"].nunique() < 2 or clean["value_peer"].nunique() < 2:
                continue
            value = _spearman(clean["value_candidate"], clean["value_peer"])
            if pd.isna(value):
                continue
            correlations.append(float(value))
            daily_rows.append(
                {
                    "factor_id": factor_id,
                    "peer_factor_id": peer_id,
                    "signal_ts": signal_ts,
                    "corr": float(value),
                    "n": len(clean),
                }
            )
        if len(correlations) < min_days:
            peers.append(
                {
                    "peer_factor_id": peer_id,
                    "status": "skipped",
                    "reason": "insufficient_shared_days",
                    "n_days": len(correlations),
                }
            )
            continue
        values = np.asarray(correlations, dtype="float64")
        peers.append(
            {
                "peer_factor_id": peer_id,
                "status": "ready",
                "mean_corr": float(values.mean()),
                "mean_abs_corr": float(np.abs(values).mean()),
                "p90_abs_corr": float(np.percentile(np.abs(values), 90)),
                "n_days": int(len(values)),
            }
        )
    daily = pd.DataFrame(daily_rows, columns=columns)
    ready = [peer for peer in peers if peer["status"] == "ready"]
    if not ready:
        return daily, {**empty, "reason": "no_peer_with_sufficient_overlap", "peers": peers}
    best = max(ready, key=lambda peer: peer["mean_abs_corr"])
    block = {
        "status": "ready",
        "max_abs_factor_correlation": float(best["mean_abs_corr"]),
        "max_correlation_factor_id": best["peer_factor_id"],
        "mean_abs_correlation": float(np.mean([peer["mean_abs_corr"] for peer in ready])),
        "n_peers": len(ready),
        "peers": peers,
        "note": "值空间相关仅作 advisory 提示；与收益空间组合层的冻结相关闸门统计对象不同。",
    }
    return daily, block


# --------------------------------------------------------------------------------------
# Coverage audit
# --------------------------------------------------------------------------------------


def _coverage_block(frame: pd.DataFrame) -> dict:
    n_signals = int(len(frame))
    value_missing = int(frame["value"].isna().sum())
    valid = frame["value"].notna() & frame["forward_return"].notna()
    n_valid = int(valid.sum())
    labelled = frame["value"].notna() & frame["forward_return"].isna()
    reasons = frame.loc[labelled, "exclusion_reason"].fillna("invalid_price")
    entry = int((reasons == "entry_open_missing").sum())
    exit_open = int((reasons == "exit_open_missing").sum())
    invalid = int((reasons == "invalid_price").sum())
    identity_holds = n_signals == n_valid + entry + exit_open + invalid + value_missing
    return {
        "status": "ready" if identity_holds else "audit_mismatch",
        "n_signals": n_signals,
        "n_valid": n_valid,
        "excluded_entry_open_missing": entry,
        "excluded_exit_open_missing": exit_open,
        "excluded_invalid_price": invalid,
        "excluded_factor_value_missing": value_missing,
        "coverage": (n_valid / n_signals) if n_signals else None,
        "identity": (
            "n_signals = n_valid + excluded_entry_open_missing + excluded_exit_open_missing"
            " + excluded_invalid_price + excluded_factor_value_missing"
        ),
    }


# --------------------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------------------


def _metadata_index(factor_metadata) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for metadata in factor_metadata or []:
        if isinstance(metadata, Mapping):
            factor_id = str(metadata.get("factor_id", "")).strip()
            direction = metadata.get("direction")
            frequency = metadata.get("frequency")
        else:
            factor_id = str(getattr(metadata, "factor_id", "")).strip()
            direction = getattr(metadata, "direction", None)
            frequency = getattr(metadata, "frequency", None)
        if factor_id:
            index[factor_id] = {"direction": direction, "frequency": frequency}
    return index


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None or isinstance(value, str):
        return value
    return value


def _frame_digest(frame: pd.DataFrame) -> bytes:
    ordered = frame.reindex(sorted(frame.columns), axis=1)
    return pd.util.hash_pandas_object(ordered, index=True).to_numpy().tobytes()


_REPO_ROOT = Path(__file__).resolve().parents[3]
# Version 1 hashed the evaluation/scorecard pair only, which is what every already
# imported run recorded. Version 2 adds the wide-universe factor set, the wide loader and
# the wide scorecard script, because a change there changes the numbers a wide run
# reports while the pair alone stayed identical.
_SOURCE_DIGEST_VERSION_FILES = {
    1: (Path(evaluation_module.__file__), Path(__file__)),
    2: (
        Path(evaluation_module.__file__),
        Path(__file__),
        _REPO_ROOT / "src/quant_system/research/wide_factor_set.py",
        _REPO_ROOT / "src/quant_system/research/wide_universe.py",
        _REPO_ROOT / "scripts/wide_universe_scorecard.py",
    ),
}
SOURCE_DIGEST_VERSION = 2


def _source_digest_files(version: int) -> tuple[Path, ...]:
    try:
        return _SOURCE_DIGEST_VERSION_FILES[int(version)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unknown_source_digest_version:{version}") from exc


def _read_source_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _source_digest(version: int = SOURCE_DIGEST_VERSION) -> str:
    return hashlib.sha256(
        b"".join(_read_source_bytes(path) for path in _source_digest_files(version))
    ).hexdigest()


def recorded_source_digests() -> dict[str, Any]:
    """Digest fields a newly built scorecard records.

    Falls back to the version-1 pair when the wide sources are not present next to this
    installation, so a build never fails and never claims a version it did not hash.
    """
    if all(path.is_file() for path in _source_digest_files(SOURCE_DIGEST_VERSION)):
        return {
            "source_digest": _source_digest(1),
            "source_digest_version": SOURCE_DIGEST_VERSION,
            "source_digest_extended": _source_digest(SOURCE_DIGEST_VERSION),
        }
    return {"source_digest": _source_digest(1)}


def current_source_digest() -> str:
    """Version-1 digest of the evaluation/scorecard source pair, recomputed on read.

    Stored runs recorded this value, so readers that predate ``SOURCE_DIGEST_VERSION``
    keep comparing against it. A version-aware comparison goes through
    ``provenance_is_stale``.
    """
    return _source_digest(1)


def source_digest_version(provenance: Mapping[str, Any] | None) -> int:
    """Digest version a stored provenance was written under; 1 when unversioned."""
    if not isinstance(provenance, Mapping):
        return 0
    try:
        return int(provenance.get("source_digest_version", 1))
    except (TypeError, ValueError):
        return 0


def provenance_is_stale(provenance: Mapping[str, Any] | None) -> bool:
    """Compare a stored provenance against the sources under the version it recorded.

    Version 1 (every run written before this field existed) is compared on
    ``source_digest``, so extending the digest never turns an existing run stale.
    Version 2 compares ``source_digest_extended``, which also covers
    ``wide_factor_set.py``, ``wide_universe.py`` and ``scripts/wide_universe_scorecard.py``.
    """
    version = source_digest_version(provenance)
    if version == 1:
        stored_key = "source_digest"
    elif version == SOURCE_DIGEST_VERSION:
        stored_key = "source_digest_extended"
    else:
        return True
    try:
        current = _source_digest(version)
    except (OSError, ValueError):
        return True
    return str(provenance.get(stored_key, "")) != current


def _digests(
    ohlcv: pd.DataFrame,
    factor_results: pd.DataFrame,
    parameters: Mapping[str, Any],
) -> tuple[str, str]:
    parameters_json = json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode("utf-8")
    prices_digest = hashlib.sha256(_frame_digest(ohlcv)).hexdigest()
    input_digest = hashlib.sha256(
        _frame_digest(ohlcv) + _frame_digest(factor_results) + parameters_json
    ).hexdigest()
    return prices_digest, input_digest


def _methodology(
    *, horizons: tuple[int, ...], quantiles: int, benchmark_symbol: str, price_basis: str
) -> dict:
    return {
        "forward_return": "open_t+1_to_open_t+1+h",
        "label_formula": "open(t+1+h)/open(t+1)-1",
        "price_basis": price_basis,
        "calendar": "union_observed_no_fill",
        "gap_rules": "R-cal-1..8",
        "nw_lag_rule": "min(max(h-1, floor(4*(T/100)^(2/9))), T-1), Bartlett, pairwise-complete",
        "min_samples": {
            "nw_T": "max(60, 3(L+1))",
            "nw_pairs": 30,
            "quantile_day": "2*quantiles",
            "beta_window": "252/min126",
            "ls_beta_days": 60,
            "marginal_T": MARGINAL_MIN_FULL_SAMPLE,
        },
        "horizons": list(horizons),
        "quantiles": quantiles,
        "benchmark_symbol": benchmark_symbol,
        "beta_estimation_residual": "rolling_252d_min126_pit",
        "beta_estimation_ls": "full_sample_ols",
        "costs": "none_evaluation_only",
        "short_assumption": _SHORT_ASSUMPTION,
        "evaluation_only": True,
        "tradeable_claim": False,
    }


_CORE_BLOCK_KEYS = ("ic", "residual_ic", "long_short", "correlation", "marginal_contribution")


def _factor_status(entry: dict) -> str:
    statuses: list[str] = []
    for horizon_entry in entry["horizons"].values():
        for key in ("ic", "residual_ic"):
            statuses.append(str(horizon_entry[key].get("status", "unavailable")))
        statuses.append(str(horizon_entry["long_short"].get("status", "unavailable")))
    statuses.append(str(entry["correlation"].get("status", "unavailable")))
    statuses.append(str(entry["marginal_contribution"].get("status", "unavailable")))
    if all(status == "ready" for status in statuses):
        return "ready"
    if all(status == "unavailable" for status in statuses):
        return "unavailable"
    return "partial"


def _compute_scorecard(
    *,
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    factor_metadata,
    benchmark_symbol: str = "SPY",
    sleeve_returns=None,
    industry_membership=None,
    horizons: Sequence[int] = (1, 5, 21),
    quantiles: int = 5,
    library_factor_results: pd.DataFrame | None = None,
    price_basis: PriceBasis = "open_to_open",
) -> tuple[dict, dict[str, pd.DataFrame]]:
    if industry_membership is not None:
        raise NotImplementedError("industry_neutral_pending_fields")
    if price_basis != "open_to_open":
        raise ValueError("factor scorecards are defined on the open-to-open basis")
    horizons = tuple(int(horizon) for horizon in horizons)
    benchmark = str(benchmark_symbol).upper().strip()
    close_available = "close" in ohlcv.columns

    open_frame = build_price_frame(ohlcv, price_basis="open_to_open")
    close_frame = (
        build_price_frame(ohlcv, price_basis="close_to_close") if close_available else None
    )
    prepared = prepare_evaluation_frames(
        factor_results,
        ohlcv,
        horizons=horizons,
        price_basis="open_to_open",
        price_frame=open_frame,
    )
    metadata = _metadata_index(factor_metadata)
    factor_ids = sorted(set(factor_results["factor_id"].astype(str)))
    benchmark_present = benchmark in open_frame.matrix.columns
    benchmark_labels = (
        {horizon: _benchmark_label(open_frame.matrix[benchmark], horizon) for horizon in horizons}
        if benchmark_present
        else {}
    )
    betas = (
        _rolling_betas(close_frame.matrix, close_frame.matrix[benchmark])
        if close_frame is not None and benchmark_present
        else None
    )
    last_observed = _last_observed_dates(open_frame)

    ic_daily_frames: list[pd.DataFrame] = []
    quantile_daily_frames: list[pd.DataFrame] = []
    long_short_daily_frames: list[pd.DataFrame] = []
    correlation_daily_frames: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []

    for factor_id in factor_ids:
        direction = metadata.get(factor_id, {}).get("direction")
        frequency = metadata.get(factor_id, {}).get("frequency")
        signal_dates = pd.DatetimeIndex(
            pd.to_datetime(
                factor_results.loc[factor_results.factor_id == factor_id, "signal_ts"], utc=True
            ).unique()
        ).sort_values()
        signal_positions = open_frame.calendar.get_indexer(signal_dates)
        signal_positions = signal_positions[signal_positions >= 0]
        sparse_calendar = (
            len(signal_positions) > 1 and np.median(np.diff(signal_positions)) > 3
        ) or frequency in {"weekly", "monthly", "month_end", "quarterly", "event"}
        horizons_block: dict[str, Any] = {}
        marginal_candidate: pd.Series | None = None
        marginal_sparse = False
        factor_candidate_frame: pd.DataFrame | None = None
        for horizon in horizons:
            # HAC lags count signal observations, while a label horizon counts
            # trading sessions. Derive overlap from the fixed calendar, never
            # choose a lag by comparing the resulting t statistics.
            overlap_lags = horizon - 1
            if sparse_calendar and len(signal_positions):
                ends = np.searchsorted(signal_positions, signal_positions + horizon, side="left")
                overlap_lags = int(np.max(ends - np.arange(len(signal_positions)) - 1))
            inference_horizon = overlap_lags + 1
            merged = prepared[horizon]
            subset = merged[merged["factor_id"].astype(str) == factor_id]
            coverage = _coverage_block(subset)
            ic_daily, ic_summary = _daily_ic_block(
                subset, factor_id=factor_id, horizon=horizon, price_basis=price_basis,
                inference_horizon=inference_horizon,
            )
            residual_daily, residual_block = _residual_ic_block(
                subset,
                factor_id=factor_id,
                horizon=horizon,
                betas=betas,
                benchmark_labels=benchmark_labels.get(horizon),
                benchmark_symbol=benchmark,
                close_available=close_available,
                inference_horizon=inference_horizon,
            )
            combined_daily = ic_daily.merge(
                residual_daily, on=["factor_id", "signal_ts", "horizon"], how="outer"
            )
            ic_daily_frames.append(combined_daily)
            quantile_daily, long_short_daily, ls_block, adjusted = _quantile_ls_block(
                subset,
                factor_id=factor_id,
                direction=direction,
                horizon=horizon,
                quantiles=quantiles,
                benchmark_labels=benchmark_labels.get(horizon),
                calendar=open_frame.calendar,
                inference_horizon=inference_horizon,
            )
            quantile_daily_frames.append(quantile_daily)
            if not long_short_daily.empty:
                long_short_daily_frames.append(long_short_daily)
            beta_block = long_short_beta_hedge(
                adjusted,
                (
                    long_short_daily.set_index("signal_ts")["benchmark_return"].dropna().sort_index()
                    if not long_short_daily.empty
                    else pd.Series(dtype="float64")
                ),
                horizon=horizon,
                inference_horizon=inference_horizon,
            )
            sparse = sparse_calendar or ls_block["turnover"].get("cadence") == "irregular"
            annualization_reason = None
            if sparse:
                # Monthly/event signals do not supply 252 annual opportunities.
                # Keep the observed h-session means and HAC statistics, but do
                # not convert the selected signal dates into a daily portfolio.
                annualization_reason = "sparse_signal_calendar_not_a_daily_portfolio"
                ls_block["spread_annualized"] = None
                beta_block["alpha_annualized"] = None
                beta_block["beta_neutral_spread_annualized"] = None
                beta_block["annualization_reason"] = annualization_reason
            horizons_block[str(horizon)] = {
                "inference": {
                    "method": "calendar_overlap_floor_v1",
                    "lag_unit": "signal_observations",
                    "horizon_unit": "trading_sessions",
                    "signal_frequency": frequency or ("sparse" if sparse else "daily"),
                    "overlap_lags": overlap_lags,
                },
                "ic": {**ic_summary, "coverage": coverage["coverage"]},
                "residual_ic": residual_block,
                "quantiles": {
                    "status": ls_block["status"],
                    "quantiles": quantiles,
                    "quantile_means": ls_block["quantile_means"],
                    "quantile_means_adjusted": ls_block["quantile_means_adjusted"],
                    "quantile_monotonic": ls_block["quantile_monotonic"],
                    "n_days": ls_block["n_days"],
                    "skipped_thin_days": ls_block["skipped_thin_days"],
                },
                "long_short": {
                    "status": ls_block["status"],
                    "reason": ls_block["reason"],
                    "spread_mean_daily": ls_block["spread_mean_daily"],
                    "spread_mean_daily_raw": ls_block["spread_mean_daily_raw"],
                    "spread_annualized": ls_block["spread_annualized"],
                    "annualization_reason": annualization_reason,
                    "spread_t_nw": ls_block["spread_t_nw"],
                    "spread_nw_lag": ls_block["spread_nw_lag"],
                    "spread_nw_reason": ls_block["spread_nw_reason"],
                    "n_days": ls_block["n_days"],
                    "evaluation_only": True,
                    "tradeable_claim": False,
                    "short_assumption": _SHORT_ASSUMPTION,
                    "beta_neutral": beta_block,
                },
                "turnover": {
                    "status": ls_block["status"],
                    **ls_block["turnover"],
                    "definition": "(1/2)*sum_i |w_i(t) - w_i(t-1)|, equal weight inside bucket",
                },
                "coverage": coverage,
            }
            # ``excluded_terminal_exit`` is the survivorship sub-count of rows whose exit
            # leg is missing *and* whose required exit session exists on the union calendar
            # and lies beyond this symbol's last observation (``return_end_ts`` is NaT when
            # the required session is past the union calendar). Consequence: a symbol whose
            # series ends exactly on the panel's last session is NOT counted -- there is no
            # observable market session after it, and the frozen ``excluded_exit_open_missing``
            # count already covers the label. This is a bounded reading of R-cal-7 (which
            # literally keys on "exit missing & required exit day > symbol last observation");
            # the terminal count stays a sub-count of that class, so R-cal-8 is unaffected.
            terminal = (
                subset["exclusion_reason"].eq("exit_open_missing")
                & subset["return_end_ts"].notna()
                & (subset["return_end_ts"] > subset["symbol"].map(last_observed))
            )
            terminal_by_symbol = terminal.groupby(subset["symbol"]).sum()
            audit_rows.append(
                {
                    "factor_id": factor_id,
                    "horizon": horizon,
                    "symbol": "",
                    **{
                        key: coverage[key]
                        for key in (
                            "n_signals",
                            "n_valid",
                            "excluded_entry_open_missing",
                            "excluded_exit_open_missing",
                            "excluded_invalid_price",
                            "excluded_factor_value_missing",
                            "coverage",
                        )
                    },
                    "terminal_exit": int(terminal.sum()),
                }
            )
            audit_rows.extend(
                {
                    "factor_id": factor_id,
                    "horizon": horizon,
                    "symbol": str(symbol),
                    "terminal_exit": int(count),
                }
                for symbol, count in terminal_by_symbol.items()
                if int(count) > 0
            )
            if horizon == 1:
                marginal_candidate = adjusted
                marginal_sparse = sparse
                factor_candidate_frame = subset
        if factor_candidate_frame is None:
            marginal_candidate = pd.Series(dtype="float64")
            factor_candidate_frame = prepared[horizons[0]][
                prepared[horizons[0]]["factor_id"].astype(str) == factor_id
            ]
        correlation_daily, correlation_block = _correlation_block(
            factor_candidate_frame, library_factor_results, factor_id=factor_id
        )
        correlation_daily_frames.append(correlation_daily)
        marginal = (
            {
                "status": "not_evaluated",
                "reason": "non_daily_signal_portfolio_required",
                "marginal_sharpe_delta": None,
                "sleeve_portfolio_correlation": None,
                "n_shared_days": 0,
                "paired_difference": None,
                "evaluation_only": True,
                "tradeable_claim": False,
                "note": "先按实际持有和空仓规则形成完整日线组合，不能只取月末信号日与模拟仓比较。",
            }
            if marginal_sparse
            else sleeve_marginal_contribution(marginal_candidate, sleeve_returns)
        )
        if 1 not in horizons:
            marginal = {
                "status": "unavailable",
                "reason": "horizon_1_not_computed",
                "marginal_sharpe_delta": None,
                "sleeve_portfolio_correlation": None,
                "n_shared_days": 0,
                "paired_difference": None,
                "evaluation_only": True,
                "tradeable_claim": False,
            }
        entries.append(
            {
                "factor_id": factor_id,
                "direction": direction,
                "direction_defaulted": direction is None,
                "horizons": horizons_block,
                "correlation": correlation_block,
                "marginal_contribution": marginal,
                "industry_neutral": {
                    "status": "field_unavailable",
                    "note": "行业中性归 T4.3 字段到位后。",
                },
            }
        )

    parameters = {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "methodology_version": METHODOLOGY_VERSION,
        "horizons": list(horizons),
        "quantiles": int(quantiles),
        "benchmark_symbol": benchmark,
        "price_basis": price_basis,
    }
    prices_digest, input_digest = _digests(ohlcv, factor_results, parameters)
    statuses = [_factor_status(entry) for entry in entries]
    if not entries:
        status = "unavailable"
    elif all(state == "ready" for state in statuses):
        status = "ready"
    elif all(state == "unavailable" for state in statuses):
        status = "unavailable"
    else:
        status = "partial"
    peer_ids = (
        sorted(set(library_factor_results["factor_id"].astype(str)))
        if library_factor_results is not None and "factor_id" in library_factor_results.columns
        else []
    )
    scorecard = {
        "schema_version": SCORECARD_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "methodology": _methodology(
            horizons=horizons,
            quantiles=int(quantiles),
            benchmark_symbol=benchmark,
            price_basis=price_basis,
        ),
        "provenance": {
            "methodology_version": METHODOLOGY_VERSION,
            "forward_return_schema_version": FORWARD_RETURN_SCHEMA_VERSION,
            "input_digest": input_digest,
            "prices_sha256": prices_digest,
            # ``source_digest`` keeps its version-1 meaning for readers that predate the
            # version marker; ``source_digest_extended`` is the digest named by
            # ``source_digest_version`` and is what ``provenance_is_stale`` compares.
            **recorded_source_digests(),
            "peer_factor_ids": peer_ids,
        },
        "stale": False,
        "factors": entries,
    }
    def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        present = [frame for frame in frames if not frame.empty]
        return pd.concat(present, ignore_index=True) if present else pd.DataFrame()

    artifacts = {
        "ic_daily": _concat(ic_daily_frames),
        "quantile_daily": _concat(quantile_daily_frames),
        "long_short_daily": _concat(long_short_daily_frames),
        "correlation_daily": _concat(correlation_daily_frames),
        "audit": pd.DataFrame(audit_rows),
    }
    return _jsonable(scorecard), artifacts


def build_factor_scorecard_bundle(
    *,
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    factor_metadata,
    benchmark_symbol: str = "SPY",
    sleeve_returns=None,
    industry_membership=None,
    horizons: Sequence[int] = (1, 5, 21),
    quantiles: int = 5,
    library_factor_results: pd.DataFrame | None = None,
) -> tuple[dict, dict[str, pd.DataFrame]]:
    """Scorecard JSON plus the daily parquet-bound frames behind it."""
    return _compute_scorecard(
        factor_results=factor_results,
        ohlcv=ohlcv,
        factor_metadata=factor_metadata,
        benchmark_symbol=benchmark_symbol,
        sleeve_returns=sleeve_returns,
        industry_membership=industry_membership,
        horizons=horizons,
        quantiles=quantiles,
        library_factor_results=library_factor_results,
    )


def build_factor_scorecards(
    *,
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    factor_metadata,
    benchmark_symbol: str = "SPY",
    sleeve_returns=None,
    industry_membership=None,
    horizons: Sequence[int] = (1, 5, 21),
    quantiles: int = 5,
    library_factor_results: pd.DataFrame | None = None,
) -> dict:
    """Pure, JSON-serialisable factor scorecards (sealed with ``allow_nan=False``)."""
    scorecard, _ = build_factor_scorecard_bundle(
        factor_results=factor_results,
        ohlcv=ohlcv,
        factor_metadata=factor_metadata,
        benchmark_symbol=benchmark_symbol,
        sleeve_returns=sleeve_returns,
        industry_membership=industry_membership,
        horizons=horizons,
        quantiles=quantiles,
        library_factor_results=library_factor_results,
    )
    return scorecard
