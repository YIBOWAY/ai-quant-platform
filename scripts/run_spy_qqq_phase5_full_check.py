from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig
from quant_system.backtest.reporting import generate_backtest_report
from quant_system.backtest.storage import LocalBacktestStorage
from quant_system.backtest.strategy import ScoreSignalStrategy
from quant_system.config.settings import load_settings
from quant_system.data.providers.sample import SampleOHLCVProvider
from quant_system.data.providers.tiingo import TiingoEODProvider
from quant_system.execution.pipeline import PaperTradingRunResult, run_signal_paper_trading
from quant_system.experiments.models import FactorBlendConfig, FactorDirection, FactorWeight
from quant_system.experiments.scoring import build_multifactor_score_frame
from quant_system.factors.base import BaseFactor
from quant_system.factors.examples import (
    LiquidityFactor,
    MACDFactor,
    MomentumFactor,
    RSIFactor,
    VolatilityFactor,
)
from quant_system.factors.pipeline import compute_factor_pipeline

SYMBOLS = ["SPY", "QQQ"]


def main() -> None:
    args = _parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ohlcv, source, source_note = _load_ohlcv(
        source=args.source,
        start=args.start,
        end=args.end,
    )
    input_dir = output_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    ohlcv.to_parquet(input_dir / "ohlcv.parquet", index=False)

    factor_results = compute_factor_pipeline(ohlcv, factors=_all_factors())
    factors_dir = output_dir / "factors"
    factors_dir.mkdir(parents=True, exist_ok=True)
    factor_results.to_parquet(factors_dir / "factor_results.parquet", index=False)

    strategy_outputs: list[dict[str, Any]] = []
    for strategy_name, config in _strategy_configs().items():
        score_frame = build_multifactor_score_frame(factor_results, config)
        strategy_dir = output_dir / "strategies" / strategy_name
        strategy_dir.mkdir(parents=True, exist_ok=True)
        score_frame.to_parquet(strategy_dir / "score_frame.parquet", index=False)

        backtest_summary = _run_backtest(
            ohlcv=ohlcv,
            score_frame=score_frame,
            output_dir=strategy_dir / "backtest",
            top_n=args.top_n,
            target_gross_exposure=args.target_gross_exposure,
            initial_cash=args.initial_cash,
            commission_bps=args.commission_bps,
            slippage_bps=args.slippage_bps,
        )
        paper_result = run_signal_paper_trading(
            ohlcv=ohlcv,
            signal_frame=score_frame,
            output_dir=strategy_dir / "paper",
            top_n=args.top_n,
            target_gross_exposure=args.target_gross_exposure,
            initial_cash=args.initial_cash,
            max_position_size=args.max_position_size,
            max_order_value=args.max_order_value,
            kill_switch=False,
            commission_bps=args.commission_bps,
            slippage_bps=args.slippage_bps,
        )
        strategy_outputs.append(
            {
                "strategy": strategy_name,
                "backtest": backtest_summary,
                "paper": _paper_summary(paper_result),
                "score_rows": int(len(score_frame)),
            }
        )

    summary = {
        "source": source,
        "source_note": source_note,
        "symbols": SYMBOLS,
        "start": args.start,
        "end": args.end,
        "rows": int(len(ohlcv)),
        "factor_rows": int(len(factor_results)),
        "target_gross_exposure": args.target_gross_exposure,
        "strategies": strategy_outputs,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    _write_markdown_report(output_dir / "summary.md", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 0-5 SPY+QQQ full check.")
    parser.add_argument("--source", choices=["auto", "tiingo", "sample"], default="auto")
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--output-dir", default="data/phase5_spy_qqq_full_check")
    parser.add_argument("--initial-cash", type=float, default=100_000.0)
    parser.add_argument("--commission-bps", type=float, default=1.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--target-gross-exposure", type=float, default=0.50)
    parser.add_argument("--top-n", type=int, default=1)
    parser.add_argument("--max-position-size", type=float, default=0.60)
    parser.add_argument("--max-order-value", type=float, default=75_000.0)
    return parser.parse_args()


def _load_ohlcv(*, source: str, start: str, end: str) -> tuple[pd.DataFrame, str, str]:
    if source in {"auto", "tiingo"}:
        token = load_settings().api_keys.tiingo_api_token
        if token is not None:
            try:
                provider = TiingoEODProvider(api_token=token)
                frame = provider.fetch_ohlcv(SYMBOLS, start=start, end=end)
                return frame, "tiingo", "Tiingo EOD data loaded successfully."
            except Exception as exc:
                if source == "tiingo":
                    raise
                note = f"Tiingo failed; used sample fallback. Error type: {type(exc).__name__}"
                return _sample_frame(start=start, end=end), "sample", note
        if source == "tiingo":
            raise ValueError("QS_TIINGO_API_TOKEN is required when --source tiingo is used")
    return _sample_frame(start=start, end=end), "sample", "Sample OHLCV fallback was used."


def _sample_frame(*, start: str, end: str) -> pd.DataFrame:
    return SampleOHLCVProvider().fetch_ohlcv(SYMBOLS, start=start, end=end)


def _all_factors() -> list[BaseFactor]:
    return [
        MomentumFactor(lookback=20),
        VolatilityFactor(lookback=20),
        LiquidityFactor(lookback=20),
        RSIFactor(lookback=14),
        MACDFactor(lookback=12),
    ]


def _strategy_configs() -> dict[str, FactorBlendConfig]:
    return {
        "single_rsi": FactorBlendConfig(
            factors=[
                FactorWeight(
                    factor_id="rsi",
                    weight=1.0,
                    direction=FactorDirection.LOWER_IS_BETTER,
                )
            ],
            rebalance_every_n_bars=5,
        ),
        "single_macd": FactorBlendConfig(
            factors=[
                FactorWeight(
                    factor_id="macd",
                    weight=1.0,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                )
            ],
            rebalance_every_n_bars=5,
        ),
        "multi_factor": FactorBlendConfig(
            factors=[
                FactorWeight(
                    factor_id="momentum",
                    weight=1.0,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                ),
                FactorWeight(
                    factor_id="volatility",
                    weight=1.0,
                    direction=FactorDirection.LOWER_IS_BETTER,
                ),
                FactorWeight(
                    factor_id="liquidity",
                    weight=1.0,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                ),
                FactorWeight(
                    factor_id="rsi",
                    weight=1.0,
                    direction=FactorDirection.LOWER_IS_BETTER,
                ),
                FactorWeight(
                    factor_id="macd",
                    weight=1.0,
                    direction=FactorDirection.HIGHER_IS_BETTER,
                ),
            ],
            rebalance_every_n_bars=5,
        ),
    }


def _run_backtest(
    *,
    ohlcv: pd.DataFrame,
    score_frame: pd.DataFrame,
    output_dir: Path,
    top_n: int,
    target_gross_exposure: float,
    initial_cash: float,
    commission_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    config = BacktestConfig(
        initial_cash=initial_cash,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )
    strategy = ScoreSignalStrategy(
        score_frame,
        top_n=top_n,
        target_gross_exposure=target_gross_exposure,
    )
    result = BacktestEngine(config).run(ohlcv, strategy)
    storage = LocalBacktestStorage(base_dir=output_dir)
    storage.save_frame(
        result.equity_curve,
        filename="equity_curve.parquet",
        table_name="backtest_equity_curve",
    )
    storage.save_frame(
        result.trade_blotter,
        filename="trade_blotter.parquet",
        table_name="backtest_trade_blotter",
    )
    storage.save_frame(result.orders, filename="orders.parquet", table_name="backtest_orders")
    storage.save_frame(
        result.positions,
        filename="positions.parquet",
        table_name="backtest_positions",
    )
    storage.save_metrics(result.metrics)
    report = generate_backtest_report(
        metrics=result.metrics,
        config=config,
        trade_count=len(result.trade_blotter),
        equity_rows=len(result.equity_curve),
    )
    storage.save_report(report)
    return {
        "total_return": result.metrics.total_return,
        "exposure_adjusted_return": (
            result.metrics.total_return / target_gross_exposure
            if target_gross_exposure
            else 0.0
        ),
        "annualized_return": result.metrics.annualized_return,
        "volatility": result.metrics.volatility,
        "sharpe": result.metrics.sharpe,
        "max_drawdown": result.metrics.max_drawdown,
        "turnover": result.metrics.turnover,
        "trades": int(len(result.trade_blotter)),
    }


def _paper_summary(result: PaperTradingRunResult) -> dict[str, Any]:
    return {
        "orders": result.order_count,
        "trades": result.trade_count,
        "risk_breaches": result.risk_breach_count,
        "final_equity": result.final_equity,
        "orders_path": str(result.orders_path),
        "trades_path": str(result.trades_path),
        "risk_breaches_path": str(result.risk_breaches_path),
        "report_path": str(result.report_path),
    }


def _write_markdown_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Phase 0-5 SPY+QQQ Full Check",
        "",
        f"- Data source: {summary['source']}",
        f"- Source note: {summary['source_note']}",
        f"- Date range: {summary['start']} to {summary['end']}",
        f"- Symbols: {', '.join(summary['symbols'])}",
        f"- OHLCV rows: {summary['rows']}",
        f"- Factor rows: {summary['factor_rows']}",
        f"- Target gross exposure: {summary['target_gross_exposure']:.2%}",
        "",
        "## Strategy Results",
        "",
        "| Strategy | Backtest Return | Exposure-Adjusted Return | Sharpe | Max DD | "
        "Backtest Trades | "
        "Paper Trades | Paper Risk Breaches | Paper Final Equity |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["strategies"]:
        backtest = item["backtest"]
        paper = item["paper"]
        lines.append(
            "| {strategy} | {ret:.4%} | {adj_ret:.4%} | {sharpe:.4f} | {dd:.4%} | "
            "{bt_trades} | "
            "{paper_trades} | {breaches} | {equity:.2f} |".format(
                strategy=item["strategy"],
                ret=backtest["total_return"],
                adj_ret=backtest["exposure_adjusted_return"],
                sharpe=backtest["sharpe"],
                dd=backtest["max_drawdown"],
                bt_trades=backtest["trades"],
                paper_trades=paper["trades"],
                breaches=paper["risk_breaches"],
                equity=paper["final_equity"],
            )
        )
    lines.extend(
        [
            "",
            "## Safety Notes",
            "",
            "- This run explicitly disables the kill switch only for local paper trading.",
            "- It does not connect to any real broker.",
            "- Orders still pass through the Phase 5 risk engine before paper fills.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
