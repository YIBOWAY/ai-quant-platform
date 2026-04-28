from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

from quant_system.config.settings import load_settings
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.factors.base import FACTOR_RESULT_COLUMNS, BaseFactor
from quant_system.factors.evaluation import (
    calculate_information_coefficients,
    calculate_quantile_returns,
)
from quant_system.factors.examples import (
    LiquidityFactor,
    MACDFactor,
    MomentumFactor,
    RSIFactor,
    VolatilityFactor,
)
from quant_system.factors.reporting import generate_factor_report
from quant_system.factors.storage import LocalFactorStorage


class FactorResearchResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    row_count: int
    signal_count: int
    factor_results_path: Path
    signal_frame_path: Path
    ic_path: Path
    quantile_returns_path: Path
    report_path: Path


def compute_factor_pipeline(
    ohlcv: pd.DataFrame,
    *,
    factors: list[BaseFactor],
) -> pd.DataFrame:
    if not factors:
        raise ValueError("at least one factor is required")

    outputs = [factor.compute(ohlcv) for factor in factors]
    if not outputs:
        return pd.DataFrame(columns=FACTOR_RESULT_COLUMNS)
    return pd.concat(outputs, ignore_index=True).sort_values(
        ["factor_id", "symbol", "signal_ts"],
        ignore_index=True,
    )


def build_factor_signal_frame(factor_results: pd.DataFrame) -> pd.DataFrame:
    """Combine factor values into a per-symbol score frame.

    Each factor is z-scored cross-sectionally at every ``signal_ts`` so that
    factors with very different scales (for example momentum returns versus
    log-dollar volume) contribute comparably to the final score. The score is
    the mean of standardized factor values.
    """
    if factor_results.empty:
        return pd.DataFrame(columns=["symbol", "signal_ts", "tradeable_ts", "score"])

    required = {"symbol", "signal_ts", "tradeable_ts", "factor_id", "value"}
    missing = required.difference(factor_results.columns)
    if missing:
        raise ValueError(f"missing required factor result columns: {', '.join(sorted(missing))}")

    factors = factor_results.copy()
    factors["signal_ts"] = pd.to_datetime(factors["signal_ts"], utc=True)
    factors["tradeable_ts"] = pd.to_datetime(factors["tradeable_ts"], utc=True)
    factors["value"] = pd.to_numeric(factors["value"], errors="coerce")
    factors["zscore"] = factors.groupby(["factor_id", "signal_ts"])["value"].transform(
        _cross_sectional_zscore
    )
    wide = (
        factors.pivot_table(
            index=["symbol", "signal_ts", "tradeable_ts"],
            columns="factor_id",
            values="zscore",
            aggfunc="last",
        )
        .reset_index()
        .rename_axis(None, axis=1)
    )
    factor_columns = [
        column
        for column in wide.columns
        if column not in {"symbol", "signal_ts", "tradeable_ts"}
    ]
    wide[factor_columns] = wide[factor_columns].fillna(0.0)
    wide["score"] = wide[factor_columns].mean(axis=1)
    return wide.sort_values(["signal_ts", "symbol"], ignore_index=True)


def _cross_sectional_zscore(values: pd.Series) -> pd.Series:
    clean = pd.to_numeric(values, errors="coerce")
    mean = clean.mean()
    std = clean.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=values.index)
    return (clean - mean) / std


def run_sample_factor_research(
    *,
    symbols: list[str],
    start: str,
    end: str,
    output_dir: str | Path | None = None,
    lookback: int = 20,
    quantiles: int = 5,
) -> FactorResearchResult:
    provider = SampleOHLCVProvider()
    ohlcv = provider.fetch_ohlcv(symbols, start=start, end=end)
    factors: list[BaseFactor] = [
        MomentumFactor(lookback=lookback),
        VolatilityFactor(lookback=lookback),
        LiquidityFactor(lookback=lookback),
        RSIFactor(lookback=lookback),
        MACDFactor(lookback=lookback),
    ]
    factor_results = compute_factor_pipeline(ohlcv, factors=factors)
    signal_frame = build_factor_signal_frame(factor_results)
    ic_frame = calculate_information_coefficients(factor_results, ohlcv, horizon=1)
    quantile_frame = calculate_quantile_returns(
        factor_results,
        ohlcv,
        quantiles=quantiles,
        horizon=1,
    )
    report = generate_factor_report(
        factor_results=factor_results,
        signal_frame=signal_frame,
        ic_frame=ic_frame,
        quantile_frame=quantile_frame,
    )
    storage = _build_storage(output_dir)
    factor_results_path = storage.save_factor_results(factor_results)
    signal_frame_path = storage.save_signal_frame(signal_frame)
    ic_path = storage.save_information_coefficients(ic_frame)
    quantile_returns_path = storage.save_quantile_returns(quantile_frame)
    report_path = storage.save_report(report)
    return FactorResearchResult(
        row_count=len(factor_results),
        signal_count=len(signal_frame),
        factor_results_path=factor_results_path,
        signal_frame_path=signal_frame_path,
        ic_path=ic_path,
        quantile_returns_path=quantile_returns_path,
        report_path=report_path,
    )


def _build_storage(output_dir: str | Path | None) -> LocalFactorStorage:
    if output_dir is not None:
        return LocalFactorStorage(base_dir=output_dir)
    data_settings = load_settings().data
    return LocalFactorStorage(
        base_dir=data_settings.data_dir,
        reports_dir=data_settings.reports_dir,
        duckdb_path=data_settings.duckdb_path,
    )
