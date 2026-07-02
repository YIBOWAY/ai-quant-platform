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
