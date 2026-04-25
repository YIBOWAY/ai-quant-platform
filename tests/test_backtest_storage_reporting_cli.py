from pathlib import Path

from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


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
