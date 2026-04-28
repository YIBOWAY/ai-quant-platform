from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


def test_paper_trading_run_sample_cli_generates_logs_and_report(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "paper",
            "run-sample",
            "--symbol",
            "SPY",
            "--symbol",
            "AAPL",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-12",
            "--initial-cash",
            "100000",
            "--max-order-value",
            "20000",
            "--max-position-size",
            "0.60",
            "--no-kill-switch",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "paper_report=" in result.output
    assert Path(tmp_path, "paper", "orders.parquet").exists()
    assert Path(tmp_path, "paper", "order_events.parquet").exists()
    assert Path(tmp_path, "paper", "trades.parquet").exists()
    assert Path(tmp_path, "paper", "risk_breaches.parquet").exists()
    assert Path(tmp_path, "reports", "paper_trading_report.md").exists()
    trades = pd.read_parquet(Path(tmp_path, "paper", "trades.parquet"))
    assert not trades.empty


def test_paper_trading_cli_respects_kill_switch(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "paper",
            "run-sample",
            "--symbol",
            "SPY",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-08",
            "--kill-switch",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    breaches = pd.read_parquet(Path(tmp_path, "paper", "risk_breaches.parquet"))
    trades = pd.read_parquet(Path(tmp_path, "paper", "trades.parquet"))
    assert not breaches.empty
    assert trades.empty


def test_paper_trading_cli_uses_global_kill_switch_by_default(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "paper",
            "run-sample",
            "--symbol",
            "SPY",
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-08",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    breaches = pd.read_parquet(Path(tmp_path, "paper", "risk_breaches.parquet"))
    trades = pd.read_parquet(Path(tmp_path, "paper", "trades.parquet"))
    assert not breaches.empty
    assert set(breaches["rule_name"]) == {"kill_switch"}
    assert trades.empty
