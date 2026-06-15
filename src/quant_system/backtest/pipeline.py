from __future__ import annotations

from pathlib import Path
from time import perf_counter

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from quant_system.backtest.benchmark import (
    build_benchmark_curve,
    calculate_benchmark_metrics,
)
from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.metrics import PerformanceMetrics
from quant_system.backtest.models import BacktestConfig
from quant_system.backtest.reporting import generate_backtest_report
from quant_system.backtest.storage import LocalBacktestStorage
from quant_system.backtest.strategy import MeanReversionTopN, ScoreSignalStrategy
from quant_system.config.settings import Settings, load_settings
from quant_system.data.provider_factory import (
    DataProviderUnavailableError,
    build_ohlcv_provider,
)
from quant_system.experiments.models import FactorBlendConfig, FactorDirection, FactorWeight
from quant_system.experiments.scoring import build_multifactor_score_frame
from quant_system.factors.pipeline import (
    compute_factor_pipeline,
)
from quant_system.factors.registry import build_default_factor_registry
from quant_system.strategies.registry import build_default_strategy_registry
from quant_system.universe.registry import build_default_universe_registry


class BacktestRunResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str
    strategy_id: str
    universe_id: str | None
    symbols: list[str]
    factor_ids: list[str]
    weights: dict[str, float]
    benchmark_symbol: str
    trade_count: int
    order_count: int
    warnings: list[str] = Field(default_factory=list)
    equity_curve_path: Path
    trade_blotter_path: Path
    orders_path: Path
    positions_path: Path
    attribution_path: Path
    metrics_path: Path
    benchmark_curve_path: Path
    benchmark_metrics_path: Path
    report_path: Path
    total_return: float
    sharpe: float
    max_drawdown: float
    attribution: list[dict[str, float | str]] = Field(default_factory=list)
    benchmark_source: str
    benchmark_metrics: PerformanceMetrics
    timings_ms: dict[str, float] = Field(default_factory=dict)


