import json

from quant_system.experiments.config import load_experiment_config
from quant_system.experiments.sweep import expand_parameter_grid


def test_load_experiment_config_from_json_file(tmp_path) -> None:
    config_path = tmp_path / "experiment.json"
    config_path.write_text(
        json.dumps(
            {
                "experiment_name": "phase4-test",
                "symbols": ["SPY", "AAPL"],
                "start": "2024-01-02",
                "end": "2024-02-15",
                "factor_blend": {
                    "factors": [
                        {
                            "factor_id": "momentum",
                            "weight": 1.0,
                            "direction": "higher_is_better",
                        }
                    ],
                    "rebalance_every_n_bars": 1,
                },
                "sweep": {"lookback": [3, 5], "top_n": [1, 2]},
                "walk_forward": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )

    config = load_experiment_config(config_path)

    assert config.experiment_name == "phase4-test"
    assert config.symbols == ["SPY", "AAPL"]
    assert config.factor_blend.factors[0].factor_id == "momentum"


def test_load_experiment_config_accepts_utf8_bom_files(tmp_path) -> None:
    config_path = tmp_path / "experiment_bom.json"
    config_path.write_text(
        json.dumps(
            {
                "experiment_name": "phase4-bom-test",
                "symbols": ["SPY", "AAPL"],
                "start": "2024-01-02",
                "end": "2024-02-15",
                "factor_blend": {
                    "factors": [
                        {
                            "factor_id": "momentum",
                            "weight": 1.0,
                            "direction": "higher_is_better",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8-sig",
    )

    config = load_experiment_config(config_path)

    assert config.experiment_name == "phase4-bom-test"


def test_parameter_grid_expands_reproducible_sorted_combinations() -> None:
    combinations = expand_parameter_grid({"top_n": [2, 1], "lookback": [5, 3]})

    assert [combo.parameters for combo in combinations] == [
        {"lookback": 5, "top_n": 2},
        {"lookback": 5, "top_n": 1},
        {"lookback": 3, "top_n": 2},
        {"lookback": 3, "top_n": 1},
    ]
    assert combinations[0].run_id == "run-001"
