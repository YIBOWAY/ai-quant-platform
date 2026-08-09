"""Production AgentWorkspace wiring for durable paper-research Gates."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from quant_system.api.schemas.workspace import (
    GateProjectionResponse,
    WorkspaceFollowResponse,
    WorkspaceSnapshotResponse,
)
from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
from quant_system.hermes.agent_workspace_actions import (
    ConfirmFormulaSource,
    PreparePromotionReview,
    ReviewCandidateCAS,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.paper_gate_authority import (
    PaperGateAuthorityConflict,
    PaperGateAuthorityUnavailable,
    PaperGateReceipt,
)
from quant_system.hermes.submission_saga import ActionReceipt, submit_action

WORKSPACE_ID = "workspace-root"
DIGEST = "a" * 64
BASE_COMMIT = "b" * 40


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _documents() -> list[tuple[dict[str, object], str, str]]:
    return [
        (
            {
                "schema_version": 1,
                "kind": "gate1.formula_source.confirm",
                "client_action_id": "paper-bff-gate1",
                "workspace": {"workspace_id": WORKSPACE_ID},
                "task_ref": "task:paper-reversal",
                "reviewed_source_sha256": DIGEST,
                "confirmation_note": "exact source reviewed",
            },
            "confirm-formula",
            "confirmed",
        ),
        (
            {
                "schema_version": 1,
                "kind": "gate2.candidate.review",
                "client_action_id": "paper-bff-gate2",
                "workspace": {"workspace_id": WORKSPACE_ID},
                "candidate_ref": "candidate:paper-reversal",
                "expected_digest": DIGEST,
                "expected_status": "pending",
                "note": "exact candidate reviewed",
            },
            "approve",
            "reviewed",
        ),
        (
            {
                "schema_version": 1,
                "kind": "gate3.promotion_review.prepare",
                "client_action_id": "paper-bff-gate3",
                "workspace": {"workspace_id": WORKSPACE_ID},
                "candidate_ref": "candidate:paper-reversal",
                "expected_digest": DIGEST,
                "final_backtest_receipt_ref": ("receipt:backtest-0123456789abcdef0123456789abcdef"),
                "base_commit": BASE_COMMIT,
            },
            "promote",
            "prepared",
        ),
    ]


class _Port:
    pass


class _RecordingAuthority:
    def __init__(
        self,
        *,
        status: str,
        failure: Exception | None = None,
    ) -> None:
        self.status = status
        self.failure = failure
        self.calls: list[tuple[object, str, object]] = []

    def execute_action(
        self,
        action: ConfirmFormulaSource | ReviewCandidateCAS | PreparePromotionReview,
        *,
        action_digest: str,
        port: object,
    ) -> PaperGateReceipt:
        self.calls.append((action, action_digest, port))
        if self.failure is not None:
            raise self.failure
        operation = {
            ConfirmFormulaSource: "confirm-formula",
            ReviewCandidateCAS: "approve",
            PreparePromotionReview: "promote",
        }[type(action)]
        return PaperGateReceipt(
            operation=operation,  # type: ignore[arg-type]
            gate_id=f"pgate-{operation}",
            gate_kind={
                "confirm-formula": "gate1",
                "approve": "gate2",
                "promote": "gate3",
            }[operation],  # type: ignore[arg-type]
            workspace_id=action.workspace.workspace_id,
            client_action_id=action.client_action_id,
            action_digest=action_digest,
            status=self.status,  # type: ignore[arg-type]
            hqa_operation_id="pgate-0123456789abcdef0123456789abcdef",
            managed_session_ref="session:managed-paper-session",
            occurred_at=datetime.now(UTC),
            reason_code=(
                "paper_gate_outcome_unknown" if self.status == "outcome_unknown" else None
            ),
        )


@pytest.mark.parametrize(("document", "_operation", "status"), _documents())
def test_production_paper_gate_actions_use_durable_authority(
    document: dict[str, object],
    _operation: str,
    status: str,
) -> None:
    authority = _RecordingAuthority(status=status)
    port = _Port()

    receipt = submit_action(
        _settings(),
        document,
        mutation_enabled=True,
        paper_gate_authority=authority,  # type: ignore[arg-type]
        paper_gate_port=port,  # type: ignore[arg-type]
    )

    assert receipt.status == "accepted"
    assert receipt.gate_id == f"pgate-{_operation}"
    assert receipt.platform_session_id == "managed-paper-session"
    assert receipt.to_public_dict()["session_ref"] == ("session:managed-paper-session")
    assert receipt.command_id is None
    assert len(authority.calls) == 1
    called_action, called_digest, called_port = authority.calls[0]
    assert called_action.client_action_id == document["client_action_id"]  # type: ignore[attr-defined]
    assert called_digest == receipt.action_digest
    assert called_port is port


def test_outcome_unknown_is_reconciliation_not_blind_retry() -> None:
    document, _, _ = _documents()[0]
    authority = _RecordingAuthority(status="outcome_unknown")

    receipt = submit_action(
        _settings(),
        document,
        mutation_enabled=True,
        paper_gate_authority=authority,  # type: ignore[arg-type]
        paper_gate_port=_Port(),  # type: ignore[arg-type]
    )

    assert receipt.status == "outcome_unknown"
    assert receipt.recovery_action == "follow_and_reconcile_original_action"
    assert receipt.reason_code == "paper_gate_outcome_unknown"
    assert receipt.command_id is None


@pytest.mark.parametrize(
    ("failure", "status", "reason"),
    [
        (
            PaperGateAuthorityConflict("exact challenge mismatch"),
            "conflict",
            "paper_gate_authority_conflict",
        ),
        (
            PaperGateAuthorityUnavailable(
                "post-HQA finalization uncertain",
                code="paper_gate_finalization_outcome_unknown",
            ),
            "outcome_unknown",
            "paper_gate_finalization_outcome_unknown",
        ),
        (
            PaperGateAuthorityUnavailable(
                "original action is executing",
                code="paper_gate_action_in_progress",
            ),
            "reconciling",
            "paper_gate_action_in_progress",
        ),
    ],
)
def test_durable_paper_gate_failure_mapping(
    failure: Exception,
    status: str,
    reason: str,
) -> None:
    document, _, _ = _documents()[0]
    authority = _RecordingAuthority(status="pending", failure=failure)

    receipt = submit_action(
        _settings(),
        document,
        mutation_enabled=True,
        paper_gate_authority=authority,  # type: ignore[arg-type]
        paper_gate_port=_Port(),  # type: ignore[arg-type]
    )

    assert receipt.status == status
    assert receipt.reason_code == reason
    assert receipt.command_id is None


def test_platform_workspace_mounts_settings_built_paper_gate_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import agent_workspace as workspace_module

    captured: dict[str, Any] = {}

    class _BuiltAuthority:
        def __init__(self, settings: Settings) -> None:
            captured["authority_settings"] = settings

        def list_observed(self, _workspace_id: str) -> list[dict[str, object]]:
            return []

    built_port = object()

    def _capture_submit(
        _settings_value: Settings,
        action: object,
        **kwargs: object,
    ) -> ActionReceipt:
        captured["action"] = action
        captured.update(kwargs)
        return ActionReceipt(
            status="unavailable",
            client_action_id="paper-bff-gate1",
            action_digest=DIGEST,
            workspace_id=WORKSPACE_ID,
            reason_code="test_capture",
            mutation_enabled=True,
        )

    monkeypatch.setattr(workspace_module, "PaperGateAuthority", _BuiltAuthority)
    monkeypatch.setattr(
        workspace_module,
        "build_subprocess_paper_gate_port",
        lambda settings: captured.setdefault("port_settings", settings) and built_port,
    )
    monkeypatch.setattr(workspace_module, "submit_action", _capture_submit)

    settings = _settings()
    workspace = PlatformAgentWorkspace(settings, mutation_enabled=True)
    document, _, _ = _documents()[0]
    workspace.act(str(ROOT_USER_ID), document)

    assert captured["authority_settings"] is settings
    assert captured["port_settings"] is settings
    assert isinstance(captured["paper_gate_authority"], _BuiltAuthority)
    assert captured["paper_gate_port"] is built_port
    assert captured["allow_hermetic_authorities"] is False


def test_explicit_hermetic_workspace_does_not_mount_production_paper_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import agent_workspace as workspace_module

    monkeypatch.setattr(
        workspace_module,
        "PaperGateAuthority",
        lambda _settings_value: pytest.fail("production authority was mounted"),
    )
    monkeypatch.setattr(
        workspace_module,
        "build_subprocess_paper_gate_port",
        lambda _settings_value: pytest.fail("production port was mounted"),
    )

    workspace = PlatformAgentWorkspace(
        _settings(),
        mutation_enabled=True,
        hermetic_authorities=True,
    )

    assert workspace._paper_gate_authority is None
    assert workspace._paper_gate_port is None


def test_gate_response_contract_keeps_legacy_hermetic_projection_compatible() -> None:
    projected = GateProjectionResponse.model_validate(
        {
            "gate_id": "legacy-gate-1",
            "gate_kind": "gate1",
            "kind": "gate1.formula_source",
            "status": "pending",
            "expected_status": "pending",
            "task_id": "legacy-task",
            "task_ref": "task:legacy-task",
            "reviewed_source_sha256": DIGEST,
        }
    )

    assert projected.attempt_ref is None
    assert projected.command_id is None
    assert projected.command_ref is None
    assert projected.hermes_session_id is None
    assert projected.hermes_run_id is None


def test_production_snapshot_projects_only_durable_paper_gates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import agent_workspace as workspace_module

    class _BuiltAuthority:
        def __init__(self, _settings_value: Settings) -> None:
            pass

        def list_observed(self, workspace_id: str) -> list[dict[str, object]]:
            assert workspace_id == WORKSPACE_ID
            return [
                {
                    "attempt_ref": "attempt:paper-plan",
                    "command_id": "11111111-1111-4111-8111-111111111111",
                    "command_ref": ("command:11111111-1111-4111-8111-111111111111"),
                    "gate_id": "paper-gate-projected",
                    "gate_kind": "gate1",
                    "hermes_session_id": "hermes-managed-paper-session",
                    "hermes_run_id": "hermes-plan-run",
                    "hqa_run_ref": None,
                    "kind": "gate1.formula_source",
                    "status": "pending",
                    "expected_status": "pending",
                    "task_id": "paper-reversal",
                    "task_ref": "task:paper-reversal",
                    "hqa_gate_ref": "gate:hqa-paper-gate",
                    "managed_session_ref": "session:managed-paper-session",
                    "reviewed_source_sha256": DIGEST,
                }
            ]

    monkeypatch.setattr(workspace_module, "PaperGateAuthority", _BuiltAuthority)
    monkeypatch.setattr(
        workspace_module,
        "build_subprocess_paper_gate_port",
        lambda _settings_value: object(),
    )

    workspace = PlatformAgentWorkspace(_settings(), mutation_enabled=True)
    snapshot = workspace.snapshot(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
    )

    assert len(snapshot.gates) == 1
    assert snapshot.gates[0]["gate_id"] == "paper-gate-projected"
    assert snapshot.gates[0]["managed_session_ref"] == ("session:managed-paper-session")
    assert snapshot.gates[0]["hermes_session_id"] == ("hermes-managed-paper-session")
    assert snapshot.approvals == ()
    assert snapshot.tasks == ("task:paper-reversal",)
    assert snapshot.attempts == ("attempt:paper-plan",)
    assert snapshot.runs == ()
    assert snapshot.authority_health["task"] == "ready"
    assert snapshot.authority_health["attempt"] == "ready"
    assert snapshot.authority_health["run"] == "ready"
    assert snapshot.authority_health["gate_1"] == "ready"
    assert snapshot.authority_health["gate_2"] == "ready"
    assert snapshot.authority_health["gate_3"] == "ready"
    validated_snapshot = WorkspaceSnapshotResponse.model_validate(snapshot.to_public_dict())
    assert validated_snapshot.gates[0].hqa_gate_ref == "gate:hqa-paper-gate"
    assert validated_snapshot.gates[0].managed_session_ref == ("session:managed-paper-session")

    follow = workspace.follow(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
        after=0,
    )
    validated_follow = WorkspaceFollowResponse.model_validate(follow.to_public_dict())
    assert validated_follow.gates is not None
    assert validated_follow.gates[0].gate_id == "paper-gate-projected"