def run_backtest(
    *,
    symbols: list[str],
    start: str,
    end: str,
    output_dir: str | Path | None = None,
    lookback: int = 20,
    top_n: int = 3,
    initial_cash: float = 100_000.0,
    commission_bps: float = 1.0,
    slippage_bps: float = 5.0,
    min_order_value: float = 0.0,
    whole_share_orders: bool = False,
    provider: str | None = None,
    strategy_id: str = "cross_sectional_top_n",
    universe_id: str | None = None,
    factor_ids: list[str] | None = None,
    weights: dict[str, float] | None = None,
    benchmark_symbol: str = "SPY",
    rebalance_frequency: str = "every_bar",
    max_weight_per_symbol: float | None = None,
    sector_cap: float | None = None,
    sector_map: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> BacktestRunResult:
    total_start = perf_counter()
    active_settings = settings or load_settings()
    resolved_symbols = _resolve_symbols(symbols=symbols, universe_id=universe_id)
    resolved_strategy_id = _resolve_strategy_id(strategy_id)
    resolved_factor_ids = _resolve_factor_ids(factor_ids)
    resolved_weights = {
        factor_id: float((weights or {}).get(factor_id, 1.0))
        for factor_id in resolved_factor_ids
    }
    ohlcv_provider, source = build_ohlcv_provider(active_settings, requested=provider)
    resolved_benchmark_symbol = benchmark_symbol.upper().strip() or "SPY"
    fetch_start = perf_counter()
    try:
        ohlcv = ohlcv_provider.fetch_ohlcv(resolved_symbols, start=start, end=end)
        benchmark_ohlcv = ohlcv_provider.fetch_ohlcv(
            [resolved_benchmark_symbol],
            start=start,
            end=end,
        )
    except Exception as exc:
        if provider is not None:
            raise DataProviderUnavailableError(provider, exc.__class__.__name__) from exc
        raise
    data_fetch_ms = _elapsed_ms(fetch_start)

    engine_start = perf_counter()
    factors = _create_factors(resolved_factor_ids, lookback=lookback)
    factor_results = compute_factor_pipeline(ohlcv, factors=factors)
    signal_frame = build_multifactor_score_frame(
        factor_results,
        _build_factor_blend_config(
            factor_ids=resolved_factor_ids,
            weights=resolved_weights,
        ),
    )
    config = BacktestConfig(
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        min_order_value=min_order_value,
        whole_share_orders=whole_share_orders,
        rebalance_frequency=rebalance_frequency,
        max_weight_per_symbol=max_weight_per_symbol,
        sector_cap=sector_cap,
        sector_map=sector_map or {},
    )
    strategy = _build_backtest_strategy(
        resolved_strategy_id, signal_frame, top_n=top_n
    )
    result = BacktestEngine(config).run(ohlcv, strategy)
    benchmark_curve = build_benchmark_curve(benchmark_ohlcv, symbol=resolved_benchmark_symbol)
    benchmark_metrics = calculate_benchmark_metrics(benchmark_curve)
    engine_ms = _elapsed_ms(engine_start)

    persist_start = perf_counter()
    storage = _build_storage(output_dir, settings=active_settings)
    equity_curve_path = storage.save_frame(
        result.equity_curve,
        filename="equity_curve.parquet",
        table_name="backtest_equity_curve",
    )
    trade_blotter_path = storage.save_frame(
        result.trade_blotter,
        filename="trade_blotter.parquet",
        table_name="backtest_trade_blotter",
    )
    orders_path = storage.save_frame(
        result.orders,
        filename="orders.parquet",
        table_name="backtest_orders",
    )
    positions_path = storage.save_frame(
        result.positions,
        filename="positions.parquet",
        table_name="backtest_positions",
    )
    attribution_path = storage.save_frame(
        result.attribution,
        filename="attribution.parquet",
        table_name="backtest_attribution",
    )
    metrics_path = storage.save_metrics(result.metrics)
    benchmark_curve_path = storage.save_frame(
        benchmark_curve,
        filename="benchmark_curve.parquet",
        table_name="backtest_benchmark_curve",
    )
    benchmark_metrics_path = storage.save_metrics(
        benchmark_metrics,
        filename="benchmark_metrics.json",
    )
    report = generate_backtest_report(
        metrics=result.metrics,
        config=config,
        trade_count=len(result.trade_blotter),
        equity_rows=len(result.equity_curve),
    )
    report_path = storage.save_report(report)
    persist_ms = _elapsed_ms(persist_start)
    timings_ms = {
        "data_fetch": data_fetch_ms,
        "engine": engine_ms,
        "persist": persist_ms,
        "total": _elapsed_ms(total_start),
    }
    return BacktestRunResult(
        source=source,
        strategy_id=resolved_strategy_id,
        universe_id=universe_id,
        symbols=resolved_symbols,
        factor_ids=resolved_factor_ids,
        weights=resolved_weights,
        benchmark_symbol=resolved_benchmark_symbol,
        trade_count=len(result.trade_blotter),
        order_count=len(result.orders),
        warnings=_build_backtest_warnings(
            ohlcv=ohlcv,
            signal_frame=signal_frame,
            trade_blotter=result.trade_blotter,
        ),
        equity_curve_path=equity_curve_path,
        trade_blotter_path=trade_blotter_path,
        orders_path=orders_path,
        positions_path=positions_path,
        attribution_path=attribution_path,
        metrics_path=metrics_path,
        benchmark_curve_path=benchmark_curve_path,
        benchmark_metrics_path=benchmark_metrics_path,
        report_path=report_path,
        total_return=result.metrics.total_return,
        sharpe=result.metrics.sharpe,
        max_drawdown=result.metrics.max_drawdown,
        attribution=result.metrics.attribution,
        benchmark_source=source,
        benchmark_metrics=benchmark_metrics,
        timings_ms=timings_ms,
    )


def run_sample_backtest(
    *,
    symbols: list[str],
    start: str,
    end: str,
    output_dir: str | Path | None = None,
    lookback: int = 20,
    top_n: int = 3,
    initial_cash: float = 100_000.0,
    commission_bps: float = 1.0,
    slippage_bps: float = 5.0,
) -> BacktestRunResult:
    return run_backtest(
        symbols=symbols,
        start=start,
        end=end,
        output_dir=output_dir,
        lookback=lookback,
        top_n=top_n,
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        provider="sample",
    )


def _resolve_symbols(*, symbols: list[str], universe_id: str | None) -> list[str]:
    normalized = [symbol.upper().strip() for symbol in symbols if symbol.strip()]
    if normalized:
        return normalized
    if universe_id:
        return build_default_universe_registry().get(universe_id).normalized_symbols()
    return ["SPY", "QQQ"]


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


# Maps a registered strategy id to a constructor that turns the prepared
# multifactor ``signal_frame`` into a backtest strategy. Adding a new
# ``result_type="backtest"`` strategy is a two-step change: register its
# metadata in ``strategies/registry.py`` and add a builder here. The strategy
# only needs to expose ``target_weights(ts) -> list[TargetWeight] | None``.
_BACKTEST_STRATEGY_BUILDERS = {
    "cross_sectional_top_n": lambda signal_frame, top_n: ScoreSignalStrategy(
        signal_frame, top_n=top_n, target_gross_exposure=1.0
    ),
    "mean_reversion_top_n": lambda signal_frame, top_n: MeanReversionTopN(
        signal_frame, top_n=top_n, target_gross_exposure=1.0
    ),
}


def _resolve_strategy_id(strategy_id: str) -> str:
    normalized = strategy_id.strip() or "cross_sectional_top_n"
    # Must be a registered strategy...
    build_default_strategy_registry().get(normalized)
    # ...and one the backtest engine knows how to construct.
    if normalized not in _BACKTEST_STRATEGY_BUILDERS:
        runnable = ", ".join(sorted(_BACKTEST_STRATEGY_BUILDERS))
        raise ValueError(
            f"strategy {normalized!r} is registered but is not runnable by the "
            f"backtest engine (runnable strategies: {runnable})"
        )
    return normalized


def _build_backtest_strategy(strategy_id: str, signal_frame: pd.DataFrame, *, top_n: int):
    return _BACKTEST_STRATEGY_BUILDERS[strategy_id](signal_frame, top_n)


def _resolve_factor_ids(factor_ids: list[str] | None) -> list[str]:
    registry = build_default_factor_registry()
    normalized = [factor_id.strip() for factor_id in factor_ids or [] if factor_id.strip()]
    if not normalized:
        return registry.factor_ids()
    for factor_id in normalized:
        registry.create(factor_id)
    return normalized


def _create_factors(factor_ids: list[str], *, lookback: int):
    registry = build_default_factor_registry()
    return [
        registry.create(factor_id, lookback=lookback)
        for factor_id in factor_ids
    ]


def _build_factor_blend_config(
    *,
    factor_ids: list[str],
    weights: dict[str, float],
) -> FactorBlendConfig:
    metadata = {
        item.factor_id: item
        for item in build_default_factor_registry().list_metadata()
    }
    return FactorBlendConfig(
        factors=[
            FactorWeight(
                factor_id=factor_id,
                weight=weights.get(factor_id, 1.0),
                direction=(
                    FactorDirection.LOWER_IS_BETTER
                    if metadata[factor_id].direction == "lower_is_better"
                    else FactorDirection.HIGHER_IS_BETTER
                ),
            )
            for factor_id in factor_ids
        ]
    )


def _build_backtest_warnings(
    *,
    ohlcv: pd.DataFrame,
    signal_frame: pd.DataFrame,
    trade_blotter: pd.DataFrame,
) -> list[str]:
    warnings: list[str] = []
    symbol_count = (
        int(ohlcv["symbol"].astype(str).str.upper().str.strip().nunique())
        if "symbol" in ohlcv.columns and not ohlcv.empty
        else 0
    )
    if symbol_count < 2:
        warnings.append(
            "Single symbol run: this backtest strategy ranks a universe and buys "
            "the top positive scores. Add peer symbols such as META, AAPL, MSFT, "
            "GOOGL, QQQ, and SPY for a useful strategy replay."
        )
    if signal_frame.empty:
        warnings.append(
            "No signal rows were produced, so the backtest had nothing to trade."
        )
    elif "score" in signal_frame.columns and (
        pd.to_numeric(signal_frame["score"], errors="coerce").fillna(0.0).abs().max() == 0
    ):
        warnings.append(
            "All strategy scores are zero, so the long-only ranking strategy did "
            "not find any positive signals to buy."
        )
    if trade_blotter.empty:
        warnings.append(
            "No simulated trades were generated; metrics can stay at zero until "
            "the input universe produces positive ranked signals."
        )
    return warnings


def _build_storage(
    output_dir: str | Path | None,
    *,
    settings: Settings | None = None,
) -> LocalBacktestStorage:
    if output_dir is not None:
        return LocalBacktestStorage(base_dir=output_dir, write_duckdb=False)
    data_settings = (settings or load_settings()).data
    return LocalBacktestStorage(
        base_dir=data_settings.data_dir,
        reports_dir=data_settings.reports_dir,
        duckdb_path=data_settings.duckdb_path,
    )
