"""Paired evaluation seam tests; fabricated fixtures never reach real runtime state."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from quant_system.research import strategy_evaluation_instance as instances
from quant_system.research import strategy_library as library
from quant_system.research.intake_evaluation import (
    compare_increment,
    digest,
    file_hash,
    validate_snapshot,
)
from quant_system.research.strategy_definition import StrategyDefinition


@pytest.fixture
def fixture(tmp_path):
    settings = SimpleNamespace(data=SimpleNamespace(data_dir=tmp_path))
    directory = tmp_path / "research_intake" / "evaluations" / "sealed"
    directory.mkdir(parents=True)
    prices = pd.DataFrame(
        {
            "timestamp": pd.bdate_range(end="2026-09-08", periods=60, tz="UTC"),
            "symbol": ["SPY"] * 60,
            "close": [100.0] * 60,
        }
    )
    path = directory / "prices.parquet"
    prices.to_parquet(path, index=False)
    evaluation = {
        "prices_path": str(path),
        "prices_sha256": file_hash(path),
        "start": "2026-06-01",
        "end": "2026-09-08",
        "cash": 10_000,
    }
    evaluation["evaluation_id"] = "evaluation-" + digest(evaluation)
    return settings, evaluation


def test_snapshot_rejects_changed_data_or_context(fixture):
    settings, evaluation = fixture
    assert validate_snapshot(settings, evaluation).is_file()
    with pytest.raises(ValueError, match="identity_changed"):
        validate_snapshot(settings, {**evaluation, "end": "2026-09-09"})
    Path(evaluation["prices_path"]).write_bytes(b"changed fixture")
    with pytest.raises(ValueError, match="prices_changed"):
        validate_snapshot(settings, evaluation)


def _comparison_job(metric="max_drawdown", minimum=0.01, guards=None):
    return {
        "proposal": {
            "increment_objective": {
                "metric": metric,
                "minimum_improvement": minimum,
                "max_regressions": guards or {},
            }
        },
        "results": [
            {
                "variant": variant,
                "evaluation": {"evaluation_id": "same"},
                "evaluation_calendar_digest": "calendar",
                "validation": {
                    "start": "2020-01-01",
                    "end": "2026-09-08",
                    "comparison": {"accepted": True},
                    "platform_metrics": metrics,
                },
            }
            for variant, metrics in [
                ("baseline", {"max_drawdown": 0.33, "total_return": 5.07, "sharpe": 0.936}),
                ("augmented", {"max_drawdown": 0.319, "total_return": 4.17, "sharpe": 0.913}),
            ]
        ],
    }


def test_increment_objective_distinguishes_risk_goal_from_return_goal():
    assert compare_increment(_comparison_job())["passed"] is True
    assert compare_increment(_comparison_job("total_return"))["passed"] is False
    assert compare_increment(_comparison_job(guards={"sharpe": 0.01}))["passed"] is False


def test_identical_endpoints_with_different_actual_return_calendar_not_comparable():
    job = _comparison_job()
    job["results"][0]["evaluation_calendar_digest"] = "different"
    assert compare_increment(job)["status"] == "unavailable"


def test_rounding_tolerance_cannot_turn_zero_improvement_into_a_pass():
    job = _comparison_job(minimum=1e-15)
    job["results"][1]["validation"]["platform_metrics"]["max_drawdown"] = 0.33
    assert compare_increment(job)["passed"] is False


@pytest.mark.parametrize("metric", [float("nan"), None, True])
def test_unknown_increment_metric_does_not_pass(metric):
    job = _comparison_job()
    job["results"][0]["validation"]["platform_metrics"]["max_drawdown"] = metric
    assert compare_increment(job)["status"] == "unavailable"


@pytest.mark.parametrize("tamper", ["definition", "source"])
def test_detached_actual_library_evaluation_preserves_entry_and_trial_identity(
    fixture,
    monkeypatch,
    tamper,
):
    settings, evaluation = fixture
    definition = StrategyDefinition(
        kind="factor_blend",
        title="sealed",
        symbols=["SPY"],
        history_start="2015-01-01",
        top_n=1,
        factors=[{"factor_id": "momentum", "lookback": 20, "direction": "higher_is_better"}],
    )
    entry = library._save_definition(settings, definition, {"type": "compose", "end": "2025-01-01"})
    directory = library._directory(settings, entry["strategy_id"])
    original = (directory / "entry.json").read_bytes()
    observed = []

    def evaluate(prices, current, start, end, *, initial_cash):
        observed.append((start, end, initial_cash))
        return {
            "status": "available",
            "start": start,
            "end": end,
            "definition_digest": current.content_digest,
            "evaluation_initial_cash": initial_cash,
            "profile": {"id": "sealed", "symbols": ["SPY"]},
            "metrics": {"total_return": 0.12, "sharpe": 1.0, "max_drawdown": 0.1, "turnover": 2.0},
            "curve": [
                {"date": str(day)[:10], "equity": 10000 + i * 20 + (i % 3) * 10}
                for i, day in enumerate(prices.timestamp)
            ],
            "signals": [],
        }

    def docker(run, module, args):
        source = {"prices_sha256": file_hash(run / "prices.parquet")}
        if module.endswith("definition_qlib_replay"):
            source.update(
                platform_result_sha256=file_hash(run / "platform-result.json"),
                replay_source_sha256=file_hash(
                    Path(library.__file__).with_name("definition_qlib_replay.py")
                ),
            )
            value = {
                "status": "available",
                "definition_digest": definition.content_digest,
                "initial_cash": 10_000,
                "terminal_nav_unit": "USD",
                "source": source,
            }
            library._write(run / "qlib-replay.json", value)
        else:
            source.update(
                result_sha256=file_hash(run / "platform-result.json"),
                validation_source_sha256=file_hash(
                    Path(library.__file__).with_name("strategy_signal_validation.py")
                ),
                fit_metrics_source_sha256=file_hash(
                    Path(library.__file__).with_name("qlib_evaluation.py")
                ),
            )
            library._write(
                run / "signal-analysis.json",
                {
                    "status": "available",
                    "definition_digest": definition.content_digest,
                    "source": source,
                },
            )

    monkeypatch.setattr(library, "evaluate_definition", evaluate)
    monkeypatch.setattr(library, "_collect_prices", lambda *_: pytest.fail("unexpected refetch"))
    monkeypatch.setattr(library, "_docker", docker)
    monkeypatch.setattr(
        library, "_comparison", lambda *_: {"accepted": True, "comparison_digest": "a" * 64}
    )
    monkeypatch.setattr(library, "evaluate_candidate_dsr", lambda *a, **k: {"passed": True})
    monkeypatch.setattr(
        library.assistant_remote, "_certify_cost_sensitivity", lambda *a, **k: {"passed": True}
    )
    monkeypatch.setattr(library.assistant_remote, "_max_hung_correlation", lambda *_: None)
    monkeypatch.setattr(
        library.assistant_remote,
        "record_verified_candidate",
        lambda *a, **k: pytest.fail("detached candidate write"),
    )
    first = library.validate_strategy(
        settings,
        entry["strategy_id"],
        definition.content_digest,
        evaluation=evaluation,
        publish_entry=False,
    )
    assert first["status"] == "validated", first.get("error")
    second = library.validate_strategy(
        settings,
        entry["strategy_id"],
        definition.content_digest,
        evaluation=evaluation,
        publish_entry=False,
    )
    assert second["status"] == "validated", second.get("error")
    assert observed == [("2026-06-01", "2026-09-08", 10_000)] * 2
    assert (directory / "entry.json").read_bytes() == original
    assert first["validation"]["run_id"] != second["validation"]["run_id"]
    assert len(library.TrialsLedger(settings.data.data_dir / "trials").list()) == 1
    for saved in (directory / "validations").glob("*/prices.parquet"):
        assert file_hash(saved) == evaluation["prices_sha256"]
    found = library.find_evaluation(settings, entry["strategy_id"], evaluation)
    assert found["status"] == "validated"
    run = directory / "validations" / found["validation"]["run_id"]
    document = json.loads((run / "validation.json").read_text())
    if tamper == "definition":
        document["definition_digest"] = "e" * 64
    else:
        document["receipts"]["sources"]["definition_qlib_replay.py"] = "f" * 64
    library._write(run / "validation.json", document)
    archive = json.loads((run / "evaluation-entry.json").read_text())
    archive.update(validation=document, validation_sha256=file_hash(run / "validation.json"))
    library._write(run / "evaluation-entry.json", archive)
    with pytest.raises(ValueError):
        library.find_evaluation(settings, entry["strategy_id"], evaluation)


def test_computation_recovery_requires_dead_owner_and_no_active_container(fixture, monkeypatch):
    settings, evaluation = fixture
    directory = settings.data.data_dir / "strategy_library" / "strategy-sealed"
    run = directory / "validations" / "validation-sealed"
    run.mkdir(parents=True)
    (run / "evaluation-owner.json").write_text(
        json.dumps(
            {
                "evaluation_id": evaluation["evaluation_id"],
                "pid": os.getpid(),
            }
        )
    )
    assert instances.computation_idle(settings, directory, evaluation) is False

    def dead(*_):
        raise ProcessLookupError

    monkeypatch.setattr(instances.os, "kill", dead)
    monkeypatch.setattr(instances, "_docker_cli_idle", lambda _: True)
    monkeypatch.setattr(instances, "resolve_docker_executable", lambda: "/sealed/docker")
    monkeypatch.setattr(instances.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=""))
    assert instances.computation_idle(settings, directory, evaluation) is True

    def active(command, **_):
        return SimpleNamespace(
            stdout="id"
            if command[1] == "ps"
            else json.dumps(
                [
                    {"Mounts": [{"Source": str(run)}]},
                ]
            )
        )

    monkeypatch.setattr(instances.subprocess, "run", active)
    assert instances.computation_idle(settings, directory, evaluation) is False

    def unavailable(*_, **__):
        raise OSError

    monkeypatch.setattr(instances.subprocess, "run", unavailable)
    assert instances.computation_idle(settings, directory, evaluation) is False


def test_orphan_docker_cli_before_container_creation_blocks_recovery(fixture, monkeypatch):
    settings, evaluation = fixture
    directory = settings.data.data_dir / "strategy_library" / "strategy-sealed"
    run = directory / "validations" / "validation-sealed"
    run.mkdir(parents=True)
    (run / "evaluation-owner.json").write_text(
        json.dumps(
            {
                "evaluation_id": evaluation["evaluation_id"],
                "pid": 987654321,
            }
        )
    )

    def dead(*_):
        raise ProcessLookupError

    monkeypatch.setattr(instances.os, "kill", dead)
    monkeypatch.setattr(instances, "resolve_docker_executable", lambda: "/sealed/docker")

    def process(command, **_):
        if command[0] == "/bin/ps":
            return SimpleNamespace(
                stdout=(
                    "456 /usr/local/bin/docker\n"
                    if "-axo" in command
                    else f"docker run --mount type=bind,source={run},target=/study"
                )
            )
        return SimpleNamespace(stdout="")  # No container exists yet.

    monkeypatch.setattr(instances.subprocess, "run", process)
    assert instances.computation_idle(settings, directory, evaluation) is False
