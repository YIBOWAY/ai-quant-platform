from __future__ import annotations

import pandas as pd


def make_forward_returns(ohlcv: pd.DataFrame, *, horizon: int = 1) -> pd.DataFrame:
    if horizon <= 0:
        raise ValueError("horizon must be greater than zero")
    required = {"symbol", "timestamp", "close"}
    missing = required.difference(ohlcv.columns)
    if missing:
        raise ValueError(f"missing required OHLCV columns: {', '.join(sorted(missing))}")

    frame = ohlcv.loc[:, ["symbol", "timestamp", "close"]].copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.sort_values(["symbol", "timestamp"], ignore_index=True)
    grouped = frame.groupby("symbol", sort=False)
    frame["return_end_ts"] = grouped["timestamp"].shift(-horizon)
    frame["future_close"] = grouped["close"].shift(-horizon)
    frame["forward_return"] = frame["future_close"] / frame["close"] - 1.0
    frame = frame.rename(columns={"timestamp": "signal_ts"})
    return frame.loc[:, ["symbol", "signal_ts", "return_end_ts", "forward_return"]].dropna(
        subset=["return_end_ts", "forward_return"]
    )


def _spearman_without_scipy(left: pd.Series, right: pd.Series) -> float:
    return left.rank(method="average").corr(right.rank(method="average"), method="pearson")


def _merge_factor_with_returns(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizon: int,
) -> pd.DataFrame:
    required = {"symbol", "signal_ts", "factor_id", "value"}
    missing = required.difference(factor_results.columns)
    if missing:
        raise ValueError(f"missing required factor result columns: {', '.join(sorted(missing))}")

    factors = factor_results.copy()
    factors["symbol"] = factors["symbol"].astype(str).str.upper().str.strip()
    factors["signal_ts"] = pd.to_datetime(factors["signal_ts"], utc=True)
    returns = make_forward_returns(ohlcv, horizon=horizon)
    return factors.merge(returns, on=["symbol", "signal_ts"], how="inner")


def calculate_information_coefficients(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizon: int = 1,
) -> pd.DataFrame:
    merged = _merge_factor_with_returns(factor_results, ohlcv, horizon=horizon)
    rows: list[dict[str, object]] = []
    for (factor_id, signal_ts), group in merged.groupby(["factor_id", "signal_ts"], sort=True):
        clean = group.dropna(subset=["value", "forward_return"])
        n = len(clean)
        ic = float("nan")
        rank_ic = float("nan")
        if n >= 2 and clean["value"].nunique() > 1 and clean["forward_return"].nunique() > 1:
            ic = clean["value"].corr(clean["forward_return"], method="pearson")
            rank_ic = _spearman_without_scipy(clean["value"], clean["forward_return"])
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


def calculate_quantile_returns(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    quantiles: int = 5,
    horizon: int = 1,
) -> pd.DataFrame:
    if quantiles < 2:
        raise ValueError("quantiles must be at least two")
    merged = _merge_factor_with_returns(factor_results, ohlcv, horizon=horizon)
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

    if not bucketed:
        return pd.DataFrame(
            columns=[
                "factor_id",
                "quantile",
                "mean_forward_return",
                "median_forward_return",
                "count",
            ]
        )

    combined = pd.concat(bucketed, ignore_index=True)
    return (
        combined.groupby(["factor_id", "quantile"], as_index=False)
        .agg(
            mean_forward_return=("forward_return", "mean"),
            median_forward_return=("forward_return", "median"),
            count=("forward_return", "count"),
        )
        .sort_values(["factor_id", "quantile"], ignore_index=True)
    )
