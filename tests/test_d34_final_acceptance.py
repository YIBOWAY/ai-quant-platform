from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from quant_system.cli import app
from quant_system.d34.final_acceptance import (
    evaluate_final_acceptance,
    verify_current_acceptance,
)

runner = CliRunner()


def test_final_acceptance_binds_time_gate_zero_duplicates_and_no_live() -> None:
    receipt = evaluate_final_acceptance(
        workspace_id="default",
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
        safety={
            "contract": "hqa.effective_paper_safety/v2",
            "workspace_id": "default",
            "paper_execution_enabled": True,
            "emergency_stop": {"active": False},
            "d34": {"queued_jobs": 0, "running_jobs": 0},
            "budget": {"limit_usd": "100.00", "spent_usd": "40.000000"},
            "canaries": {"allocated_cash": "40000.00"},
            "soak": {
                "completed_cycles": 10,
                "required_completed_cycles": 10,
                "canary_observation_days": 5,
                "required_canary_observation_days": 5,
                "time_gate_ready": True,
            },
            "risk": {"max_total_nav_fraction": 0.1},
            "live_execution_enabled": False,
        },
        database_facts={
            "jobs": 10,
            "artifacts": 10,
            "canaries": 10,
            "policy_decisions": 10,
            "active_canary_nav_fraction": "0.040000000",
            "non_paper_artifacts": 0,
            "artifact_policy_lineage_mismatches": 0,
            "canary_sleeve_links": [
                {"sleeve_id": "sleeve-d34-a", "artifact_id": "artifact-d34-a"}
            ],
            "duplicate_groups": {
                "jobs_job_key": 0,
                "artifact_job": 0,
                "canary_artifact": 0,
                "canary_sleeve": 0,
                "policy_identity": 0,
                "budget_consumption": 0,
            },
        },
        paper_facts={
            "d34_sleeves": 10,
            "signals": 10,
            "executions": 10,
            "duplicate_signal_ids": 0,
            "duplicate_execution_ids": 0,
            "duplicate_order_batches": 0,
            "live_registry_factor_matches": 0,
            "missing_factor_ids": 0,
            "sleeve_artifact_links": [
                {"sleeve_id": "sleeve-d34-a", "artifact_id": "artifact-d34-a"}
            ],
            "pending_execution_journals": 0,
            "corrupt_execution_journals": 0,
            "non_paper_only_sleeves": 0,
        },
    )

    assert receipt["accepted"] is True
    assert receipt["blockers"] == []
    assert receipt["live_execution_enabled"] is False
    assert len(receipt["receipt_digest"]) == 64


def test_final_acceptance_rejects_duplicate_execution_and_live_eligibility() -> None:
    receipt = evaluate_final_acceptance(
        workspace_id="default",
        observed_at=datetime(2026, 8, 20, tzinfo=UTC),
        safety={
            "contract": "hqa.effective_paper_safety/v2",
            "workspace_id": "default",
            "paper_execution_enabled": True,
            "emergency_stop": {"active": False},
            "d34": {"queued_jobs": 0, "running_jobs": 0},
            "budget": {"limit_usd": "100.00", "spent_usd": "40.000000"},
            "soak": {"completed_cycles": 10, "time_gate_ready": True},
            "risk": {"max_total_nav_fraction": 0.1},
            "live_execution_enabled": True,
        },
        database_facts={
            "jobs": 10,
            "artifacts": 10,
            "canaries": 10,
            "policy_decisions": 10,
            "active_canary_nav_fraction": "0.040000000",
            "non_paper_artifacts": 0,
            "artifact_policy_lineage_mismatches": 0,
            "canary_sleeve_links": [
                {"sleeve_id": "sleeve-d34-a", "artifact_id": "artifact-d34-a"}
            ],
            "duplicate_groups": {
                "jobs_job_key": 0,
                "artifact_job": 0,
                "canary_artifact": 0,
                "canary_sleeve": 0,
                "policy_identity": 0,
                "budget_consumption": 0,
            },
        },
        paper_facts={
            "d34_sleeves": 10,
            "signals": 10,
            "executions": 11,
            "duplicate_signal_ids": 0,
            "duplicate_execution_ids": 1,
            "duplicate_order_batches": 1,
            "live_registry_factor_matches": 1,
            "missing_factor_ids": 1,
            "sleeve_artifact_links": [
                {"sleeve_id": "sleeve-d34-a", "artifact_id": "artifact-d34-other"}
            ],
            "pending_execution_journals": 0,
            "corrupt_execution_journals": 0,
            "non_paper_only_sleeves": 0,
        },
    )

    assert receipt["accepted"] is False
    assert receipt["blockers"] == [
        "live_execution_not_disabled",
        "d34_canary_sleeve_link_mismatch",
        "duplicate_d34_execution_id",
        "duplicate_d34_order_batch",
        "d34_factor_present_in_live_registry",
        "d34_sleeve_factor_identity_missing",
    ]


def test_final_acceptance_cli_writes_and_emits_one_digest_bound_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[object] = []
    receipt = {
        "contract": "hqa.d34_final_acceptance/v1",
        "workspace_id": "default",
        "accepted": False,
        "blockers": ["d34_time_gate_not_ready"],
        "receipt_digest": "d" * 64,
    }

    class Auditor:
        def __init__(self, _settings, *, now) -> None:
            calls.append(now)

        def audit(self, *, workspace_id: str):
            calls.append(workspace_id)
            return receipt

        def write(self, observed):
            calls.append(observed)
            return tmp_path / "latest.json"

    monkeypatch.setattr("quant_system.d34.cli.D34FinalAcceptanceAuditor", Auditor, raising=False)

    result = runner.invoke(app, ["d34", "final-acceptance"])

    assert result.exit_code == 1
    assert json.loads(result.output) == receipt
    assert calls[1:] == ["default", receipt]


def test_cutover_rejects_a_previously_accepted_receipt_after_facts_drift() -> None:
    prior = {
        "accepted": True,
        "blockers": [],
        "live_execution_enabled": False,
        "soak": {"time_gate_ready": True, "completed_cycles": 10},
        "budget": {"spent_usd": "40.000000"},
        "risk": {"max_total_nav_fraction": 0.1},
        "database_facts": {"jobs": 10, "duplicate_groups": {"jobs_job_key": 0}},
        "paper_facts": {"executions": 10, "duplicate_execution_ids": 0},
    }
    current = {
        **prior,
        "database_facts": {"jobs": 11, "duplicate_groups": {"jobs_job_key": 0}},
    }

    try:
        verify_current_acceptance(prior, current)
    except ValueError as exc:
        assert str(exc) == "d34_final_acceptance_facts_changed"
    else:
        raise AssertionError("cutover must reject a stale final acceptance receipt")
