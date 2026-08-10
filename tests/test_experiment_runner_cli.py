import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.experiments import runner as runner_module
from quant_system.experiments.models import (
    CandidateResearchBinding,
    ExperimentConfig,
    FactorBlendConfig,
    FactorWeight,
)
from quant_system.experiments.runner import run_experiment

runner = CliRunner()


def test_experiment_ids_are_unique_even_when_the_clock_is_identical() -> None:
    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)

    identities = {
        runner_module._new_experiment_id("factor-repro-candidate", now)
        for _ in range(32)
    }

    assert len(identities) == 32
    assert all(
        identity.startswith("factor-repro-candidate-20260714T120000000000Z-")
        for identity in identities
    )


def test_experiment_namespace_collision_retries_without_overwrite(
    tmp_path, monkeypatch
) -> None:
    now = datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)
    collision = "factor-repro-candidate-20260714T120000000000Z-aaaaaaaaaaaa"
    unique = "factor-repro-candidate-20260714T120000000000Z-bbbbbbbbbbbb"
    collision_dir = tmp_path / "experiments" / collision.replace("-", "_")
    collision_dir.mkdir(parents=True)
    marker = collision_dir / "keep.txt"
    marker.write_text("do not overwrite\n", encoding="utf-8")
    identities = iter([collision, unique])
    monkeypatch.setattr(
        runner_module,
        "_new_experiment_id",
        lambda _name, _now: next(identities),
    )

    experiment_id, storage = runner_module._reserve_experiment_storage(
        output_dir=tmp_path,
        experiment_name="factor-repro-candidate",
        now_utc=now,
    )

    assert experiment_id == unique
    assert storage.experiments_dir.is_dir()
    assert storage.reports_dir.is_dir()
    assert marker.read_text(encoding="utf-8") == "do not overwrite\n"


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


def test_candidate_binding_is_persisted_in_config_and_agent_summary(tmp_path) -> None:
    binding = CandidateResearchBinding(
        candidate_id="cand-receipt",
        manifest_digest="c" * 64,
        factor_id="momentum",
    )
    config = ExperimentConfig(
        experiment_name="candidate-receipt",
        symbols=["SPY", "QQQ"],
        start="2024-01-02",
        end="2024-02-15",
        factor_blend=FactorBlendConfig(
            factors=[FactorWeight(factor_id="momentum")]
        ),
        candidate_binding=binding,
    )

    result = run_experiment(config, output_dir=tmp_path)

    persisted_config = json.loads(result.config_path.read_text(encoding="utf-8"))
    agent_summary = json.loads(
        result.agent_summary_path.read_text(encoding="utf-8")
    )
    assert persisted_config["candidate_binding"] == binding.model_dump()
    assert agent_summary["candidate_binding"] == binding.model_dump()


def test_automation_experiment_persists_observed_sample_and_holdout_evidence(
    tmp_path,
) -> None:
    config = ExperimentConfig.model_validate(
        {
            "experiment_name": "automation-evidence",
            "symbols": ["SPY", "QQQ"],
            "start": "2024-01-02",
            "end": "2024-04-15",
            "factor_blend": {"factors": [{"factor_id": "momentum"}]},
            "automation_evidence": {"holdout_days": 30},
        }
    )

    result = run_experiment(config, output_dir=tmp_path)

    summary = json.loads(result.agent_summary_path.read_text(encoding="utf-8"))
    observed = summary["data"]["automation_evidence"]
    assert observed["sample_rows"] > observed["out_of_sample_rows"] > 0
    assert observed["data_coverage_ratio"] == 1.0
    assert observed["holdout_days"] == 30
