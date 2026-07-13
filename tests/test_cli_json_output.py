"""D-22: `--json` machine contract on the four HQA-consumed commands.

Contract: with `--json`, exactly one JSON object is emitted on the LAST stdout
line (human lines may precede it; HQA parses only the last line). Without
`--json`, legacy key=value output stays byte-identical so the HQA regex
fallback keeps working mid-migration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

import quant_system.cli as cli_module
from quant_system.cli import app
from quant_system.config.settings import reload_settings

runner = CliRunner()

_CANDIDATE_ID_RE = re.compile(r"candidate_id=(\S+)")

_EXPERIMENT_CONFIG = {
    "experiment_name": "json-contract-test",
    "symbols": ["SPY"],
    "start": "2024-01-02",
    "end": "2024-02-15",
    "factor_blend": {"factors": [{"factor_id": "momentum"}]},
}


def _last_line(output: str) -> str:
    lines = [line for line in output.splitlines() if line.strip()]
    assert lines, f"no output lines in {output!r}"
    return lines[-1]


def _propose_factor(tmp_path: Path, *extra: str):
    output_dir = tmp_path / "agent_run"
    result = runner.invoke(
        app,
        [
            "agent",
            "propose-factor",
            "--goal",
            "json contract check",
            "--agent-output-dir",
            str(output_dir),
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output
    return result, output_dir


def _candidate_id(output: str) -> str:
    match = _CANDIDATE_ID_RE.search(output)
    assert match, f"candidate_id missing in {output!r}"
    return match.group(1)


def _write_experiment_config(tmp_path: Path) -> Path:
    path = tmp_path / "exp.json"
    path.write_text(json.dumps(_EXPERIMENT_CONFIG), encoding="utf-8")
    return path


def _patch_experiment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli_module,
        "build_ohlcv_provider",
        lambda settings, *, requested: (object(), requested),
    )

    class _Result:
        experiment_id = "e-json-1"
        run_count = 2
        best_run_id = "run-7"
        config_path = tmp_path / "c"
        runs_path = tmp_path / "r"
        folds_path = tmp_path / "f"
        agent_summary_path = tmp_path / "a.json"
        report_path = tmp_path / "rep.md"

    monkeypatch.setattr(cli_module, "run_experiment", lambda *a, **k: _Result())


# --- agent propose-factor ---------------------------------------------------


def test_propose_factor_legacy_line_byte_identical_without_json(tmp_path) -> None:
    result, output_dir = _propose_factor(tmp_path)

    candidate_id = _candidate_id(result.output)
    candidate_dir = Path(output_dir, "agent", "candidates", candidate_id)
    expected = " ".join(
        [
            f"candidate_id={candidate_id}",
            "status=pending",
            f"path={candidate_dir / 'factor.py.candidate'}",
            f"metadata={candidate_dir / 'metadata.json'}",
        ]
    )
    assert _last_line(result.output) == expected


def test_propose_factor_json_emits_contract_on_last_line(tmp_path) -> None:
    result, output_dir = _propose_factor(tmp_path, "--json")

    payload = json.loads(_last_line(result.output))
    assert set(payload) == {"candidate_id", "status", "path", "metadata_path"}
    assert payload["status"] == "pending"
    assert payload["candidate_id"] == _candidate_id(result.output)
    candidate_dir = Path(output_dir, "agent", "candidates", payload["candidate_id"])
    assert payload["path"] == str(candidate_dir / "factor.py.candidate")
    assert payload["metadata_path"] == str(candidate_dir / "metadata.json")
    # Legacy key=value line still precedes the JSON line (regex fallback safe).
    assert "status=pending" in result.output


# --- agent review -----------------------------------------------------------


def test_agent_review_legacy_line_byte_identical_without_json(tmp_path) -> None:
    propose_result, output_dir = _propose_factor(tmp_path)
    candidate_id = _candidate_id(propose_result.output)

    result = runner.invoke(
        app,
        [
            "agent",
            "review",
            "--candidate-id",
            candidate_id,
            "--decision",
            "approve",
            "--note",
            "json contract regression",
            "--agent-output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    expected = f"candidate_id={candidate_id} decision=approve registration=manual_required"
    assert _last_line(result.output) == expected


def test_agent_review_json_emits_contract_on_last_line(tmp_path) -> None:
    propose_result, output_dir = _propose_factor(tmp_path)
    candidate_id = _candidate_id(propose_result.output)

    result = runner.invoke(
        app,
        [
            "agent",
            "review",
            "--candidate-id",
            candidate_id,
            "--decision",
            "approve",
            "--note",
            "json contract",
            "--agent-output-dir",
            str(output_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    assert set(payload) == {"candidate_id", "decision", "registration"}
    assert payload["candidate_id"] == candidate_id
    assert payload["decision"] == "approve"
    assert payload["registration"] == "manual_required"
    # Legacy line still present for the regex fallback.
    assert "registration=manual_required" in result.output.splitlines()[0]


# --- experiment run-config ----------------------------------------------------


def test_run_config_legacy_line_byte_identical_without_json(tmp_path, monkeypatch) -> None:
    _patch_experiment(monkeypatch, tmp_path)

    result = runner.invoke(
        app,
        ["experiment", "run-config", "--config", str(_write_experiment_config(tmp_path))],
    )

    assert result.exit_code == 0, result.output
    expected = " ".join(
        [
            "experiment_id=e-json-1",
            "run_count=2",
            "best_run_id=run-7",
            f"config={tmp_path / 'c'}",
            f"runs={tmp_path / 'r'}",
            f"folds={tmp_path / 'f'}",
            f"agent_summary={tmp_path / 'a.json'}",
            f"report={tmp_path / 'rep.md'}",
        ]
    )
    assert _last_line(result.output) == expected


def test_run_config_json_emits_contract_on_last_line(tmp_path, monkeypatch) -> None:
    _patch_experiment(monkeypatch, tmp_path)

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_experiment_config(tmp_path)),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    assert set(payload) == {
        "experiment_id",
        "run_count",
        "best_run_id",
        "agent_summary",
        "report",
        "approved_candidates_loaded",
    }
    assert payload["experiment_id"] == "e-json-1"
    assert payload["run_count"] == 2
    assert payload["best_run_id"] == "run-7"
    assert payload["agent_summary"] == str(tmp_path / "a.json")
    assert payload["report"] == str(tmp_path / "rep.md")
    assert payload["approved_candidates_loaded"] == []
    # Legacy summary line still precedes the JSON line.
    assert "experiment_id=e-json-1" in result.output


def test_run_config_json_lists_loaded_approved_candidates(tmp_path, monkeypatch) -> None:
    _patch_experiment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        cli_module,
        "load_approved_factor_candidates",
        lambda registry, *, candidates_dir: ["candidate_x"],
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_experiment_config(tmp_path)),
            "--include-approved-candidates",
            "--agent-output-dir",
            str(tmp_path / "agent-output"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    assert payload["approved_candidates_loaded"] == ["candidate_x"]


# --- doctor -------------------------------------------------------------------


def test_doctor_legacy_line_byte_identical_without_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "safety.live_trading_enabled=false" in result.output.splitlines()
    # Legacy output still ends with the runtime log pointer, not JSON.
    assert _last_line(result.output).startswith("runtime.log=")


def test_doctor_json_emits_contract_on_last_line(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("QS_DATA_DIR", str(tmp_path))
    reload_settings()

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    assert set(payload) == {"environment", "safety", "ok"}
    assert set(payload["safety"]) == {
        "dry_run",
        "paper_trading",
        "live_trading_enabled",
        "kill_switch",
    }
    for value in payload["safety"].values():
        assert isinstance(value, bool)
    assert payload["safety"]["live_trading_enabled"] is False
    assert payload["ok"] is True
    assert isinstance(payload["environment"], str)
    # Human summary lines still precede the JSON line.
    assert "Quant System local health" in result.output
