import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app

runner = CliRunner()


def test_experiment_run_sample_cli_generates_comparison_and_agent_summary(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "experiment",
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
            "2024-03-15",
            "--lookback",
            "3",
            "--lookback",
            "5",
            "--top-n",
            "1",
            "--top-n",
            "2",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "experiment_id=" in result.output

    experiments_root = Path(tmp_path, "experiments")
    experiment_dirs = [path for path in experiments_root.iterdir() if path.is_dir()]
    assert len(experiment_dirs) == 1
    experiment_dir = experiment_dirs[0]
    assert (experiment_dir / "experiment_config.json").exists()
    assert (experiment_dir / "experiment_runs.parquet").exists()
    assert (experiment_dir / "agent_summary.json").exists()
    reports_dir = Path(tmp_path, "reports", experiment_dir.name)
    assert (reports_dir / "experiment_comparison_report.md").exists()

    runs = pd.read_parquet(experiment_dir / "experiment_runs.parquet")
    assert len(runs) == 4
    assert {"run_id", "created_at", "lookback", "top_n", "total_return"}.issubset(
        runs.columns
    )

    summary = json.loads(
        (experiment_dir / "agent_summary.json").read_text(encoding="utf-8")
    )
    assert summary["safety"]["live_trading"] is False
    assert len(summary["runs"]) == 4


def test_experiment_run_config_cli_uses_json_config_and_walk_forward(tmp_path) -> None:
    config_path = tmp_path / "experiment_config.json"
    config_path.write_text(
        json.dumps(
            {
                "experiment_name": "walk-forward-cli",
                "symbols": ["SPY", "AAPL", "QQQ"],
                "start": "2024-01-02",
                "end": "2024-04-15",
                "initial_cash": 100000,
                "commission_bps": 1,
                "slippage_bps": 5,
                "factor_blend": {
                    "factors": [
                        {
                            "factor_id": "momentum",
                            "weight": 1.0,
                            "direction": "higher_is_better",
                        },
                        {
                            "factor_id": "volatility",
                            "weight": 0.5,
                            "direction": "lower_is_better",
                        },
                    ],
                    "rebalance_every_n_bars": 2,
                },
                "sweep": {"lookback": [3], "top_n": [1, 2]},
                "walk_forward": {
                    "enabled": True,
                    "train_bars": 12,
                    "validation_bars": 8,
                    "step_bars": 8,
                },
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(config_path),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0
    experiments_root = Path(tmp_path, "out", "experiments")
    experiment_dirs = [path for path in experiments_root.iterdir() if path.is_dir()]
    assert len(experiment_dirs) == 1
    experiment_dir = experiment_dirs[0]
    folds_path = experiment_dir / "walk_forward_folds.parquet"
    assert folds_path.exists()
    folds = pd.read_parquet(folds_path)
    assert not folds.empty
    assert {"fold_id", "train_start", "validation_start", "validation_end"}.issubset(
        folds.columns
    )
