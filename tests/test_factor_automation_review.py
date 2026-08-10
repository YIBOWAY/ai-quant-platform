from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from quant_system.agent.candidate_pool import CandidatePool
from quant_system.cli import app
from quant_system.config.settings import reload_settings

runner = CliRunner()
POLICY_DIGEST = "a" * 64
INTAKE_DIGEST = "b" * 64


def _pending_candidate(root: Path):
    return CandidatePool(root).write_candidate(
        task_id="factor-automation-review",
        goal="machine policy reviewed factor",
        artifact_type="factor",
        filename="factor.py.candidate",
        content=(
            "from quant_system.factors.base import BaseFactor\n"
            "class AutoFactor(BaseFactor):\n"
            "    factor_id = 'auto_factor'\n"
        ),
        universe=["SPY", "QQQ"],
    )


def _invoke(root: Path, candidate_id: str, digest: str, *, enabled: bool):
    return runner.invoke(
        app,
        [
            "agent",
            "auto-review",
            "--candidate-id",
            candidate_id,
            "--expected-digest",
            digest,
            "--expected-status",
            "pending",
            "--policy-digest",
            POLICY_DIGEST,
            "--intake-contract-digest",
            INTAKE_DIGEST,
            "--agent-output-dir",
            str(root),
            "--json",
        ],
        env={"QS_FACTOR_AUTOMATION_MODE": "true" if enabled else "false"},
    )


def test_factor_automation_settings_default_off_and_parse_exact_env(monkeypatch) -> None:
    monkeypatch.delenv("QS_FACTOR_AUTOMATION_MODE", raising=False)
    monkeypatch.delenv("QS_FACTOR_AUTOMATION_AUTO_LAND", raising=False)
    assert reload_settings().factor_automation.mode is False
    assert reload_settings().factor_automation.auto_land is False

    monkeypatch.setenv("QS_FACTOR_AUTOMATION_MODE", "true")
    monkeypatch.setenv("QS_FACTOR_AUTOMATION_AUTO_LAND", "true")
    settings = reload_settings()
    assert settings.factor_automation.mode is True
    assert settings.factor_automation.auto_land is True


def test_auto_review_flag_off_makes_no_candidate_mutation(tmp_path: Path) -> None:
    artifact = _pending_candidate(tmp_path)
    result = _invoke(
        tmp_path,
        artifact.candidate_id,
        str(artifact.manifest_digest),
        enabled=False,
    )

    assert result.exit_code == 1
    assert "factor_automation_disabled" in result.output
    assert not (artifact.path.parent / "approved.lock").exists()


def test_auto_review_writes_auto_policy_and_intake_bound_lock(tmp_path: Path) -> None:
    artifact = _pending_candidate(tmp_path)
    result = _invoke(
        tmp_path,
        artifact.candidate_id,
        str(artifact.manifest_digest),
        enabled=True,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.splitlines()[-1])
    assert payload == {
        "candidate_id": artifact.candidate_id,
        "decision": "approve",
        "intake_contract_digest": INTAKE_DIGEST,
        "manifest_digest": artifact.manifest_digest,
        "policy_digest": POLICY_DIGEST,
        "registration": "auto_promote",
        "reviewer": "auto",
    }
    lock = json.loads((artifact.path.parent / "approved.lock").read_text())
    assert lock["reviewer"] == "auto"
    assert lock["note"] == (
        f"auto:policy:{POLICY_DIGEST}:intake:{INTAKE_DIGEST}"
    )
    assert CandidatePool(tmp_path).get(artifact.candidate_id).approval_binding == "approved"

    repeated = _invoke(
        tmp_path,
        artifact.candidate_id,
        str(artifact.manifest_digest),
        enabled=True,
    )
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(repeated.output.splitlines()[-1]) == payload


def test_auto_review_rejects_bad_digest_before_lock_write(tmp_path: Path) -> None:
    artifact = _pending_candidate(tmp_path)
    result = runner.invoke(
        app,
        [
            "agent",
            "auto-review",
            "--candidate-id",
            artifact.candidate_id,
            "--expected-digest",
            str(artifact.manifest_digest),
            "--expected-status",
            "pending",
            "--policy-digest",
            "not-a-digest",
            "--intake-contract-digest",
            INTAKE_DIGEST,
            "--agent-output-dir",
            str(tmp_path),
        ],
        env={"QS_FACTOR_AUTOMATION_MODE": "true"},
    )

    assert result.exit_code != 0
    assert not (artifact.path.parent / "approved.lock").exists()


def test_auto_commit_and_land_surfaces_refuse_before_state_io_when_flags_off() -> None:
    for argv in (
        ["agent", "promote-auto-commit", "--promotion-id", "promo-disabled"],
        [
            "agent",
            "promote-auto-land",
            "--promotion-id",
            "promo-disabled",
            "--expected-base-commit",
            "a" * 40,
            "--expected-reviewed-commit",
            "b" * 40,
        ],
    ):
        result = runner.invoke(
            app,
            argv,
            env={
                "QS_FACTOR_AUTOMATION_MODE": "false",
                "QS_FACTOR_AUTOMATION_AUTO_LAND": "false",
            },
        )
        assert result.exit_code == 1
        assert "factor_automation_disabled" in result.output
