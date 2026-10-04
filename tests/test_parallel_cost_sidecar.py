"""Actual engine sidecar wiring with explicitly artificial market inputs."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from quant_system.research.strategy_library import _parallel_cost_replay
from tests.test_cost_replay import artificial_case


def test_sidecar_replays_and_preserves_original_increment_metrics(tmp_path):
    inputs = artificial_case()
    original = deepcopy(inputs["base_result"])
    descriptor = _parallel_cost_replay(tmp_path, inputs["prices"], inputs["base_result"],
                                      SimpleNamespace(**original["definition"]))
    report = json.loads((tmp_path / "parallel-cost-replay.json").read_text())
    assert descriptor["status"] == "evaluated", report
    assert descriptor["authority"] == "parallel_only"
    assert report["engine_runs"] == 3 and report["admission_authority"] is False
    assert inputs["base_result"] == original
    frozen = (tmp_path / "parallel-cost-replay.json").read_bytes()
    with pytest.raises(ValueError, match="already_exists"):
        _parallel_cost_replay(tmp_path, inputs["prices"], inputs["base_result"],
                              SimpleNamespace(**original["definition"]))
    assert (tmp_path / "parallel-cost-replay.json").read_bytes() == frozen


def test_invalid_input_retains_explicit_failure_and_original_metrics(tmp_path):
    inputs = artificial_case()
    inputs["base_result"]["curve"][0]["equity"] += 10
    original = deepcopy(inputs["base_result"])
    descriptor = _parallel_cost_replay(tmp_path, inputs["prices"], inputs["base_result"],
                                      SimpleNamespace(**original["definition"]))
    report = json.loads((tmp_path / "parallel-cost-replay.json").read_text())
    assert descriptor["status"] == "not_evaluated"
    assert report["reason"] and report["capital_authorized"] is False
    assert inputs["base_result"] == original
