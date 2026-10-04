"""Factor evaluation: forward-return labels and cross-sectional statistics.

Label convention (``forward_returns/v2``): a signal observed at ``signal_ts``
(day ``t``, known after that session's close) is actionable at the next session's
open. The forward return for horizon ``h`` is::

    forward_return(s, t, h) = open(s, t + 1 + h) / open(s, t + 1) - 1

For ``h == 1`` this is ``opens.shift(-2) / opens.shift(-1) - 1`` -- the label
used by ``research/qlib_evaluation.py`` (signal day t close -> t+1 open entry).

Shifts always run on the union of observed sessions, never inside a single
symbol's non-missing rows and never with forward fill: a missing session must
not silently become a later entry price. A broken leg therefore yields a missing
label plus an audit counter instead of a longer holding period.

The legacy ``price_basis="close_to_close"`` option keeps the retired
``close(t + h) / close(t) - 1`` convention for compatibility seals only; the
default is always ``open_to_open``.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

FORWARD_RETURN_SCHEMA_VERSION = "forward_returns/v2"
METHODOLOGY_VERSION = "factor-eval-2"
PriceBasis = Literal["open_to_open", "close_to_close"]

_BASIS_COLUMNS: dict[str, str] = {"open_to_open": "open", "close_to_close": "close"}
INVALID_PRICE_CELL_LIMIT = 0.01
_LABEL_COLUMNS = [
    "symbol",
    "signal_ts",
    "entry_ts",
    "return_end_ts",
    "forward_return",
    "price_basis",
    "horizon",
]


@dataclass(frozen=True)
class PriceFrame:
    """Wide price matrix on the union observed calendar, pivoted exactly once.

    ``matrix`` holds the selected basis column (NaN when a symbol has no
    observation on a session, or when the observed price is not a usable
    positive finite number). ``observed_mask`` is True where the input had a row
    for that (session, symbol); ``invalid_mask`` is True where that row's price
    was unusable. ``invalid_cells`` counts the latter.
    """

    matrix: pd.DataFrame
    calendar: pd.DatetimeIndex
    price_basis: str
    invalid_cells: int
    observed_mask: pd.DataFrame
    invalid_mask: pd.DataFrame


def build_price_frame(ohlcv: pd.DataFrame, *, price_basis: str = "open_to_open") -> PriceFrame:
    """Validate ``ohlcv`` and pivot the selected basis column into a wide matrix.

    Validation: required columns, duplicate ``(symbol, timestamp)`` rows,
    non-positive / non-finite prices (turned into NaN and counted; more than
    ``INVALID_PRICE_CELL_LIMIT`` of the panel raises). Symbols are upper-cased
    and timestamps normalised to tz-aware UTC.
    """
    if price_basis not in _BASIS_COLUMNS:
        raise ValueError(f"unsupported price_basis: {price_basis!r}")
    column = _BASIS_COLUMNS[price_basis]
    required = {"symbol", "timestamp", column}
    missing = required.difference(ohlcv.columns)
    if missing:
        raise ValueError(f"missing required OHLCV columns: {', '.join(sorted(missing))}")

    frame = ohlcv.loc[:, ["symbol", "timestamp", column]].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if frame.duplicated(["symbol", "timestamp"]).any():
        raise ValueError("evaluation_duplicate_price_rows")
    numeric = pd.to_numeric(frame[column], errors="coerce")
    invalid = ~(numeric.notna() & np.isfinite(numeric) & (numeric > 0))
    frame["_price"] = numeric.mask(invalid)
    frame["_invalid"] = invalid

    matrix = frame.pivot(index="timestamp", columns="symbol", values="_price").sort_index()
    matrix = matrix.reindex(sorted(matrix.columns), axis=1)
    pivoted_invalid = frame.pivot(index="timestamp", columns="symbol", values="_invalid").reindex(
        index=matrix.index, columns=matrix.columns
    )
    # Absent (symbol, session) combinations are NaN after the pivot; only an
    # observed row with an unusable price counts as an invalid cell.
    invalid_mask = pivoted_invalid.notna() & pivoted_invalid.eq(True)
    observed_mask = matrix.notna() | invalid_mask
    invalid_cells = int(invalid.sum())
    if matrix.size and invalid_cells / matrix.size > INVALID_PRICE_CELL_LIMIT:
        raise ValueError("evaluation_excessive_invalid_prices")
    return PriceFrame(
        matrix=matrix,
        calendar=pd.DatetimeIndex(matrix.index),
        price_basis=price_basis,
        invalid_cells=invalid_cells,
        observed_mask=observed_mask,
        invalid_mask=invalid_mask,
    )


def forward_return_matrix(frame: PriceFrame, h: int) -> pd.DataFrame:
    """Wide forward-return matrix: open(t+1) -> open(t+1+h), or legacy close basis."""
    if h <= 0:
        raise ValueError("horizon must be greater than zero")
    matrix = frame.matrix
    if frame.price_basis == "open_to_open":
        return matrix.shift(-(h + 1)) / matrix.shift(-1) - 1.0
    return matrix.shift(-h) / matrix - 1.0


def _leg_offsets(price_basis: str, horizon: int) -> tuple[int, int]:
    if price_basis == "open_to_open":
        return 1, horizon + 1
    return 0, horizon


def _audited_labels(prices: PriceFrame, horizon: int) -> tuple[pd.DataFrame, dict]:
    """Every observed signal row with its label, exclusion reason and audit counters."""
    if horizon <= 0:
        raise ValueError("horizon must be greater than zero")
    returns = forward_return_matrix(prices, horizon)
    entry_offset, exit_offset = _leg_offsets(prices.price_basis, horizon)
    matrix = prices.matrix
    entry_prices = matrix.shift(-entry_offset)
    exit_prices = matrix.shift(-exit_offset)
    entry_invalid = (
        prices.invalid_mask.shift(-entry_offset, fill_value=False).astype(bool)
        if entry_offset
        else prices.invalid_mask
    )
    exit_invalid = (
        prices.invalid_mask.shift(-exit_offset, fill_value=False).astype(bool)
        if exit_offset
        else prices.invalid_mask
    )

    stacked = pd.DataFrame(
        {
            "forward_return": returns.stack(future_stack=True),
            "observed": prices.observed_mask.stack(future_stack=True),
            "entry_price": entry_prices.stack(future_stack=True),
            "exit_price": exit_prices.stack(future_stack=True),
            "entry_invalid": entry_invalid.stack(future_stack=True),
            "exit_invalid": exit_invalid.stack(future_stack=True),
        }
    )
    stacked = stacked[stacked["observed"]]
    stacked.index = stacked.index.set_names(["signal_ts", "symbol"])
    stacked = stacked.reset_index()

    forward_return = pd.to_numeric(stacked["forward_return"], errors="coerce")
    valid = forward_return.notna() & np.isfinite(forward_return)
    # A row is classified once, by the first leg that is unusable for this label.
    reason = np.where(
        valid,
        None,
        np.where(
            stacked["entry_price"].isna(),
            np.where(stacked["entry_invalid"], "invalid_price", "entry_open_missing"),
            np.where(
                stacked["exit_price"].isna(),
                np.where(stacked["exit_invalid"], "invalid_price", "exit_open_missing"),
                "invalid_price",
            ),
        ),
    )

    calendar_series = pd.Series(prices.calendar, index=prices.calendar)
    entry_map = calendar_series.shift(-entry_offset) if entry_offset else calendar_series
    exit_map = calendar_series.shift(-exit_offset) if exit_offset else calendar_series
    signal_ts = stacked["signal_ts"]
    result = pd.DataFrame(
        {
            "symbol": stacked["symbol"].astype(str),
            "signal_ts": signal_ts,
            "entry_ts": pd.to_datetime(signal_ts.map(entry_map), utc=True),
            "return_end_ts": pd.to_datetime(signal_ts.map(exit_map), utc=True),
            "forward_return": forward_return,
            "exclusion_reason": reason,
        }
    )
    result["price_basis"] = prices.price_basis
    result["horizon"] = int(horizon)
    result = result.sort_values(["symbol", "signal_ts"], ignore_index=True)

    last_observed = result.groupby("symbol")["signal_ts"].max()
    # Read the masks back off the sorted frame: the pre-sort ``reason`` array and
    # ``valid`` mask are ordered by (session, symbol) and would misalign here.
    reason_column = result["exclusion_reason"]
    missing_label = result["forward_return"].isna()
    required_exit = result["return_end_ts"]
    # Survivorship visibility: the label needs a session that exists on the union
    # calendar but the symbol's own series had already ended (whichever leg broke
    # first). Sub-count of the exclusion counters, not an extra class.
    terminal = (
        missing_label
        & required_exit.notna()
        & (required_exit > result["symbol"].map(last_observed))
    )
    terminal_counts = terminal.groupby(result["symbol"]).sum().astype(int)
    audit = {
        "price_basis": prices.price_basis,
        "horizon": int(horizon),
        "n_signal_rows": int(len(result)),
        "n_valid": int(result["forward_return"].notna().sum()),
        "excluded_entry_open_missing": int(reason_column.eq("entry_open_missing").sum()),
        "excluded_exit_open_missing": int(reason_column.eq("exit_open_missing").sum()),
        "excluded_invalid_price": int(reason_column.eq("invalid_price").sum()),
        "excluded_terminal_exit": {
            str(symbol): int(count) for symbol, count in terminal_counts.items() if count > 0
        },
        "invalid_cells": prices.invalid_cells,
    }
    return result, audit


def make_forward_returns(
    ohlcv: pd.DataFrame,
    *,
    horizon: int = 1,
    price_basis: str = "open_to_open",
) -> pd.DataFrame:
    """Mature forward-return labels (one row per observed symbol-session signal)."""
    audited, _audit = _labels_for_input(ohlcv, horizon=horizon, price_basis=price_basis)
    mature = audited[audited["forward_return"].notna()]
    return mature.loc[:, _LABEL_COLUMNS].reset_index(drop=True)


def make_forward_returns_audited(
    ohlcv: pd.DataFrame,
    *,
    horizon: int = 1,
    price_basis: str = "open_to_open",
) -> tuple[pd.DataFrame, dict]:
    """All observed signal rows plus an audit dict (no silent row drops).

    ``exclusion_reason`` is one of ``None`` / ``entry_open_missing`` /
    ``exit_open_missing`` / ``invalid_price``. Missing labels are never rolled
    forward to a later session.
    """
    return _labels_for_input(ohlcv, horizon=horizon, price_basis=price_basis)


def _labels_for_input(
    ohlcv: pd.DataFrame, *, horizon: int, price_basis: str
) -> tuple[pd.DataFrame, dict]:
    prices = build_price_frame(ohlcv, price_basis=price_basis)
    return _audited_labels(prices, horizon)


def make_forward_returns_multi(
    ohlcv: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 5, 21),
    *,
    price_basis: str = "open_to_open",
) -> dict[int, pd.DataFrame]:
    """One pivot, one entry shift, one exit shift per horizon.

    ``multi[h]`` is bit-for-bit equal to ``make_forward_returns(ohlcv, horizon=h)``.
    """
    prices = build_price_frame(ohlcv, price_basis=price_basis)
    labels: dict[int, pd.DataFrame] = {}
    for horizon in horizons:
        audited, _audit = _audited_labels(prices, horizon)
        labels[int(horizon)] = audited[audited["forward_return"].notna()].loc[
            :, _LABEL_COLUMNS
        ].reset_index(drop=True)
    return labels


def prepare_evaluation_frames(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizons: tuple[int, ...],
    price_basis: str = "open_to_open",
    price_frame: PriceFrame | None = None,
) -> dict[int, pd.DataFrame]:
    """Normalise factor rows once and merge them with audited labels per horizon.

    The factor frame is de-duplicated on ``(factor_id, symbol, signal_ts)`` (a
    second row would silently fan out every statistic), and the price matrix and
    entry shift are computed once for the whole call.
    """
    if not horizons:
        raise ValueError("horizons must be non-empty")
    required = {"symbol", "signal_ts", "factor_id", "value"}
    missing = required.difference(factor_results.columns)
    if missing:
        raise ValueError(f"missing required factor result columns: {', '.join(sorted(missing))}")

    factors = factor_results.copy()
    factors["symbol"] = factors["symbol"].astype(str).str.upper().str.strip()
    factors["signal_ts"] = pd.to_datetime(factors["signal_ts"], utc=True)
    factors["value"] = pd.to_numeric(factors["value"], errors="coerce")
    if factors.duplicated(["factor_id", "symbol", "signal_ts"]).any():
        raise ValueError("evaluation_duplicate_factor_rows")

    prices = (
        price_frame
        if price_frame is not None
        else build_price_frame(ohlcv, price_basis=price_basis)
    )
    prepared: dict[int, pd.DataFrame] = {}
    for horizon in horizons:
        labels, _audit = _audited_labels(prices, horizon)
        prepared[int(horizon)] = factors.merge(labels, on=["symbol", "signal_ts"], how="inner")
    return prepared


def spearman_correlation(left: pd.Series, right: pd.Series) -> float:
    """Spearman rank correlation without a scipy dependency."""
    return left.rank(method="average").corr(right.rank(method="average"), method="pearson")


def _spearman_without_scipy(left: pd.Series, right: pd.Series) -> float:
    return spearman_correlation(left, right)


def information_coefficients_from_merged(
    merged: pd.DataFrame, *, return_column: str = "forward_return"
) -> pd.DataFrame:
    """Per-(factor, signal_ts) Pearson and Spearman IC rows from a prepared frame.

    The single implementation of the per-day IC rule, shared by
    :func:`calculate_information_coefficients` and the scorecard residual block.
    Days with fewer than two usable rows (or a constant column) keep an ``ic`` /
    ``rank_ic`` of NaN, matching the historical semantics.
    """
    rows: list[dict[str, object]] = []
    for (factor_id, signal_ts), group in merged.groupby(["factor_id", "signal_ts"], sort=True):
        clean = group.dropna(subset=["value", return_column])
        n = len(clean)
        ic = float("nan")
        rank_ic = float("nan")
        if n >= 2 and clean["value"].nunique() > 1 and clean[return_column].nunique() > 1:
            ic = clean["value"].corr(clean[return_column], method="pearson")
            rank_ic = spearman_correlation(clean["value"], clean[return_column])
        rows.append(
            {
                "factor_id": factor_id,
                "signal_ts": signal_ts,
                "ic": ic,
                "rank_ic": rank_ic,
                "n": n,
            }
        )
    return pd.DataFrame(rows, columns=["factor_id", "signal_ts", "ic", "rank_ic", "n"])


def calculate_information_coefficients(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizon: int = 1,
    price_basis: str = "open_to_open",
) -> pd.DataFrame:
    """Per-signal-date Pearson IC and Spearman rank IC."""
    prepared = prepare_evaluation_frames(
        factor_results, ohlcv, horizons=(horizon,), price_basis=price_basis
    )
    frame = information_coefficients_from_merged(prepared[horizon])
    frame["horizon"] = int(horizon)
    frame["price_basis"] = price_basis
    return frame


def calculate_quantile_returns(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    quantiles: int = 5,
    horizon: int = 1,
    price_basis: str = "open_to_open",
) -> pd.DataFrame:
    if quantiles < 2:
        raise ValueError("quantiles must be at least two")
    prepared = prepare_evaluation_frames(
        factor_results, ohlcv, horizons=(horizon,), price_basis=price_basis
    )
    merged = prepared[horizon]
    bucketed: list[pd.DataFrame] = []
    for (_, signal_ts), group in merged.groupby(["factor_id", "signal_ts"], sort=True):
        clean = group.dropna(subset=["value", "forward_return"]).copy()
        if len(clean) < 2 or clean["value"].nunique() < 2:
            continue
        bucket_count = min(quantiles, len(clean))
        clean["quantile"] = pd.qcut(
            clean["value"].rank(method="first"),
            q=bucket_count,
            labels=range(1, bucket_count + 1),
        ).astype(int)
        clean["signal_ts"] = signal_ts
        bucketed.append(clean)

    columns = [
        "factor_id",
        "quantile",
        "mean_forward_return",
        "median_forward_return",
        "count",
        "horizon",
        "price_basis",
    ]
    if not bucketed:
        empty = pd.DataFrame(columns=columns[:5])
        empty["horizon"] = int(horizon)
        empty["price_basis"] = price_basis
        return empty.loc[:, columns]

    combined = pd.concat(bucketed, ignore_index=True)
    frame = (
        combined.groupby(["factor_id", "quantile"], as_index=False)
        .agg(
            mean_forward_return=("forward_return", "mean"),
            median_forward_return=("forward_return", "median"),
            count=("forward_return", "count"),
        )
        .sort_values(["factor_id", "quantile"], ignore_index=True)
    )
    frame["horizon"] = int(horizon)
    frame["price_basis"] = price_basis
    return frame.loc[:, columns]


def calculate_ic_ir(ic_frame: pd.DataFrame) -> dict:
    """Summarize one factor's IC series: mean, std, ICIR, and signal count.

    Descriptive only: this is an i.i.d. period ratio. Under overlapping horizons
    the periods are autocorrelated and the ratio is distorted; use the
    Newey-West statistic from :func:`summarize_ic_series` for inference.
    """
    if ic_frame.empty:
        raise ValueError("ic_frame is empty")
    factor_ids = sorted(ic_frame["factor_id"].unique())
    if len(factor_ids) != 1:
        raise ValueError("calculate_ic_ir expects exactly one factor")
    values = pd.to_numeric(ic_frame["ic"], errors="coerce").dropna()
    n = int(len(values))
    mean = float(values.mean()) if n else None
    std = float(values.std(ddof=1)) if n > 1 else None
    ic_ir = float(mean / std) if (mean is not None and std not in (None, 0.0)) else None
    return {
        "factor_id": factor_ids[0],
        "n_signals": n,
        "ic_mean": mean,
        "ic_std": std,
        "ic_ir": ic_ir,
    }


def calculate_ic_decay(
    factor_frame: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = (1, 5, 10, 21),
    price_basis: str = "open_to_open",
) -> list[dict]:
    """Rank IC of one factor against forward returns at several horizons."""
    required = {"symbol", "signal_ts", "factor_id", "value"}
    missing = required.difference(factor_frame.columns)
    if missing:
        raise ValueError(f"factor frame missing columns: {sorted(missing)}")
    for horizon in horizons:
        if horizon <= 0:
            raise ValueError("horizons must be positive")
    prepared = prepare_evaluation_frames(
        factor_frame, ohlcv, horizons=horizons, price_basis=price_basis
    )
    rows: list[dict] = []
    for horizon in horizons:
        clean = prepared[horizon].dropna(subset=["value", "forward_return"])
        rank_ic = None
        if not clean.empty:
            rank_ic = spearman_correlation(clean["value"], clean["forward_return"])
            if rank_ic is not None and pd.isna(rank_ic):
                rank_ic = None
        rows.append({"horizon": horizon, "rank_ic": rank_ic, "n": int(len(clean))})
    return rows


def newey_west_lag_rule(n_obs: int, *, horizon: int = 1) -> int:
    """Bartlett lag truncation with the mechanical overlap floor.

    An ``h``-session forward return spans ``h`` daily increments, so signals
    ``k`` sessions apart share a window whenever ``k <= h - 1``: the induced
    moving-average order is ``h - 1`` (0, 4 and 20 for h = 1, 5 and 21). Slow
    factors add real autocorrelation at arbitrary lags, so the floor is combined
    with the Newey-West (1994) plug-in rule ``floor(4 * (T/100)^(2/9))``.
    """
    if horizon < 1:
        raise ValueError("horizon must be greater than zero")
    if n_obs < 2:
        return 0
    plug_in = math.floor(4.0 * (n_obs / 100.0) ** (2.0 / 9.0))
    return int(min(max(horizon - 1, plug_in), n_obs - 1))


def newey_west_stats(
    values,
    *,
    lag: int,
    horizon: int = 1,
    min_observations: int | None = None,
    min_pairs: int = 30,
) -> dict:
    """Newey-West HAC summary of a (possibly NaN-bearing) daily series.

    Pairwise-complete Bartlett kernel: ``gamma_k`` sums only over pairs where
    both ends are present and divides by the number of present observations
    ``T``; ``LRV = gamma_0 + 2 * sum_k (1 - k/(L+1)) * gamma_k`` and
    ``t = mean / sqrt(LRV / T)``.

    Guardrails return ``t_stat=None`` with a reason instead of a fragile number:
    too few observations, fewer than ``min_pairs`` pairs at a mechanically
    required lag (``k <= horizon - 1``), or a non-positive long-run variance.
    ``min_observations`` defaults to ``max(60, 3 * (lag + 1))``.
    """
    if lag < 0:
        raise ValueError("lag must not be negative")
    if horizon < 1:
        raise ValueError("horizon must be greater than zero")
    raw = pd.to_numeric(pd.Series(values, dtype="float64"), errors="coerce").to_numpy(dtype=float)
    present = raw[np.isfinite(raw)]
    n_obs = int(present.size)
    lag = int(lag)
    result: dict = {
        "t_stat": None,
        "reason": None,
        "mean": None,
        "lrv": None,
        "gamma_0": None,
        "kappa": None,
        "n_obs": n_obs,
        "lag": lag,
        "pair_counts": {},
    }
    threshold = max(60, 3 * (lag + 1)) if min_observations is None else int(min_observations)
    if n_obs < threshold:
        result["reason"] = "insufficient_observations"
        return result

    mean = float(present.mean())
    gamma_0 = float(((present - mean) ** 2).mean())
    result["mean"] = mean
    result["gamma_0"] = gamma_0
    lrv = gamma_0
    pair_counts: dict[int, int] = {}
    for k in range(1, lag + 1):
        left = raw[k:]
        right = raw[:-k]
        mask = np.isfinite(left) & np.isfinite(right)
        n_k = int(mask.sum())
        pair_counts[k] = n_k
        if k <= horizon - 1 and n_k < min_pairs:
            result["reason"] = "insufficient_pairs_at_required_lag"
            result["pair_counts"] = pair_counts
            return result
        if n_k:
            covariance = float(((left[mask] - mean) * (right[mask] - mean)).sum() / n_obs)
        else:
            covariance = 0.0
        lrv += 2.0 * (1.0 - k / (lag + 1.0)) * covariance
    result["pair_counts"] = pair_counts
    result["lrv"] = float(lrv)
    if not np.isfinite(lrv) or lrv <= 0:
        warnings.warn(
            "newey-west long-run variance is not positive; t statistic unavailable",
            stacklevel=2,
        )
        result["reason"] = "nonpositive_lrv"
        return result
    result["kappa"] = float(lrv / gamma_0) if gamma_0 > 0 else None
    result["t_stat"] = float(mean / math.sqrt(lrv / n_obs))
    return result


def newey_west_t_statistic(
    values,
    *,
    lag: int,
    horizon: int = 1,
    min_observations: int | None = None,
    min_pairs: int = 30,
) -> float | None:
    """Newey-West t statistic of the series mean, or None when not measurable."""
    return newey_west_stats(
        values,
        lag=lag,
        horizon=horizon,
        min_observations=min_observations,
        min_pairs=min_pairs,
    )["t_stat"]


def summarize_ic_series(ic_frame: pd.DataFrame, *, horizon: int) -> dict:
    """Mean/IR (descriptive) plus the Newey-West t statistic (inference) of an IC series."""
    if ic_frame.empty:
        return {
            "ic_mean": None,
            "rank_ic_mean": None,
            "ic_std": None,
            "ic_ir": None,
            "rank_ic_ir": None,
            "nw_t": None,
            "nw_lag": None,
            "n_days": 0,
            "reason": "no_ic_days",
        }
    ic = pd.to_numeric(ic_frame["ic"], errors="coerce")
    rank_ic = pd.to_numeric(ic_frame["rank_ic"], errors="coerce")
    n_days = int(ic.dropna().size)

    def _ratio(series: pd.Series) -> tuple[float | None, float | None, float | None]:
        clean = series.dropna()
        n = len(clean)
        mean = float(clean.mean()) if n else None
        std = float(clean.std(ddof=1)) if n > 1 else None
        ratio = float(mean / std) if (mean is not None and std not in (None, 0.0)) else None
        return mean, std, ratio

    ic_mean, ic_std, ic_ir = _ratio(ic)
    rank_mean, _rank_std, rank_ir = _ratio(rank_ic)
    lag = newey_west_lag_rule(n_days, horizon=horizon)
    stats = newey_west_stats(ic.to_numpy(dtype=float), lag=lag, horizon=horizon)
    return {
        "ic_mean": ic_mean,
        "rank_ic_mean": rank_mean,
        "ic_std": ic_std,
        "ic_ir": ic_ir,
        "rank_ic_ir": rank_ir,
        "nw_t": stats["t_stat"],
        "nw_lag": lag,
        "n_days": n_days,
        "reason": stats["reason"],
    }
