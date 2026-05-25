import json

import pandas as pd
from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def _write_experiment_fixture(output_dir, experiment_id: str) -> None:
    experiment_dir = output_dir / "experiments" / experiment_id
    experiment_dir.mkdir(parents=True)

    (experiment_dir / "experiment_config.json").write_text(
        json.dumps(
            {
                "experiment_name": "e2e-sweep",
                "symbols": ["SPY", "QQQ"],
                "start": "2024-01-02",
                "end": "2024-02-15",
                "initial_cash": 100000,
                "commission_bps": 1,
                "slippage_bps": 5,
                "sweep": {"lookback": [3, 5], "top_n": [1, 2]},
                "walk_forward": {
                    "enabled": True,
                    "train_bars": 12,
                    "validation_bars": 5,
                    "step_bars": 5,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (experiment_dir / "agent_summary.json").write_text(
        json.dumps(
            {
                "experiment_id": experiment_id,
                "best_run_id": "run-lb5-top1",
                "notes": ["Research-only summary.", "No automatic deployment."],
                "safety": {
                    "live_trading": False,
                    "paper_trading": False,
                    "auto_promotion": False,
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "run_id": "run-lb3-top1",
                "lookback": 3,
                "top_n": 1,
                "sharpe": 0.9,
                "total_return": 0.03,
                "max_drawdown": -0.02,
                "turnover": 1.4,
            },
            {
                "run_id": "run-lb5-top1",
                "lookback": 5,
                "top_n": 1,
                "sharpe": 1.4,
                "total_return": 0.05,
                "max_drawdown": -0.015,
                "turnover": 1.1,
            },
        ]
    ).to_parquet(experiment_dir / "experiment_runs.parquet", index=False)
    pd.DataFrame(
        [
            {
                "run_id": "run-lb5-top1",
                "fold_id": "fold-1",
                "train_start": "2024-01-02",
                "train_end": "2024-01-19",
                "validation_start": "2024-01-22",
                "validation_end": "2024-01-26",
                "sharpe": 1.2,
                "total_return": 0.02,
            }
        ]
    ).to_parquet(experiment_dir / "walk_forward_folds.parquet", index=False)


def test_experiment_list_includes_best_run_id(tmp_path) -> None:
    _write_experiment_fixture(tmp_path, "experiment-api-test")
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/experiments")

    assert response.status_code == 200
    payload = response.json()
    assert payload["experiments"][0]["id"] == "experiment-api-test"
    assert payload["experiments"][0]["best_run_id"] == "run-lb5-top1"


def test_experiment_detail_reads_phase4_artifact_names(tmp_path) -> None:
    _write_experiment_fixture(tmp_path, "experiment-api-test")
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/experiments/experiment-api-test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["experiment_config"]["experiment_name"] == "e2e-sweep"
    assert payload["agent_summary"]["best_run_id"] == "run-lb5-top1"
    assert [run["run_id"] for run in payload["runs"]] == ["run-lb3-top1", "run-lb5-top1"]
    assert payload["folds"][0]["fold_id"] == "fold-1"
