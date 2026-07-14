"""D-22: `--json` machine contract on the four HQA-consumed commands.

Contract: with `--json`, exactly one JSON object is emitted on the LAST stdout
line (human lines may precede it; HQA parses only the last line). Without
`--json`, legacy key=value output stays byte-identical so the HQA regex
fallback keeps working mid-migration.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from typer.testing import CliRunner

import quant_system.cli as cli_module
from quant_system.agent.promotion import CandidateFactorBinding
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

    (tmp_path / "c").write_text(json.dumps(_EXPERIMENT_CONFIG), encoding="utf-8")
    (tmp_path / "a.json").write_text(
        json.dumps({"experiment_id": "e-json-1", "runs": []}),
        encoding="utf-8",
    )
    (tmp_path / "rep.md").write_text("# report\n", encoding="utf-8")

    class _Result:
        experiment_id = "e-json-1"
        run_count = 2
        best_run_id = "run-7"
        data_source = "sample"
        config_path = tmp_path / "c"
        runs_path = tmp_path / "r"
        folds_path = tmp_path / "f"
        agent_summary_path = tmp_path / "a.json"
        report_path = tmp_path / "rep.md"

    monkeypatch.setattr(cli_module, "run_experiment", lambda *a, **k: _Result())


# --- agent propose-factor ---------------------------------------------------


def test_propose_factor_legacy_line_byte_identical_without_json(tmp_path) -> None:
    from quant_system.agent.candidate_pool import CandidatePool

    result, output_dir = _propose_factor(tmp_path)

    candidate_id = _candidate_id(result.output)
    candidate_dir = Path(output_dir, "agent", "candidates", candidate_id)
    digest = CandidatePool(output_dir).get(candidate_id).manifest_digest
    line = _last_line(result.output)
    assert f"candidate_id={candidate_id}" in line
    assert "status=pending" in line
    assert f"path={candidate_dir / 'factor.py.candidate'}" in line
    assert f"metadata={candidate_dir / 'metadata.json'}" in line
    assert f"manifest_digest={digest}" in line
    assert f"--expected-digest {digest}" in line
    assert "--expected-status pending" in line
    assert "approve_cmd=quant-system agent review" in line
    assert "approve_cmd=agent review" not in line


def test_propose_factor_json_emits_contract_on_last_line(tmp_path) -> None:
    result, output_dir = _propose_factor(tmp_path, "--json")

    payload = json.loads(_last_line(result.output))
    assert set(payload) == {
        "candidate_id",
        "status",
        "path",
        "metadata_path",
        "manifest_digest",
        "source_sha256",
    }
    assert payload["status"] == "pending"
    assert re.fullmatch(r"[0-9a-f]{64}", payload["source_sha256"])
    assert payload["candidate_id"] == _candidate_id(result.output)
    candidate_dir = Path(output_dir, "agent", "candidates", payload["candidate_id"])
    assert payload["path"] == str(candidate_dir / "factor.py.candidate")
    assert payload["metadata_path"] == str(candidate_dir / "metadata.json")
    assert isinstance(payload["manifest_digest"], str)
    assert len(payload["manifest_digest"]) == 64
    # Legacy key=value line still precedes the JSON line (regex fallback safe).
    assert "status=pending" in result.output


def test_inspect_factor_candidate_json_returns_one_review_bundle(tmp_path) -> None:
    from quant_system.agent.candidate_pool import CandidatePool

    propose_result, output_dir = _propose_factor(tmp_path)
    candidate_id = _candidate_id(propose_result.output)
    digest = CandidatePool(output_dir).get(candidate_id).manifest_digest

    result = runner.invoke(
        app,
        [
            "agent",
            "inspect-factor-candidate",
            "--candidate-id",
            candidate_id,
            "--expected-digest",
            digest,
            "--agent-output-dir",
            str(output_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    assert payload["candidate_id"] == candidate_id
    assert payload["manifest_digest"] == digest
    assert payload["factor_id"]
    assert payload["approval_binding"] == "pending"
    assert payload["source_path"].endswith("factor.py.candidate")
    assert "BaseFactor" in payload["source"]


# --- agent review -----------------------------------------------------------


def test_agent_review_missing_expected_status_exits_2(tmp_path) -> None:
    from quant_system.agent.candidate_pool import CandidatePool

    propose_result, output_dir = _propose_factor(tmp_path)
    candidate_id = _candidate_id(propose_result.output)
    digest = CandidatePool(output_dir).get(candidate_id).manifest_digest

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
            "missing status CAS field",
            "--expected-digest",
            digest,
            "--agent-output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 2
    assert not (
        Path(output_dir) / "agent" / "candidates" / candidate_id / "approved.lock"
    ).exists()


def test_agent_review_missing_expected_digest_exits_2(tmp_path) -> None:
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
            "missing digest CAS field",
            "--expected-status",
            "pending",
            "--agent-output-dir",
            str(output_dir),
        ],
    )
    assert result.exit_code == 2
    assert not (
        Path(output_dir) / "agent" / "candidates" / candidate_id / "approved.lock"
    ).exists()


def test_agent_list_candidates_isolates_corrupt_and_verified(tmp_path) -> None:
    import json

    from quant_system.agent.candidate_pool import CandidatePool

    propose_result, output_dir = _propose_factor(tmp_path)
    good_id = _candidate_id(propose_result.output)
    digest = CandidatePool(output_dir).get(good_id).manifest_digest

    legacy = Path(output_dir) / "agent" / "candidates" / "legacy-pending"
    legacy.mkdir(parents=True)
    (legacy / "metadata.json").write_text(
        json.dumps(
            {
                "candidate_id": "legacy-pending",
                "task_id": "t",
                "artifact_type": "factor",
                "goal": "legacy",
                "universe": ["SPY"],
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "files": ["factor.py.candidate"],
                "safety": {
                    "auto_promotion": False,
                    "requires_human_review": True,
                    "review_status": "pending",
                },
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    (legacy / "factor.py.candidate").write_text("# legacy\n", encoding="utf-8")
    broken = Path(output_dir) / "agent" / "candidates" / "broken"
    broken.mkdir()
    (broken / "metadata.json").write_text("{not-json", encoding="utf-8")

    result = runner.invoke(
        app,
        ["agent", "list-candidates", "--agent-output-dir", str(output_dir)],
    )
    assert result.exit_code == 0, result.output
    assert f"candidate_id={good_id}" in result.output
    assert f"manifest_digest={digest}" in result.output
    assert "approve_cmd=" not in result.output
    assert "quant-system agent review" not in result.output
    assert "review_authority=withheld_use_exact_detail" in result.output
    assert "integrity=migration_required" in result.output
    assert "observed_manifest_digest=" in result.output
    assert "migration_evidence_approval_disabled" in result.output
    assert "integrity=corrupt" in result.output
    # Authoritative approve digest never appears for migration/corrupt.
    for line in result.output.splitlines():
        if "integrity=migration_required" in line or "integrity=corrupt" in line:
            assert " manifest_digest=" not in f" {line}"
            # observed_manifest_digest is allowed for migration; reject bare key.
            tokens = line.split()
            assert not any(token.startswith("manifest_digest=") for token in tokens)
            assert "approve_cmd=" not in line


def test_external_factor_source_preserves_exact_crlf_bytes(tmp_path) -> None:
    source = tmp_path / "reviewed_factor.py"
    reviewed_bytes = b"class ReviewedFactor:\r\n    factor_id = 'reviewed'\r\n"
    source.write_bytes(reviewed_bytes)
    output_dir = tmp_path / "agent_run"

    result = runner.invoke(
        app,
        [
            "agent",
            "propose-factor",
            "--goal",
            "preserve reviewed bytes",
            "--source-file",
            str(source),
            "--agent-output-dir",
            str(output_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    candidate_path = (
        output_dir
        / "agent"
        / "candidates"
        / payload["candidate_id"]
        / "factor.py.candidate"
    )
    assert candidate_path.read_bytes() == reviewed_bytes
    assert payload["source_sha256"] == hashlib.sha256(reviewed_bytes).hexdigest()


def test_agent_review_legacy_line_byte_identical_without_json(tmp_path) -> None:
    from quant_system.agent.candidate_pool import CandidatePool

    propose_result, output_dir = _propose_factor(tmp_path)
    candidate_id = _candidate_id(propose_result.output)
    digest = CandidatePool(output_dir).get(candidate_id).manifest_digest

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
            "--expected-digest",
            digest,
            "--expected-status",
            "pending",
            "--agent-output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    expected = f"candidate_id={candidate_id} decision=approve registration=manual_required"
    assert _last_line(result.output) == expected


def test_agent_review_json_emits_contract_on_last_line(tmp_path) -> None:
    from quant_system.agent.candidate_pool import CandidatePool

    propose_result, output_dir = _propose_factor(tmp_path)
    candidate_id = _candidate_id(propose_result.output)
    digest = CandidatePool(output_dir).get(candidate_id).manifest_digest

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
            "--expected-digest",
            digest,
            "--expected-status",
            "pending",
            "--agent-output-dir",
            str(output_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    assert set(payload) == {"candidate_id", "decision", "registration", "manifest_digest"}
    assert payload["candidate_id"] == candidate_id
    assert payload["decision"] == "approve"
    assert payload["registration"] == "manual_required"
    assert payload["manifest_digest"] == digest
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
        "data_source",
        "config",
        "config_sha256",
        "agent_summary",
        "agent_summary_sha256",
        "report",
        "report_sha256",
        "approved_candidates_loaded",
        "candidate_binding",
    }
    assert payload["experiment_id"] == "e-json-1"
    assert payload["run_count"] == 2
    assert payload["best_run_id"] == "run-7"
    assert payload["data_source"] == "sample"
    assert payload["config"] == str(tmp_path / "c")
    assert payload["config_sha256"] == hashlib.sha256(
        (tmp_path / "c").read_bytes()
    ).hexdigest()
    assert payload["agent_summary"] == str(tmp_path / "a.json")
    assert payload["agent_summary_sha256"] == hashlib.sha256(
        (tmp_path / "a.json").read_bytes()
    ).hexdigest()
    assert payload["report"] == str(tmp_path / "rep.md")
    assert payload["report_sha256"] == hashlib.sha256(
        (tmp_path / "rep.md").read_bytes()
    ).hexdigest()
    assert payload["approved_candidates_loaded"] == []
    assert payload["candidate_binding"] is None
    # Legacy summary line still precedes the JSON line.
    assert "experiment_id=e-json-1" in result.output


def test_run_config_json_records_the_exact_candidate_binding(tmp_path, monkeypatch) -> None:
    _patch_experiment(monkeypatch, tmp_path)
    digest = "d" * 64
    monkeypatch.setattr(
        cli_module,
        "load_approved_factor_candidate",
        lambda registry, **kwargs: CandidateFactorBinding(
            candidate_id="cand-x",
            manifest_digest=digest,
            factor_id="candidate_x",
        ),
    )

    result = runner.invoke(
        app,
        [
            "experiment",
            "run-config",
            "--config",
            str(_write_experiment_config(tmp_path)),
            "--candidate-id",
            "cand-x",
            "--expected-digest",
            digest,
            "--agent-output-dir",
            str(tmp_path / "agent-output"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(_last_line(result.output))
    assert payload["approved_candidates_loaded"] == ["candidate_x"]
    assert payload["candidate_binding"] == {
        "candidate_id": "cand-x",
        "manifest_digest": digest,
        "factor_id": "candidate_x",
    }


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
