from __future__ import annotations

from quant_system.backtest.metrics import PerformanceMetrics
from quant_system.backtest.models import BacktestConfig


def generate_backtest_report(
    *,
    metrics: PerformanceMetrics,
    config: BacktestConfig,
    trade_count: int,
    equity_rows: int,
) -> str:
    return "\n".join(
        [
            "# Phase 3 Backtest Report",
            "",
            "## Scope",
            "",
            "This report is produced by the local backtest simulator. It does not place "
            "orders and does not represent live-trading readiness.",
            "",
            "## Execution Assumptions",
            "",
            f"- Execution price: {config.execution_price}",
            f"- Initial cash: {config.initial_cash:.2f}",
            f"- Commission: {config.commission_bps:.4f} bps",
            f"- Slippage: {config.slippage_bps:.4f} bps",
            "- Signals are converted to target weights before order generation.",
            "- Orders are generated and simulated outside the strategy layer.",
            "",
            "## Summary",
            "",
            f"- Equity rows: {equity_rows}",
            f"- Trades: {trade_count}",
            f"- Total return: {metrics.total_return:.6f}",
            f"- Annualized return: {metrics.annualized_return:.6f}",
            f"- Volatility: {metrics.volatility:.6f}",
            f"- Sharpe: {metrics.sharpe:.6f}",
            f"- Max drawdown: {metrics.max_drawdown:.6f}",
            f"- Turnover: {metrics.turnover:.6f}",
            "",
            "## Bias Controls",
            "",
            "- The engine executes only on `tradeable_ts` from the signal table.",
            "- The default fill assumption is next bar open.",
            "- Closing prices are used only for end-of-bar valuation.",
            "- Transaction costs and slippage are included in cash updates.",
            "",
        ]
    )
