from __future__ import annotations

import json

from typer.testing import CliRunner

import quant_system.cli as cli_module
from quant_system.agent.promotion import CandidateFactorBinding
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
    (tmp_path / "c").write_text(json.dumps(_CONFIG), encoding="utf-8")
    (tmp_path / "a.json").write_text(
        json.dumps({"experiment_id": "e-1", "runs": []}), encoding="utf-8"
    )
    (tmp_path / "rep.md").write_text("# report\n", encoding="utf-8")

    class _R:
        experiment_id = "e-1"
        run_count = 1
        best_run_id = None
        data_source = "sample"
        config_path = tmp_path / "c"
        runs_path = tmp_path / "r"
        folds_path = tmp_path / "f"
        agent_summary_path = tmp_path / "a.json"
        report_path = tmp_path / "rep.md"

    return _R()


def _invoke_stubbed_run_config_with_exact_candidate(
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
        "--candidate-id",
        "cand-exact",
        "--expected-digest",
        "a" * 64,
    ]
    if extra_args:
        args.extend(extra_args)
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return result


def test_run_config_exact_candidate_loader_is_cwd_independent_and_uses_env(
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

    def fake_load(
        registry,
        *,
        agent_output_dir,
        candidate_id,
        expected_manifest_digest,
    ):
        captured["agent_output_dir"] = Path(agent_output_dir)
        return CandidateFactorBinding(
            candidate_id=candidate_id,
            manifest_digest=expected_manifest_digest,
            factor_id="momentum",
        )

    monkeypatch.setattr(cli_module, "load_approved_factor_candidate", fake_load)
    _invoke_stubbed_run_config_with_exact_candidate(monkeypatch, tmp_path)

    assert captured["agent_output_dir"] == resolve_agent_output_dir()
    assert resolve_candidates_dir(captured["agent_output_dir"]) == (
        agent / "agent" / "candidates"
    )


def test_exact_candidate_accepts_agent_output_dir_override(
    tmp_path,
    monkeypatch,
) -> None:
    from pathlib import Path

    from quant_system.agent.paths import resolve_agent_output_dir, resolve_candidates_dir

    custom_agent_root = tmp_path / "custom-agent-root"
    captured = {}

    def fake_load(
        registry,
        *,
        agent_output_dir,
        candidate_id,
        expected_manifest_digest,
    ):
        captured["agent_output_dir"] = Path(agent_output_dir)
        return CandidateFactorBinding(
            candidate_id=candidate_id,
            manifest_digest=expected_manifest_digest,
            factor_id="momentum",
        )

    monkeypatch.setattr(cli_module, "load_approved_factor_candidate", fake_load)
    _invoke_stubbed_run_config_with_exact_candidate(
        monkeypatch,
        tmp_path,
        extra_args=["--agent-output-dir", str(custom_agent_root)],
    )

    assert captured["agent_output_dir"] == resolve_agent_output_dir(custom_agent_root)
    assert resolve_candidates_dir(captured["agent_output_dir"]) == (
        custom_agent_root / "agent" / "candidates"
    )


def test_run_config_loads_only_the_exact_candidate_binding(
    tmp_path,
    monkeypatch,
) -> None:
    captured = {}
    custom_agent_root = tmp_path / "candidate-root"
    digest = "a" * 64
    monkeypatch.setattr(
        cli_module,
        "build_ohlcv_provider",
        lambda settings, *, requested: (object(), requested),
    )

    def fake_exact_load(
        registry,
        *,
        agent_output_dir,
        candidate_id,
        expected_manifest_digest,
    ):
        captured.update(
            agent_output_dir=agent_output_dir,
            candidate_id=candidate_id,
            expected_manifest_digest=expected_manifest_digest,
        )
        return CandidateFactorBinding(
            candidate_id=candidate_id,
            manifest_digest=expected_manifest_digest,
            factor_id="momentum",
        )

    monkeypatch.setattr(
        cli_module,
        "load_approved_factor_candidate",
        fake_exact_load,
        raising=False,
    )
    monkeypatch.setattr(
        cli_module,
        "run_experiment",
        lambda *a, **k: _stub_run_experiment_result(tmp_path),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_config(tmp_path)),
            "--candidate-id",
            "cand-exact",
            "--expected-digest",
            digest,
            "--agent-output-dir",
            str(custom_agent_root),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured == {
        "agent_output_dir": custom_agent_root.resolve(),
        "candidate_id": "cand-exact",
        "expected_manifest_digest": digest,
    }


def test_exact_candidate_identity_is_recorded_in_config_and_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    captured = {}
    digest = "b" * 64
    monkeypatch.setattr(
        cli_module,
        "build_ohlcv_provider",
        lambda settings, *, requested: (object(), requested),
    )
    monkeypatch.setattr(
        cli_module,
        "load_approved_factor_candidate",
        lambda *a, **k: CandidateFactorBinding(
            candidate_id="cand-bound",
            manifest_digest=digest,
            factor_id="candidate_factor",
        ),
        raising=False,
    )

    def fake_run_experiment(config, **kwargs):
        captured["config"] = config
        return _stub_run_experiment_result(tmp_path)

    monkeypatch.setattr(cli_module, "run_experiment", fake_run_experiment)

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_config(tmp_path)),
            "--candidate-id",
            "cand-bound",
            "--expected-digest",
            digest,
            "--agent-output-dir",
            str(tmp_path / "agent-root"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    config = captured["config"]
    assert config.factor_blend.factors[0].factor_id == "candidate_factor"
    assert config.candidate_binding.model_dump() == {
        "candidate_id": "cand-bound",
        "manifest_digest": digest,
        "factor_id": "candidate_factor",
    }
    receipt = json.loads(result.output.splitlines()[-1])
    assert receipt["candidate_binding"] == config.candidate_binding.model_dump()


def test_run_config_rejects_the_legacy_load_all_candidate_switch(
    tmp_path,
) -> None:
    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_config(tmp_path)),
            "--include-approved-candidates",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    help_result = runner.invoke(app, ["experiment", "run-config", "--help"])
    assert help_result.exit_code == 0
    assert "--include-approved-candidates" not in help_result.output


