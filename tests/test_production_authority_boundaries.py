"""Production AgentWorkspace must never expose hermetic V7 authorities.

The in-process V7 authorities remain useful contract-test doubles, but they
are not canonical Hermes/HQA/platform authorities and disappear on restart.
This suite protects the production workspace construction path from silently
mounting those doubles when local mutation is enabled.
"""

from __future__ import annotations

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.command_approval_authority import (
    default_command_approval_authority,
    reset_default_command_approval_authority,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID

WORKSPACE_ID = "ws-production-authority-boundary"
DIGEST = "a" * 64


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def test_default_workspace_does_not_project_process_local_authorities() -> None:
    reset_default_command_approval_authority()
    try:
        default_command_approval_authority().seed_pending(
            workspace_id=WORKSPACE_ID,
            approval_id="challenge.must-stay-hermetic",
            run_id="hermes.must-stay-hermetic",
            command_digest=DIGEST,
            expires_at="2099-01-01T00:00:00.000000Z",
        )

        workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
        snapshot = workspace.snapshot(
            str(ROOT_USER_ID),
            {"workspace_id": WORKSPACE_ID},
        )

        assert snapshot.approvals == ()
        assert snapshot.gates == ()
        assert snapshot.tasks == ()
        assert snapshot.attempts == ()
        assert snapshot.runs == ()
        assert snapshot.results == ()
        for name in (
            "command_approval",
            "gate_1",
            "gate_2",
            "gate_3",
            "task",
            "attempt",
            "run",
            "result",
        ):
            assert snapshot.authority_health[name] == "unavailable"
    finally:
        reset_default_command_approval_authority()


def test_default_workspace_rejects_hermetic_vertical_action() -> None:
    workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    receipt = workspace.act(
        str(ROOT_USER_ID),
        {
            "schema_version": 1,
            "kind": "vertical.options_a.bind",
            "client_action_id": "act-production-must-refuse-fake",
            "workspace": {"workspace_id": WORKSPACE_ID},
            "ticker": "AAPL",
            "goal_note": "must not create process-local Task facts",
            "expiry": "2026-12-18",
            "strike": 200.0,
            "bid": 5.0,
            "ask": 5.2,
            "delta": 0.25,
            "iv": 0.3,
            "apr": 0.1,
            "include_provider_evidence": True,
        },
    )

    assert receipt.status == "unavailable"
    assert receipt.reason_code == "canonical_authority_adapter_unavailable"
    assert receipt.task_id is None
    assert receipt.attempt_id is None
    assert receipt.run_id is None
    assert receipt.result_id is None
