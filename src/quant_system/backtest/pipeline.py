from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.backtest.reporting import generate_backtest_report
from quant_system.backtest.storage import LocalBacktestStorage
from quant_system.backtest.strategy import ScoreSignalStrategy
from quant_system.config.settings import load_settings
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.factors.examples import LiquidityFactor, MomentumFactor, VolatilityFactor
from quant_system.factors.pipeline import build_factor_signal_frame, compute_factor_pipeline


class BacktestRunResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    equity_curve_path: Path
    trade_blotter_path: Path
    orders_path: Path
    positions_path: Path
    metrics_path: Path
    report_path: Path
    total_return: float
    sharpe: float
    max_drawdown: float


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
    provider = SampleOHLCVProvider()
    ohlcv = provider.fetch_ohlcv(symbols, start=start, end=end)
    factors = [
        MomentumFactor(lookback=lookback),
        VolatilityFactor(lookback=lookback),
        LiquidityFactor(lookback=lookback),
    ]
    factor_results = compute_factor_pipeline(ohlcv, factors=factors)
    signal_frame = build_factor_signal_frame(factor_results)
    config = BacktestConfig(
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )
    strategy = ScoreSignalStrategy(signal_frame, top_n=top_n, target_gross_exposure=1.0)
    result = BacktestEngine(config).run(ohlcv, strategy)
    storage = _build_storage(output_dir)
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
    metrics_path = storage.save_metrics(result.metrics)
    report = generate_backtest_report(
        metrics=result.metrics,
        config=config,
        trade_count=len(result.trade_blotter),
        equity_rows=len(result.equity_curve),
    )
    report_path = storage.save_report(report)
    return BacktestRunResult(
        equity_curve_path=equity_curve_path,
        trade_blotter_path=trade_blotter_path,
        orders_path=orders_path,
        positions_path=positions_path,
        metrics_path=metrics_path,
        report_path=report_path,
        total_return=result.metrics.total_return,
        sharpe=result.metrics.sharpe,
        max_drawdown=result.metrics.max_drawdown,
    )


def _build_storage(output_dir: str | Path | None) -> LocalBacktestStorage:
    if output_dir is not None:
        return LocalBacktestStorage(base_dir=output_dir)
    data_settings = load_settings().data
    return LocalBacktestStorage(
        base_dir=data_settings.data_dir,
        reports_dir=data_settings.reports_dir,
        duckdb_path=data_settings.duckdb_path,
    )