def test_run_config_rejects_malformed_digest_before_candidate_read(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "load_approved_factor_candidate",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("malformed digest must fail before candidate read")
        ),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_config(tmp_path)),
            "--candidate-id",
            "cand-exact",
            "--expected-digest",
            "not-a-digest",
        ],
    )

    assert result.exit_code == 2
    assert "64" in result.output
    assert "digest" in result.output.lower()


def test_run_config_rejects_a_candidate_binding_claim_without_exact_selector(
    tmp_path,
    monkeypatch,
) -> None:
    payload = dict(_CONFIG)
    payload["candidate_binding"] = {
        "candidate_id": "cand-spoofed",
        "manifest_digest": "f" * 64,
        "factor_id": "momentum",
    }
    config_path = tmp_path / "spoofed.json"
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        cli_module,
        "run_experiment",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("spoofed binding must fail before experiment execution")
        ),
    )

    result = runner.invoke(
        app,
        ["experiment", "run-config", "--config", str(config_path)],
    )

    assert result.exit_code == 2
    assert "candidate_binding" in result.output
    assert "--candidate-id" in result.output


def test_run_config_reports_exact_candidate_refusal_before_experiment(
    tmp_path,
    monkeypatch,
) -> None:
    from quant_system.agent.promotion import CandidateLoadError

    monkeypatch.setattr(
        cli_module,
        "load_approved_factor_candidate",
        lambda *a, **k: (_ for _ in ()).throw(
            CandidateLoadError("factor_id collision with builtin")
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "run_experiment",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("candidate refusal must stop before experiment")
        ),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_config(tmp_path)),
            "--candidate-id",
            "cand-collision",
            "--expected-digest",
            "a" * 64,
        ],
    )

    assert result.exit_code == 1
    assert "candidate_load_refused" in result.output
    assert "collision" in result.output
