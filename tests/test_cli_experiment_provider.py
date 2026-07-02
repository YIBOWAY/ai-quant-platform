from __future__ import annotations

import json

from typer.testing import CliRunner

import quant_system.cli as cli_module
from quant_system.cli import app

runner = CliRunner()

_CONFIG = {
    "experiment_name": "wiring-test",
    "symbols": ["SPY"],
    "start": "2024-01-02",
    "end": "2024-02-15",
    "factor_blend": {"factors": [{"factor_id": "momentum"}]},
}


def _write_config(tmp_path):
    path = tmp_path / "exp.json"
    path.write_text(json.dumps(_CONFIG), encoding="utf-8")
    return path


def test_run_config_passes_provider_to_run_experiment(tmp_path, monkeypatch):
    sentinel = object()
    captured = {}

    monkeypatch.setattr(
        cli_module, "build_ohlcv_provider", lambda settings, *, requested: (sentinel, requested)
    )

    def fake_run_experiment(config, *, output_dir=None, provider=None, data_source="sample", **kwargs):
        captured.update(provider=provider, data_source=data_source)

        class _R:
            experiment_id = "e-1"
            run_count = 1
            best_run_id = "run-1"
            config_path = tmp_path / "c"
            runs_path = tmp_path / "r"
            folds_path = tmp_path / "f"
            agent_summary_path = tmp_path / "a.json"
            report_path = tmp_path / "rep.md"

        return _R()

    monkeypatch.setattr(cli_module, "run_experiment", fake_run_experiment)

    result = runner.invoke(
        app, ["experiment", "run-config", "--config", str(_write_config(tmp_path)), "--provider", "tiingo"]
    )
    assert result.exit_code == 0, result.output
    assert captured["provider"] is sentinel
    assert captured["data_source"] == "tiingo"


def test_run_config_defaults_to_sample(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cli_module, "build_ohlcv_provider", lambda settings, *, requested: (object(), requested)
    )

    def fake_run_experiment(config, **kwargs):
        captured.update(kwargs)

        class _R:
            experiment_id = "e-1"
            run_count = 1
            best_run_id = None
            config_path = tmp_path / "c"
            runs_path = tmp_path / "r"
            folds_path = tmp_path / "f"
            agent_summary_path = tmp_path / "a.json"
            report_path = tmp_path / "rep.md"

        return _R()

    monkeypatch.setattr(cli_module, "run_experiment", fake_run_experiment)

    result = runner.invoke(app, ["experiment", "run-config", "--config", str(_write_config(tmp_path))])
    assert result.exit_code == 0, result.output
    assert captured["data_source"] == "sample"


def test_include_approved_candidates_reads_same_dir_agent_cli_writes_to(tmp_path, monkeypatch):
    # Finding #3: --include-approved-candidates must read from the directory the
    # agent CLI (propose-factor / agent review) actually writes approved.lock to,
    # i.e. CandidatePool(output_dir).candidates_dir with output_dir defaulting to
    # "data/agent_run". A mismatch silently loads zero candidates.
    from quant_system.agent.candidate_pool import CandidatePool

    captured = {}

    def fake_load(registry, *, candidates_dir):
        captured["candidates_dir"] = candidates_dir
        return []

    monkeypatch.setattr(cli_module, "load_approved_factor_candidates", fake_load)
    monkeypatch.setattr(
        cli_module, "build_ohlcv_provider", lambda settings, *, requested: (object(), requested)
    )

    class _R:
        experiment_id = "e-1"
        run_count = 1
        best_run_id = None
        config_path = tmp_path / "c"
        runs_path = tmp_path / "r"
        folds_path = tmp_path / "f"
        agent_summary_path = tmp_path / "a.json"
        report_path = tmp_path / "rep.md"

    monkeypatch.setattr(cli_module, "run_experiment", lambda *a, **k: _R())

    result = runner.invoke(
        app,
        ["experiment", "run-config", "--config", str(_write_config(tmp_path)),
         "--include-approved-candidates"],
    )
    assert result.exit_code == 0, result.output
    expected = str(CandidatePool("data/agent_run").candidates_dir)
    assert str(captured["candidates_dir"]) == expected, (
        f"loader reads {captured['candidates_dir']!r}, but agent CLI writes to {expected!r}"
    )
