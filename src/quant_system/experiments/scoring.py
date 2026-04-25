from __future__ import annotations

import pandas as pd

from quant_system.experiments.models import FactorBlendConfig, FactorDirection


def build_multifactor_score_frame(
    factor_results: pd.DataFrame,
    config: FactorBlendConfig,
) -> pd.DataFrame:
    if factor_results.empty:
        return pd.DataFrame(columns=["symbol", "signal_ts", "tradeable_ts", "score"])

    required = {"symbol", "signal_ts", "tradeable_ts", "factor_id", "value"}
    missing = required.difference(factor_results.columns)
    if missing:
        raise ValueError(f"missing required factor result columns: {', '.join(sorted(missing))}")

    frames: list[pd.DataFrame] = []
    total_abs_weight = sum(abs(factor.weight) for factor in config.factors) or 1.0
    for factor in config.factors:
        subset = factor_results[factor_results["factor_id"] == factor.factor_id].copy()
        if subset.empty:
            continue
        subset["signal_ts"] = pd.to_datetime(subset["signal_ts"], utc=True)
        subset["tradeable_ts"] = pd.to_datetime(subset["tradeable_ts"], utc=True)
        subset["value"] = pd.to_numeric(subset["value"], errors="coerce")
        zscore = subset.groupby("signal_ts")["value"].transform(_cross_sectional_zscore)
        direction_multiplier = -1.0 if factor.direction == FactorDirection.LOWER_IS_BETTER else 1.0
        subset[factor.factor_id] = zscore * direction_multiplier * factor.weight / total_abs_weight
        frames.append(
            subset.loc[:, ["symbol", "signal_ts", "tradeable_ts", factor.factor_id]]
        )

    if not frames:
        return pd.DataFrame(columns=["symbol", "signal_ts", "tradeable_ts", "score"])

    wide = frames[0]
    for frame in frames[1:]:
        wide = wide.merge(frame, on=["symbol", "signal_ts", "tradeable_ts"], how="outer")
    factor_columns = [
        factor.factor_id for factor in config.factors if factor.factor_id in wide.columns
    ]
    wide[factor_columns] = wide[factor_columns].fillna(0.0)
    wide["score"] = wide[factor_columns].sum(axis=1)
    wide = wide.sort_values(["tradeable_ts", "symbol"], ignore_index=True)
    return _filter_rebalance_dates(wide, every_n_bars=config.rebalance_every_n_bars)


def _cross_sectional_zscore(values: pd.Series) -> pd.Series:
    clean = pd.to_numeric(values, errors="coerce")
    mean = clean.mean()
    std = clean.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=values.index)
    return (clean - mean) / std


def _filter_rebalance_dates(frame: pd.DataFrame, *, every_n_bars: int) -> pd.DataFrame:
    if every_n_bars <= 1 or frame.empty:
        return frame.reset_index(drop=True)
    dates = list(pd.Series(frame["tradeable_ts"]).drop_duplicates())
    keep_dates = set(dates[::every_n_bars])
    return frame[frame["tradeable_ts"].isin(keep_dates)].reset_index(drop=True)
