from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant_system.data.provider_factory import DataProviderUnavailableError, build_ohlcv_provider
from quant_system.experiments.models import WalkForwardConfig
from quant_system.experiments.walk_forward import build_walk_forward_splits
from quant_system.factors.evaluation import (
    calculate_information_coefficients,
    calculate_quantile_returns,
    make_forward_returns,
)
from quant_system.factors.pipeline import compute_factor_pipeline
from quant_system.factors.registry import build_factor_registry
from quant_system.universe.registry import build_default_universe_registry


def build_factor_lab_dashboard(
    *,
    settings,
    output_dir: str | Path,
    provider: str = "sample",
    universe_id: str = "etf",
    symbol: str = "QQQ",
    benchmark_symbol: str = "QQQ",
    start: str = "2024-01-02",
    end: str = "2024-12-31",
    lookback: int = 20,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cache_path = Path(output_dir) / "factor_lab" / "factor_lab_cache.json"
    cache_key = {
        "provider": provider,
        "universe_id": universe_id,
        "symbol": symbol.upper().strip(),
        "benchmark_symbol": benchmark_symbol.upper().strip(),
        "start": start,
        "end": end,
        "lookback": lookback,
    }
    if not force_refresh and cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("cache", {}).get("key") == cache_key:
            cached["cache"]["status"] = "cached"
            return cached

    registry = build_factor_registry()
    universe = build_default_universe_registry().get(universe_id)
    symbols = sorted(set(universe.normalized_symbols()).union({symbol.upper().strip()}))
    provider_instance, source = build_ohlcv_provider(settings, requested=provider)
    try:
        ohlcv = provider_instance.fetch_ohlcv(symbols, start=start, end=end)
    except Exception as exc:
        raise DataProviderUnavailableError(provider, exc.__class__.__name__) from exc
    factors = [registry.create(factor_id, lookback=lookback) for factor_id in registry.factor_ids()]
    factor_results = compute_factor_pipeline(ohlcv, factors=factors)
    factor_metadata = registry.list_metadata()

    walk_forward = WalkForwardConfig(
        enabled=True,
        train_bars=60,
        validation_bars=20,
        step_bars=20,
    )
    splits = build_walk_forward_splits(
        ohlcv["timestamp"].drop_duplicates().sort_values(),
        walk_forward,
    )
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source,
        "benchmark_symbol": benchmark_symbol.upper().strip() or "QQQ",
        "universe": universe.model_dump(mode="json"),
        "factors": [metadata.model_dump(mode="json") for metadata in factor_metadata],
        "guardrails": {
            "exploratory_only": True,
            "warning": (
                "Factor Lab is exploratory and easy to overfit. Use walk-forward "
                "validation and leakage review before promoting a factor."
            ),
            "walk_forward": {
                **walk_forward.model_dump(mode="json"),
                "fold_count": len(splits),
            },
            "leakage_audit": _basic_leakage_audit(factor_results),
        },
        "cache": {
            "status": "recomputed",
            "path": str(cache_path),
            "key": cache_key,
        },
        "cross_sectional": {
            "engine": "cross_sectional_health",
            "rows": _cross_sectional_rows(factor_results, ohlcv, factor_metadata),
        },
        "timing": {
            "engine": "single_symbol_timing",
            "symbol": symbol.upper().strip() or "QQQ",
            "rows": _timing_rows(
                factor_results,
                ohlcv,
                factor_metadata,
                symbol=symbol.upper().strip() or "QQQ",
                lookback=lookback,
            ),
        },
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    return payload


def _cross_sectional_rows(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    factor_metadata,
) -> list[dict[str, Any]]:
    ic_h1 = calculate_information_coefficients(factor_results, ohlcv, horizon=1)
    ic_h5 = calculate_information_coefficients(factor_results, ohlcv, horizon=5)
    quantiles = calculate_quantile_returns(factor_results, ohlcv, quantiles=5, horizon=1)
    possible = _max_possible_rows(factor_results)
    rows: list[dict[str, Any]] = []
    for metadata in factor_metadata:
        factor_id = metadata.factor_id
        subset = factor_results[factor_results["factor_id"] == factor_id]
        ic_1 = _mean_numeric(ic_h1[ic_h1["factor_id"] == factor_id], "rank_ic")
        ic_5 = _mean_numeric(ic_h5[ic_h5["factor_id"] == factor_id], "rank_ic")
        rows.append(
            {
                "factor_id": factor_id,
                "factor_name": metadata.factor_name,
                "direction": metadata.direction,
                "ic_mean": _safe_float(ic_1),
                "ic_decay": _safe_float((ic_5 or 0.0) - (ic_1 or 0.0)),
                "quantile_spread": _safe_float(_quantile_spread(quantiles, factor_id)),
                "turnover": _safe_float(_factor_turnover(subset, metadata.direction)),
                "coverage": _safe_float(len(subset) / possible if possible else 0.0),
                "sample_count": int(len(subset)),
            }
        )
    return rows


def _timing_rows(
    factor_results: pd.DataFrame,
    ohlcv: pd.DataFrame,
    factor_metadata,
    *,
    symbol: str,
    lookback: int,
) -> list[dict[str, Any]]:
    returns = make_forward_returns(ohlcv[ohlcv["symbol"] == symbol], horizon=1)
    rows: list[dict[str, Any]] = []
    for metadata in factor_metadata:
        subset = factor_results[
            (factor_results["factor_id"] == metadata.factor_id)
            & (factor_results["symbol"] == symbol)
        ].copy()
        if subset.empty:
            rows.append(_empty_timing_row(metadata))
            continue
        subset["signal_ts"] = pd.to_datetime(subset["signal_ts"], utc=True)
        subset["value"] = pd.to_numeric(subset["value"], errors="coerce")
        subset["zscore"] = _rolling_zscore(subset["value"], lookback=lookback)
        direction = -1.0 if metadata.direction == "lower_is_better" else 1.0
        subset["position"] = ((subset["zscore"] * direction) > 0).astype(float)
        merged = subset.merge(
            returns,
            on=["symbol", "signal_ts"],
            how="inner",
        ).dropna(subset=["forward_return"])
        merged["strategy_return"] = merged["position"] * merged["forward_return"]
        rows.append(
            {
                "factor_id": metadata.factor_id,
                "factor_name": metadata.factor_name,
                "sharpe": _safe_float(_sharpe(merged["strategy_return"])),
                "max_drawdown": _safe_float(_max_drawdown(merged["strategy_return"])),
                "win_rate": _safe_float(_win_rate(merged)),
                "trade_count": int(merged["position"].diff().abs().fillna(0).sum()),
                "coverage": _safe_float(
                    len(merged.dropna(subset=["zscore"])) / max(len(subset), 1)
                ),
            }
        )
    return rows


def _empty_timing_row(metadata) -> dict[str, Any]:
    return {
        "factor_id": metadata.factor_id,
        "factor_name": metadata.factor_name,
        "sharpe": 0.0,
        "max_drawdown": 0.0,
        "win_rate": 0.0,
        "trade_count": 0,
        "coverage": 0.0,
    }


def _basic_leakage_audit(factor_results: pd.DataFrame) -> dict[str, Any]:
    if factor_results.empty:
        return {"status": "empty", "checked": False}
    signal_ts = pd.to_datetime(factor_results["signal_ts"], utc=True)
    tradeable_ts = pd.to_datetime(factor_results["tradeable_ts"], utc=True)
    passed = bool((tradeable_ts > signal_ts).all())
    return {
        "status": "basic_passed" if passed else "failed",
        "checked": True,
        "rule": "tradeable_ts must be later than signal_ts",
    }


def _max_possible_rows(factor_results: pd.DataFrame) -> int:
    if factor_results.empty:
        return 0
    symbols = int(factor_results["symbol"].nunique())
    dates = int(factor_results["signal_ts"].nunique())
    return max(symbols * dates, 1)


def _mean_numeric(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _quantile_spread(frame: pd.DataFrame, factor_id: str) -> float | None:
    subset = frame[frame["factor_id"] == factor_id]
    if subset.empty:
        return None
    values = subset.sort_values("quantile")
    low = pd.to_numeric(values.iloc[0]["mean_forward_return"], errors="coerce")
    high = pd.to_numeric(values.iloc[-1]["mean_forward_return"], errors="coerce")
    if pd.isna(low) or pd.isna(high):
        return None
    return float(high - low)


def _factor_turnover(subset: pd.DataFrame, direction: str) -> float:
    if subset.empty:
        return 0.0
    previous: set[str] | None = None
    turnovers: list[float] = []
    for _timestamp, group in subset.groupby("signal_ts", sort=True):
        group = group.dropna(subset=["value"]).copy()
        if group.empty:
            continue
        ascending = direction == "lower_is_better"
        count = max(1, len(group) // 2)
        selected = set(
            group.sort_values("value", ascending=ascending).head(count)["symbol"].astype(str)
        )
        if previous is not None:
            denom = max(len(previous.union(selected)), 1)
            turnovers.append(len(previous.symmetric_difference(selected)) / denom)
        previous = selected
    return float(np.mean(turnovers)) if turnovers else 0.0


def _rolling_zscore(values: pd.Series, *, lookback: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    rolling = numeric.rolling(max(lookback, 2), min_periods=max(lookback, 2))
    mean = rolling.mean()
    std = rolling.std(ddof=0).replace(0, np.nan)
    return (numeric - mean) / std


def _sharpe(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    std = clean.std(ddof=0)
    if pd.isna(std) or std == 0:
        return 0.0
    return float(clean.mean() / std * np.sqrt(252))


def _max_drawdown(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min())


def _win_rate(frame: pd.DataFrame) -> float:
    active = frame[frame["position"] > 0]
    if active.empty:
        return 0.0
    return float((active["strategy_return"] > 0).mean())


def _safe_float(value: float | int | None) -> float:
    if value is None:
        return 0.0
    numeric = float(value)
    if not np.isfinite(numeric):
        return 0.0
    return numeric
