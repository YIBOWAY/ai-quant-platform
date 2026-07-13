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

    def fake_run_experiment(
        config,
        *,
        output_dir=None,
        provider=None,
        data_source="sample",
        **kwargs,
    ):
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
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_config(tmp_path)),
            "--provider",
            "tiingo",
        ],
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

    result = runner.invoke(
        app,
        ["experiment", "run-config", "--config", str(_write_config(tmp_path))],
    )
    assert result.exit_code == 0, result.output
    assert captured["data_source"] == "sample"


def _stub_run_experiment_result(tmp_path):
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


def _invoke_stubbed_run_config_with_approved_candidates(
    monkeypatch, tmp_path, extra_args: list[str] | None = None
):
    monkeypatch.setattr(
        cli_module, "build_ohlcv_provider", lambda settings, *, requested: (object(), requested)
    )
    monkeypatch.setattr(
        cli_module, "run_experiment", lambda *a, **k: _stub_run_experiment_result(tmp_path)
    )
    args = [
        "experiment",
        "run-config",
        "--config",
        str(_write_config(tmp_path)),
        "--include-approved-candidates",
    ]
    if extra_args:
        args.extend(extra_args)
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def test_run_config_candidate_loader_is_cwd_independent_and_uses_env(
    monkeypatch, tmp_path
) -> None:
    from pathlib import Path

    from quant_system.agent.paths import resolve_agent_output_dir, resolve_candidates_dir

    agent = tmp_path / "agent-output"
    outside = tmp_path / "outside-platform-repo"
    outside.mkdir()
    monkeypatch.setenv("QS_AGENT_OUTPUT_DIR", str(agent))
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path / "general-data"))
    monkeypatch.chdir(outside)

    captured = {}

    def fake_load(registry, *, candidates_dir):
        captured["candidates_dir"] = Path(candidates_dir)
        return []

    monkeypatch.setattr(cli_module, "load_approved_factor_candidates", fake_load)
    _invoke_stubbed_run_config_with_approved_candidates(monkeypatch, tmp_path)

    assert captured["candidates_dir"] == resolve_candidates_dir(resolve_agent_output_dir())
    assert captured["candidates_dir"] == agent / "agent" / "candidates"


def test_include_approved_candidates_accepts_agent_output_dir_override(
    tmp_path,
    monkeypatch,
) -> None:
    from pathlib import Path

    from quant_system.agent.paths import resolve_agent_output_dir, resolve_candidates_dir

    custom_agent_root = tmp_path / "custom-agent-root"
    captured = {}

    def fake_load(registry, *, candidates_dir):
        captured["candidates_dir"] = Path(candidates_dir)
        return []

    monkeypatch.setattr(cli_module, "load_approved_factor_candidates", fake_load)
    _invoke_stubbed_run_config_with_approved_candidates(
        monkeypatch,
        tmp_path,
        extra_args=["--agent-output-dir", str(custom_agent_root)],
    )

    assert captured["candidates_dir"] == resolve_candidates_dir(
        resolve_agent_output_dir(custom_agent_root)
    )
