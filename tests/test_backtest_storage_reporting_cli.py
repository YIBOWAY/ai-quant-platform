from pathlib import Path

from typer.testing import CliRunner

from quant_system.backtest.metrics import PerformanceMetrics
from quant_system.backtest.models import BacktestConfig
from quant_system.backtest.reporting import generate_backtest_report
from quant_system.cli import app

runner = CliRunner()


def test_backtest_report_contains_order_execution_constraints() -> None:
    report = generate_backtest_report(
        metrics=PerformanceMetrics(
            total_return=0.1,
            annualized_return=0.2,
            volatility=0.3,
            sharpe=1.4,
            max_drawdown=0.05,
            turnover=0.8,
        ),
        config=BacktestConfig(min_order_value=250, whole_share_orders=True),
        trade_count=2,
        equity_rows=3,
    )

    assert "- Minimum order value: 250.00" in report
    assert "- Whole-share orders: true" in report


def test_backtest_run_sample_cli_generates_artifacts(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "backtest",
            "run-sample",
            "--symbol",
            "SPY",
            "--symbol",
            "AAPL",
            "--symbol",
            "QQQ",
            "--start",
            "2024-01-02",
            "--end",
            "2024-02-15",
            "--lookback",
            "3",
            "--top-n",
            "2",
            "--initial-cash",
            "100000",
            "--commission-bps",
            "1",
            "--slippage-bps",
            "5",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "equity_curve=" in result.output
    assert Path(tmp_path, "backtests", "equity_curve.parquet").exists()
    assert Path(tmp_path, "backtests", "trade_blotter.parquet").exists()
    assert Path(tmp_path, "backtests", "orders.parquet").exists()
    assert Path(tmp_path, "backtests", "positions.parquet").exists()
    assert Path(tmp_path, "backtests", "metrics.json").exists()
    assert Path(tmp_path, "reports", "backtest_report.md").exists()
