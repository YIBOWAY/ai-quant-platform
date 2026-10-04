import importlib.util
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_current_phase2_controls.py"
spec = importlib.util.spec_from_file_location("current_controls", SCRIPT)
controls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controls)


def test_original_fixed_rng_and_schedule_algorithm_are_reused_exactly():
    profile = {
        "signals": [
            {
                "eligible_symbols": ["F", "D", "B", "A", "C", "E"],
                "trade_date": "2020-02-03",
                "signal_date": "2020-01-31",
                "ready": True,
            }
        ]
    }
    first, rows = controls.engine_driver().random_schedule(np.random.default_rng(20260920), profile)
    second, identical = controls.engine_driver().random_schedule(
        np.random.default_rng(20260920), profile
    )
    assert first == second and rows == identical
    assert len(rows[0]["targets"]) == 5
    assert set(rows[0]["targets"].values()) == {0.2}
