"""PostgreSQL authority for production paper-research Gate 1/2/3.

The browser action is durably claimed before HQA is invoked.  PostgreSQL owns
owner/workspace/action CAS and restart recovery; HQA owns exact formula
confirmation, candidate binding/review, and Gate 3 promotion preparation.
Human notes and source bytes cross the fixed subprocess stdin seam but are
never persisted in this authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from quant_system.config.settings import Settings
from quant_system.hermes.agent_workspace_actions import (
    ConfirmFormulaSource,
    PreparePromotionReview,
    ReviewCandidateCAS,
    canonical_action_digest,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.paper_gate_port import (
    PaperGateOperation,
    PaperGatePortError,
)
from quant_system.storage.database import (
    SCHEMA,
    Database,
    DatabaseUnavailable,
    get_database,
)

PAPER_GATE_SCHEMA_VERSION = 1
PaperGateKind = Literal["gate1", "gate2", "gate3"]
PaperGateStatus = Literal[
    "pending",
    "confirmed",
    "reviewed",
    "prepared",
    "rejected",
    "outcome_unknown",
]

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TASK_REF_RE = re.compile(r"^task:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ATTEMPT_REF_RE = re.compile(r"^attempt:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_GATE_REF_RE = re.compile(r"^gate:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_RUN_REF_RE = re.compile(r"^run:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_COMMAND_REF_RE = re.compile(
    r"^(?:command:)?[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_CONFIRMATION_RE = re.compile(r"^gate1-[0-9a-f]{32}$")
_FINAL_RECEIPT_RE = re.compile(r"^backtest-[0-9a-f]{32}$")
_PROMOTION_RE = re.compile(r"^promo-[0-9a-f]{32}(?:-r(?:[2-9]|[1-9][0-9]+))?$")
_HQA_RECEIPT_RE = re.compile(r"^hqa-paper-gate:pgate-[0-9a-f]{32}$")
_HQA_COMPLETION_RECEIPT_RE = re.compile(r"^hqa-paper-completion:[0-9a-f]{32}$")
_PROVIDER_EVIDENCE_RE = re.compile(r"^provider-evidence:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_WORKFLOW_AUDIT_REF_RE = re.compile(r"^workflow-audit:[0-9a-f]{64}$")
_WORKFLOW_OPERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_MANAGED_SESSION_REF_RE = re.compile(r"^session:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_WORKFLOW_EVENT_RE = re.compile(r"^event:[0-9a-f]{64}$")
_READY_SESSION_FUNCTION_BODY_SHA256 = (
    "5bc031244c5d0d99e45bc4b867180fcba86c66892b12aa3741f1b6dd78774626"
)
# The port permits a 300-second subprocess deadline. A second caller must
# never expire a still-running HQA mutation, so the durable lease includes a
# fixed 30-second finalization margin.
_LEASE_SECONDS = 330

_ACTION_KIND = {
    ConfirmFormulaSource: "gate1_formula_source_confirm",
    ReviewCandidateCAS: "gate2_candidate_review",
    PreparePromotionReview: "gate3_promotion_review_prepare",
}
_OPERATION = {
    ConfirmFormulaSource: "confirm-formula",
    ReviewCandidateCAS: "approve",
    PreparePromotionReview: "promote",
}
_PUBLIC_KIND = {
    "gate1": "gate1.formula_source",
    "gate2": "gate2.candidate",
    "gate3": "gate3.promotion_review",
}

_CHALLENGE_COLUMNS = """
    gate_id,
    owner_user_id,
    workspace_id,
    gate_kind,
    status,
    task_ref,
    expected_task_version,
    attempt_ref,
    hqa_gate_ref,
    platform_session_id,
    hermes_session_id,
    command_id,
    hermes_run_id,
    hqa_run_ref,
    provider_evidence_ref,
    subject_command_id,
    subject_hermes_run_id,
    subject_run_attestation_ref,
    subject_run_attestation_digest,
    final_backtest_provider,
    final_backtest_receipt_digest,
    final_backtest_config_ref,
    final_backtest_config_digest,
    final_backtest_summary_ref,
    final_backtest_summary_digest,
    final_backtest_report_ref,
    final_backtest_report_digest,
    parent_gate_id,
    source_file_ref,
    universe,
    reviewed_source_sha256,
    gate1_confirmation_id,
    candidate_id,
    expected_digest,
    expected_status,
    final_backtest_receipt_id,
    base_commit,
    hqa_receipt_ref,
    hqa_receipt_digest,
    promotion_id,
    worktree_ref,
    patch_ref,
    manifest_ref,
    decided_action_kind,
    decided_client_action_id,
    decided_action_digest,
    decided_at,
    created_at,
    updated_at
"""
_QUALIFIED_CHALLENGE_COLUMNS = ",\n".join(
    f"challenge.{name.strip()}" for name in _CHALLENGE_COLUMNS.split(",") if name.strip()
)
_COMPLETION_COLUMNS = """
    gate_id,
    owner_user_id,
    workspace_id,
    task_ref,
    task_version,
    task_status,
    task_terminal_outcome,
    plan_version,
    plan_digest,
    plan_confirmation_note_digest,
    attempt_ref,
    attempt_status,
    attempt_terminal_outcome,
    domain_gate_ref,
    domain_gate_outcome,
    hqa_run_ref,
    provider_evidence_ref,
    subject_command_id,
    subject_hermes_run_id,
    subject_run_attestation_ref,
    subject_run_attestation_digest,
    final_backtest_provider,
    final_backtest_receipt_digest,
    final_backtest_config_ref,
    final_backtest_config_digest,
    final_backtest_summary_ref,
    final_backtest_summary_digest,
    final_backtest_report_ref,
    final_backtest_report_digest,
    promotion_id,
    reviewed_commit,
    candidate_id,
    candidate_digest,
    final_backtest_receipt_id,
    base_commit,
    attempt_completion_operation_id,
    attempt_completion_event_id,
    task_completion_operation_id,
    task_completion_event_id,
    workflow_audit_status,
    workflow_audit_ref,
    workflow_audit_digest,
    hqa_completion_receipt_ref,
    hqa_completion_receipt_digest,
    completion_evidence,
    created_at
"""
_COMPLETION_EVIDENCE_FIELDS = frozenset(
    {
        "schema_version",
        "task_ref",
        "task_version",
        "task_status",
        "task_terminal_outcome",
        "attempt_ref",
        "attempt_status",
        "attempt_terminal_outcome",
        "domain_gate_ref",
        "domain_gate_outcome",
        "hqa_run_ref",
        "provider_evidence_ref",
        "promotion_id",
        "reviewed_commit",
        "candidate_id",
        "candidate_digest",
        "final_backtest_receipt_id",
        "base_commit",
        "attempt_completion_operation_id",
        "attempt_completion_event_id",
        "task_completion_operation_id",
        "task_completion_event_id",
        "workflow_audit_status",
        "workflow_audit_ref",
        "workflow_audit_digest",
    }
)


class PaperGateExecutionPort(Protocol):
    def execute(
        self,
        operation: PaperGateOperation,
        request: Mapping[str, object],
    ) -> dict[str, object]: ...


class PaperGateAuthorityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PaperGateAuthorityUnavailable(PaperGateAuthorityError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "paper_gate_authority_unavailable",
    ) -> None:
        super().__init__(code, message)


class PaperGateAuthorityValidationError(PaperGateAuthorityError):
    def __init__(self, message: str) -> None:
        super().__init__("paper_gate_authority_validation", message)


class PaperGateAuthorityConflict(PaperGateAuthorityError):
    def __init__(self, message: str) -> None:
        super().__init__("paper_gate_authority_conflict", message)


class PaperGateNotFound(PaperGateAuthorityError):
    def __init__(self, message: str = "paper gate challenge is missing") -> None:
        super().__init__("paper_gate_not_found", message)


@dataclass(frozen=True)
class RegisterPaperGateChallenge:
    gate_id: str
    gate_kind: PaperGateKind
    workspace_id: str
    task_ref: str
    expected_task_version: int
    platform_session_id: str
    hermes_session_id: str
    command_id: str
    attempt_ref: str | None = None
    hqa_gate_ref: str | None = None
    hermes_run_id: str | None = None
    hqa_run_ref: str | None = None
    provider_evidence_ref: str | None = None
    subject_command_id: str | None = None
    subject_hermes_run_id: str | None = None
    subject_run_attestation_ref: str | None = None
    subject_run_attestation_digest: str | None = None
    final_backtest_provider: str | None = None
    final_backtest_receipt_digest: str | None = None
    final_backtest_config_ref: str | None = None
    final_backtest_config_digest: str | None = None
    final_backtest_summary_ref: str | None = None
    final_backtest_summary_digest: str | None = None
    final_backtest_report_ref: str | None = None
    final_backtest_report_digest: str | None = None
    parent_gate_id: str | None = None
    source_file_ref: str | None = None
    universe: str | None = None
    reviewed_source_sha256: str | None = None
    gate1_confirmation_id: str | None = None
    candidate_id: str | None = None
    expected_digest: str | None = None
    expected_status: str | None = None
    final_backtest_receipt_id: str | None = None
    base_commit: str | None = None


@dataclass(frozen=True)
class RegisterPaperGateCompletion:
    gate_id: str
    workspace_id: str
    hqa_completion_receipt_ref: str
    hqa_completion_receipt_digest: str
    completion_evidence: Mapping[str, object]


@dataclass(frozen=True)
class PaperGateCompletionRecord:
    gate_id: str
    owner_user_id: UUID
    workspace_id: str
    task_ref: str
    task_version: int
    task_status: str
    task_terminal_outcome: str
    plan_version: int
    plan_digest: str
    plan_confirmation_note_digest: str
    attempt_ref: str
    attempt_status: str
    attempt_terminal_outcome: str
    domain_gate_ref: str
    domain_gate_outcome: str
    hqa_run_ref: str
    provider_evidence_ref: str
    subject_command_id: UUID
    subject_hermes_run_id: str
    subject_run_attestation_ref: str
    subject_run_attestation_digest: str
    final_backtest_provider: str
    final_backtest_receipt_digest: str
    final_backtest_config_ref: str
    final_backtest_config_digest: str
    final_backtest_summary_ref: str
    final_backtest_summary_digest: str
    final_backtest_report_ref: str
    final_backtest_report_digest: str
    promotion_id: str
    reviewed_commit: str
    candidate_id: str
    candidate_digest: str
    final_backtest_receipt_id: str
    base_commit: str
    attempt_completion_operation_id: str
    attempt_completion_event_id: str
    task_completion_operation_id: str
    task_completion_event_id: str
    workflow_audit_status: str
    workflow_audit_ref: str
    workflow_audit_digest: str
    hqa_completion_receipt_ref: str
    hqa_completion_receipt_digest: str
    completion_evidence: Mapping[str, object]
    created_at: datetime

    def to_operator_dict(self) -> dict[str, object]:
        return {
            "attempt_ref": self.attempt_ref,
            "attempt_status": self.attempt_status,
            "attempt_terminal_outcome": self.attempt_terminal_outcome,
            "base_commit": self.base_commit,
            "candidate_digest": self.candidate_digest,
            "candidate_id": self.candidate_id,
            "completion_evidence": dict(self.completion_evidence),
            "created_at": _timestamp(self.created_at),
            "domain_gate_outcome": self.domain_gate_outcome,
            "domain_gate_ref": self.domain_gate_ref,
            "final_backtest_receipt_id": self.final_backtest_receipt_id,
            "gate_id": self.gate_id,
            "hqa_completion_receipt_digest": (self.hqa_completion_receipt_digest),
            "hqa_completion_receipt_ref": self.hqa_completion_receipt_ref,
            "hqa_run_ref": self.hqa_run_ref,
            "promotion_id": self.promotion_id,
            "provider_evidence_ref": self.provider_evidence_ref,
            "subject_command_id": str(self.subject_command_id),
            "subject_hermes_run_id": self.subject_hermes_run_id,
            "subject_run_attestation_ref": self.subject_run_attestation_ref,
            "subject_run_attestation_digest": self.subject_run_attestation_digest,
            "final_backtest_provider": self.final_backtest_provider,
            "final_backtest_receipt_digest": self.final_backtest_receipt_digest,
            "reviewed_commit": self.reviewed_commit,
            "status": "completed",
            "task_ref": self.task_ref,
            "task_status": self.task_status,
            "task_terminal_outcome": self.task_terminal_outcome,
            "task_version": self.task_version,
            "workflow_audit_digest": self.workflow_audit_digest,
            "workflow_audit_ref": self.workflow_audit_ref,
            "workflow_audit_status": self.workflow_audit_status,
            "workspace_id": self.workspace_id,
        }


@dataclass(frozen=True)
class PaperGateChallengeRecord:
    gate_id: str
    owner_user_id: UUID
    workspace_id: str
    gate_kind: PaperGateKind
    status: str
    task_ref: str
    expected_task_version: int
    attempt_ref: str | None
    hqa_gate_ref: str
    platform_session_id: str
    hermes_session_id: str
    command_id: UUID
    hermes_run_id: str | None
    hqa_run_ref: str | None
    provider_evidence_ref: str | None
    subject_command_id: UUID | None
    subject_hermes_run_id: str | None
    subject_run_attestation_ref: str | None
    subject_run_attestation_digest: str | None
    final_backtest_provider: str | None
    final_backtest_receipt_digest: str | None
    final_backtest_config_ref: str | None
    final_backtest_config_digest: str | None
    final_backtest_summary_ref: str | None
    final_backtest_summary_digest: str | None
    final_backtest_report_ref: str | None
    final_backtest_report_digest: str | None
    parent_gate_id: str | None
    source_file_ref: str | None
    universe: str | None
    reviewed_source_sha256: str | None
    gate1_confirmation_id: str | None
    candidate_id: str | None
    expected_digest: str | None
    expected_status: str | None
    final_backtest_receipt_id: str | None
    base_commit: str | None
    hqa_receipt_ref: str | None
    hqa_receipt_digest: str | None
    promotion_id: str | None
    worktree_ref: str | None
    patch_ref: str | None
    manifest_ref: str | None
    decided_action_kind: str | None
    decided_client_action_id: str | None
    decided_action_digest: str | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def to_public_dict(
        self,
        *,
        action_state: str | None = None,
        action_error: str | None = None,
    ) -> dict[str, object]:
        status = self.status
        note: str | None = None
        if status == "rejected":
            note = action_error or "paper_gate_rejected"
        elif status == "outcome_unknown":
            note = "paper_gate_outcome_unknown; reconcile_original_action"
        elif action_state == "failed" and status == "pending":
            status = "rejected"
            note = action_error or "paper_gate_rejected"
        elif action_state == "outcome_unknown" and status == "pending":
            note = "paper_gate_outcome_unknown; reconcile_original_action"
        elif status == "confirmed":
            note = "formula_source_confirmed"
        elif status == "reviewed":
            note = "candidate_review_approved"
        elif status == "prepared":
            note = "promotion_review_prepared; human_git_commit_required"
        payload: dict[str, object] = {
            "attempt_ref": self.attempt_ref,
            "command_id": str(self.command_id),
            "command_ref": f"command:{self.command_id}",
            "gate_id": self.gate_id,
            "gate_kind": self.gate_kind,
            "hermes_session_id": self.hermes_session_id,
            "hermes_run_id": self.hermes_run_id,
            "hqa_run_ref": self.hqa_run_ref,
            "provider_evidence_ref": self.provider_evidence_ref,
            "kind": _PUBLIC_KIND[self.gate_kind],
            "status": status,
            "expected_status": "pending" if status == "pending" else status,
            "task_id": self.task_ref.removeprefix("task:"),
            "task_ref": self.task_ref,
            "hqa_gate_ref": self.hqa_gate_ref,
            "managed_session_ref": f"session:{self.platform_session_id}",
        }
        if self.reviewed_source_sha256 is not None:
            payload["reviewed_source_sha256"] = self.reviewed_source_sha256
        if self.candidate_id is not None:
            payload["candidate_id"] = self.candidate_id
            payload["candidate_ref"] = f"candidate:{self.candidate_id}"
        if self.expected_digest is not None:
            payload["expected_digest"] = self.expected_digest
        if self.final_backtest_receipt_id is not None:
            payload["final_backtest_receipt_id"] = self.final_backtest_receipt_id
            payload["final_backtest_receipt_ref"] = f"receipt:{self.final_backtest_receipt_id}"
        if self.base_commit is not None:
            payload["base_commit"] = self.base_commit
        if self.hqa_receipt_ref is not None:
            payload["hqa_receipt_ref"] = self.hqa_receipt_ref
            payload["hqa_receipt_digest"] = self.hqa_receipt_digest
        if self.promotion_id is not None:
            payload.update(
                {
                    "auto_commit": False,
                    "human_git_commit_required": True,
                    "manifest": self.manifest_ref,
                    "patch": self.patch_ref,
                    "promotion_id": self.promotion_id,
                    "reviewed_commit": None,
                    "worktree": self.worktree_ref,
                }
            )
        if note is not None:
            payload["note"] = note
        if self.decided_at is not None:
            payload["decided_at"] = _timestamp(self.decided_at)
        return payload

    def to_operator_dict(
        self,
        *,
        action_state: str | None = None,
        action_error: str | None = None,
    ) -> dict[str, object]:
        """Return the bounded provenance record used by the internal CLI."""

        payload = self.to_public_dict(
            action_state=action_state,
            action_error=action_error,
        )
        payload.update(
            {
                "base_commit": self.base_commit,
                "candidate_id": self.candidate_id,
                "expected_digest": self.expected_digest,
                "registered_expected_status": self.expected_status,
                "created_at": _timestamp(self.created_at),
                "decided_action_digest": self.decided_action_digest,
                "decided_action_kind": self.decided_action_kind,
                "decided_client_action_id": self.decided_client_action_id,
                "expected_task_version": self.expected_task_version,
                "final_backtest_receipt_id": (self.final_backtest_receipt_id),
                "gate1_confirmation_id": self.gate1_confirmation_id,
                "hqa_receipt_digest": self.hqa_receipt_digest,
                "hqa_receipt_ref": self.hqa_receipt_ref,
                "manifest": self.manifest_ref,
                "parent_gate_id": self.parent_gate_id,
                "patch": self.patch_ref,
                "platform_session_id": self.platform_session_id,
                "subject_command_id": (
                    None
                    if self.subject_command_id is None
                    else str(self.subject_command_id)
                ),
                "subject_hermes_run_id": self.subject_hermes_run_id,
                "subject_run_attestation_ref": self.subject_run_attestation_ref,
                "subject_run_attestation_digest": (
                    self.subject_run_attestation_digest
                ),
                "provider_evidence_ref": self.provider_evidence_ref,
                "final_backtest_provider": self.final_backtest_provider,
                "final_backtest_receipt_digest": (
                    self.final_backtest_receipt_digest
                ),
                "final_backtest_config_ref": self.final_backtest_config_ref,
                "final_backtest_config_digest": self.final_backtest_config_digest,
                "final_backtest_summary_ref": self.final_backtest_summary_ref,
                "final_backtest_summary_digest": (
                    self.final_backtest_summary_digest
                ),
                "final_backtest_report_ref": self.final_backtest_report_ref,
                "final_backtest_report_digest": (
                    self.final_backtest_report_digest
                ),
                "promotion_id": self.promotion_id,
                "reviewed_commit": None,
                "source_file_ref": self.source_file_ref,
                "universe": self.universe,
                "updated_at": _timestamp(self.updated_at),
                "workspace_id": self.workspace_id,
                "worktree": self.worktree_ref,
            }
        )
        return payload


@dataclass(frozen=True)
class PaperGateReceipt:
    operation: PaperGateOperation
    gate_id: str
    gate_kind: PaperGateKind
    workspace_id: str
    client_action_id: str
    action_digest: str
    status: PaperGateStatus
    hqa_operation_id: str
    managed_session_ref: str
    occurred_at: datetime
    hqa_receipt_ref: str | None = None
    hqa_receipt_digest: str | None = None
    gate1_confirmation_id: str | None = None
    promotion_id: str | None = None
    worktree: str | None = None
    patch: str | None = None
    manifest: str | None = None
    human_git_commit_required: bool = False
    auto_commit: bool = False
    reason_code: str | None = None
    idempotent_replay: bool = False

    def to_storage_dict(self) -> dict[str, object]:
        return {
            "action_digest": self.action_digest,
            "auto_commit": self.auto_commit,
            "client_action_id": self.client_action_id,
            "gate1_confirmation_id": self.gate1_confirmation_id,
            "gate_id": self.gate_id,
            "gate_kind": self.gate_kind,
            "hqa_operation_id": self.hqa_operation_id,
            "hqa_receipt_digest": self.hqa_receipt_digest,
            "hqa_receipt_ref": self.hqa_receipt_ref,
            "human_git_commit_required": self.human_git_commit_required,
            "idempotent_replay": False,
            "manifest": self.manifest,
            "managed_session_ref": self.managed_session_ref,
            "occurred_at": _timestamp(self.occurred_at),
            "operation": self.operation,
            "patch": self.patch,
            "promotion_id": self.promotion_id,
            "reason_code": self.reason_code,
            "status": self.status,
            "workspace_id": self.workspace_id,
            "worktree": self.worktree,
        }


@dataclass(frozen=True)
class _Claim:
    challenge: PaperGateChallengeRecord
    action_kind: str
    operation: PaperGateOperation
    client_action_id: str
    action_digest: str
    hqa_operation_id: str
    lease_token: UUID


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PaperGateAuthorityValidationError("authority timestamps must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise PaperGateAuthorityUnavailable("stored receipt timestamp is invalid")
    try:
        return datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        ).astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise PaperGateAuthorityUnavailable("stored receipt timestamp is invalid") from exc


def _identifier(value: object, field: str, *, workflow: bool = False) -> str:
    pattern = _WORKFLOW_ID_RE if workflow else _WORKSPACE_ID_RE
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise PaperGateAuthorityValidationError(f"{field} must be a bounded identifier")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise PaperGateAuthorityValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _bounded_text(
    value: object,
    field: str,
    *,
    maximum: int,
    nonempty: bool = True,
) -> str:
    if (
        type(value) is not str
        or (nonempty and not value.strip())
        or len(value.encode("utf-8")) > maximum
        or not value.isprintable()
    ):
        raise PaperGateAuthorityValidationError(f"{field} must be bounded printable text")
    return value.strip()


def _optional_ref(
    value: object,
    field: str,
    pattern: re.Pattern[str],
) -> str | None:
    if value is None:
        return None
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise PaperGateAuthorityValidationError(f"{field} is invalid")
    return value


def _command_id(value: object) -> str:
    if type(value) is not str or _COMMAND_REF_RE.fullmatch(value) is None:
        raise PaperGateAuthorityValidationError("command_id is invalid")
    raw = value.removeprefix("command:")
    try:
        parsed = UUID(raw)
    except ValueError as exc:
        raise PaperGateAuthorityValidationError("command_id is invalid") from exc
    if str(parsed) != raw:
        raise PaperGateAuthorityValidationError("command_id must use canonical lowercase UUID form")
    return str(parsed)


def _record_from_row(row: tuple[object, ...]) -> PaperGateChallengeRecord:
    return PaperGateChallengeRecord(
        gate_id=str(row[0]),
        owner_user_id=UUID(str(row[1])),
        workspace_id=str(row[2]),
        gate_kind=str(row[3]),  # type: ignore[arg-type]
        status=str(row[4]),
        task_ref=str(row[5]),
        expected_task_version=int(row[6]),
        attempt_ref=None if row[7] is None else str(row[7]),
        hqa_gate_ref=str(row[8]),
        platform_session_id=str(row[9]),
        hermes_session_id=str(row[10]),
        command_id=UUID(str(row[11])),
        hermes_run_id=None if row[12] is None else str(row[12]),
        hqa_run_ref=None if row[13] is None else str(row[13]),
        parent_gate_id=None if row[14] is None else str(row[14]),
        source_file_ref=None if row[15] is None else str(row[15]),
        universe=None if row[16] is None else str(row[16]),
        reviewed_source_sha256=(None if row[17] is None else str(row[17]).strip()),
        gate1_confirmation_id=None if row[18] is None else str(row[18]),
        candidate_id=None if row[19] is None else str(row[19]),
        expected_digest=None if row[20] is None else str(row[20]).strip(),
        expected_status=None if row[21] is None else str(row[21]),
        final_backtest_receipt_id=(None if row[22] is None else str(row[22])),
        base_commit=None if row[23] is None else str(row[23]).strip(),
        hqa_receipt_ref=None if row[24] is None else str(row[24]),
        hqa_receipt_digest=(None if row[25] is None else str(row[25]).strip()),
        promotion_id=None if row[26] is None else str(row[26]),
        worktree_ref=None if row[27] is None else str(row[27]),
        patch_ref=None if row[28] is None else str(row[28]),
        manifest_ref=None if row[29] is None else str(row[29]),
        decided_action_kind=None if row[30] is None else str(row[30]),
        decided_client_action_id=None if row[31] is None else str(row[31]),
        decided_action_digest=(None if row[32] is None else str(row[32]).strip()),
        decided_at=row[33],  # type: ignore[arg-type]
        created_at=row[34],  # type: ignore[arg-type]
        updated_at=row[35],  # type: ignore[arg-type]
    )


def _completion_from_row(
    row: tuple[object, ...],
) -> PaperGateCompletionRecord:
    evidence = row[29]
    if not isinstance(evidence, Mapping):
        raise PaperGateAuthorityUnavailable("stored paper completion evidence is invalid")
    return PaperGateCompletionRecord(
        gate_id=str(row[0]),
        owner_user_id=UUID(str(row[1])),
        workspace_id=str(row[2]),
        task_ref=str(row[3]),
        task_version=int(row[4]),
        task_status=str(row[5]),
        task_terminal_outcome=str(row[6]),
        attempt_ref=str(row[7]),
        attempt_status=str(row[8]),
        attempt_terminal_outcome=str(row[9]),
        domain_gate_ref=str(row[10]),
        domain_gate_outcome=str(row[11]),
        hqa_run_ref=str(row[12]),
        provider_evidence_ref=str(row[13]),
        promotion_id=str(row[14]),
        reviewed_commit=str(row[15]).strip(),
        candidate_id=str(row[16]),
        candidate_digest=str(row[17]).strip(),
        final_backtest_receipt_id=str(row[18]),
        base_commit=str(row[19]).strip(),
        attempt_completion_operation_id=str(row[20]),
        attempt_completion_event_id=str(row[21]),
        task_completion_operation_id=str(row[22]),
        task_completion_event_id=str(row[23]),
        workflow_audit_status=str(row[24]),
        workflow_audit_ref=str(row[25]),
        workflow_audit_digest=str(row[26]).strip(),
        hqa_completion_receipt_ref=str(row[27]),
        hqa_completion_receipt_digest=str(row[28]).strip(),
        completion_evidence=dict(evidence),
        created_at=row[30],  # type: ignore[arg-type]
    )


def _canonical_completion_digest(evidence: Mapping[str, object]) -> str:
    try:
        payload = json.dumps(
            dict(evidence),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperGateAuthorityValidationError(
            "completion_evidence must be canonical strict JSON"
        ) from exc
    return hashlib.sha256(payload).hexdigest()


def _gate_public_projection(
    gate: PaperGateChallengeRecord,
    *,
    action_state: str | None = None,
    action_error: str | None = None,
    completion: PaperGateCompletionRecord | None = None,
    operator: bool = False,
) -> dict[str, object]:
    payload = (
        gate.to_operator_dict(
            action_state=action_state,
            action_error=action_error,
        )
        if operator
        else gate.to_public_dict(
            action_state=action_state,
            action_error=action_error,
        )
    )
    if completion is not None:
        payload.update(
            {
                "attempt_status": completion.attempt_status,
                "attempt_terminal_outcome": (completion.attempt_terminal_outcome),
                "domain_gate_outcome": completion.domain_gate_outcome,
                "expected_status": "completed",
                "hqa_completion_receipt_digest": (completion.hqa_completion_receipt_digest),
                "hqa_completion_receipt_ref": (completion.hqa_completion_receipt_ref),
                "human_git_commit_required": False,
                "note": "paper_research_completed_after_human_commit",
                "provider_evidence_ref": completion.provider_evidence_ref,
                "reviewed_commit": completion.reviewed_commit,
                "status": "completed",
                "task_status": completion.task_status,
                "task_terminal_outcome": completion.task_terminal_outcome,
                "task_version": completion.task_version,
                "workflow_audit_digest": completion.workflow_audit_digest,
                "workflow_audit_ref": completion.workflow_audit_ref,
                "workflow_audit_status": completion.workflow_audit_status,
            }
        )
        if operator:
            payload["completion"] = completion.to_operator_dict()
    return payload


def _receipt_from_payload(
    payload: object,
    *,
    replay: bool,
) -> PaperGateReceipt:
    if not isinstance(payload, Mapping):
        raise PaperGateAuthorityUnavailable("stored paper gate receipt is invalid")
    try:
        receipt = PaperGateReceipt(
            operation=str(payload["operation"]),  # type: ignore[arg-type]
            gate_id=str(payload["gate_id"]),
            gate_kind=str(payload["gate_kind"]),  # type: ignore[arg-type]
            workspace_id=str(payload["workspace_id"]),
            client_action_id=str(payload["client_action_id"]),
            action_digest=str(payload["action_digest"]),
            status=str(payload["status"]),  # type: ignore[arg-type]
            hqa_operation_id=str(payload["hqa_operation_id"]),
            managed_session_ref=str(payload["managed_session_ref"]),
            occurred_at=_parse_timestamp(payload["occurred_at"]),
            hqa_receipt_ref=(
                None if payload.get("hqa_receipt_ref") is None else str(payload["hqa_receipt_ref"])
            ),
            hqa_receipt_digest=(
                None
                if payload.get("hqa_receipt_digest") is None
                else str(payload["hqa_receipt_digest"])
            ),
            gate1_confirmation_id=(
                None
                if payload.get("gate1_confirmation_id") is None
                else str(payload["gate1_confirmation_id"])
            ),
            promotion_id=(
                None if payload.get("promotion_id") is None else str(payload["promotion_id"])
            ),
            worktree=(None if payload.get("worktree") is None else str(payload["worktree"])),
            patch=None if payload.get("patch") is None else str(payload["patch"]),
            manifest=(None if payload.get("manifest") is None else str(payload["manifest"])),
            human_git_commit_required=(payload.get("human_git_commit_required") is True),
            auto_commit=payload.get("auto_commit") is True,
            reason_code=(
                None if payload.get("reason_code") is None else str(payload["reason_code"])
            ),
            idempotent_replay=replay,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PaperGateAuthorityUnavailable("stored paper gate receipt is invalid") from exc
    if (
        receipt.operation not in {"confirm-formula", "approve", "promote"}
        or receipt.gate_kind not in {"gate1", "gate2", "gate3"}
        or receipt.status
        not in {
            "pending",
            "confirmed",
            "reviewed",
            "prepared",
            "rejected",
            "outcome_unknown",
        }
        or _MANAGED_SESSION_REF_RE.fullmatch(receipt.managed_session_ref) is None
    ):
        raise PaperGateAuthorityUnavailable("stored paper gate receipt is invalid")
    return receipt


def paper_gate_schema_is_ready_on_connection(
    conn: psycopg.Connection,
) -> bool:
    challenge_table = "agent_v02_paper_gate_challenges"
    action_table = "agent_v02_paper_gate_actions"
    completion_table = "agent_v02_paper_gate_completions"
    meta_table = "agent_v02_paper_gate_meta"
    relations = conn.execute(
        """
        SELECT
            relation.relname,
            relation.relrowsecurity,
            relation.relforcerowsecurity
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relkind = 'r'
          AND relation.relname = ANY(%s)
        """,
        (
            SCHEMA,
            [
                meta_table,
                challenge_table,
                action_table,
                completion_table,
            ],
        ),
    ).fetchall()
    relation_state = {(str(row[0]), bool(row[1]), bool(row[2])) for row in relations}
    if relation_state != {
        (meta_table, False, False),
        (challenge_table, True, True),
        (action_table, True, True),
        (completion_table, True, True),
    }:
        return False
    version = conn.execute(
        f"""
        SELECT schema_version
        FROM {SCHEMA}.agent_v02_paper_gate_meta
        WHERE singleton IS TRUE
        """
    ).fetchone()
    if version != (PAPER_GATE_SCHEMA_VERSION,):
        return False
    expected_columns = {
        challenge_table: tuple(
            name.strip() for name in _CHALLENGE_COLUMNS.split(",") if name.strip()
        ),
        action_table: (
            "owner_user_id",
            "workspace_id",
            "action_kind",
            "client_action_id",
            "action_digest",
            "gate_id",
            "action_state",
            "attempt_count",
            "lease_token",
            "lease_until",
            "hqa_operation_id",
            "hqa_receipt_ref",
            "hqa_receipt_digest",
            "receipt",
            "last_error_code",
            "created_at",
            "updated_at",
        ),
        completion_table: tuple(
            name.strip() for name in _COMPLETION_COLUMNS.split(",") if name.strip()
        ),
    }
    columns = conn.execute(
        """
        SELECT table_name, column_name, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = ANY(%s)
        ORDER BY table_name, ordinal_position
        """,
        (
            SCHEMA,
            [challenge_table, action_table, completion_table],
        ),
    ).fetchall()
    observed_columns = {
        table: tuple(str(row[1]) for row in columns if str(row[0]) == table)
        for table in expected_columns
    }
    if observed_columns != expected_columns:
        return False
    required_binding_columns = conn.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
          AND column_name = ANY(%s)
        ORDER BY column_name
        """,
        (
            SCHEMA,
            challenge_table,
            [
                "command_id",
                "hermes_run_id",
                "hermes_session_id",
                "platform_session_id",
            ],
        ),
    ).fetchall()
    if required_binding_columns != [
        ("command_id", "uuid", "NO"),
        ("hermes_run_id", "text", "NO"),
        ("hermes_session_id", "text", "NO"),
        ("platform_session_id", "text", "NO"),
    ]:
        return False
    session_binding_columns = conn.execute(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = 'hermes_workspace_sessions'
          AND column_name = ANY(%s)
        ORDER BY column_name
        """,
        (
            SCHEMA,
            [
                "kind",
                "owner_user_id",
                "platform_session_id",
                "provision_state",
                "workspace_id",
                "writer",
            ],
        ),
    ).fetchall()
    if session_binding_columns != [
        ("kind", "text", "NO"),
        ("owner_user_id", "uuid", "NO"),
        ("platform_session_id", "text", "NO"),
        ("provision_state", "text", "NO"),
        ("workspace_id", "text", "NO"),
        ("writer", "text", "NO"),
    ]:
        return False

    required_constraints = {
        (
            challenge_table,
            "agent_v02_paper_gate_challenges_expected_task_version_check",
            "c",
        ),
        (
            challenge_table,
            "agent_v02_paper_gate_challenges_gate_kind_check",
            "c",
        ),
        (
            challenge_table,
            "agent_v02_paper_gate_challenges_status_check",
            "c",
        ),
        (
            challenge_table,
            "agent_v02_paper_gate_challenges_pkey",
            "p",
        ),
        (challenge_table, "ck_agent_v02_paper_gate_id", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_workspace", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_task", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_attempt", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_hqa_gate", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_run", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_hqa_run", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_digest_fields", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_source_ref", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_universe", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_expected_status", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_exact_refs", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_artifact_refs", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_hqa_receipt_pair", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_decision_identity", "c"),
        (challenge_table, "ck_agent_v02_paper_gate_kind_shape", "c"),
        (
            action_table,
            "agent_v02_paper_gate_actions_action_digest_check",
            "c",
        ),
        (
            action_table,
            "agent_v02_paper_gate_actions_action_kind_check",
            "c",
        ),
        (
            action_table,
            "agent_v02_paper_gate_actions_action_state_check",
            "c",
        ),
        (
            action_table,
            "agent_v02_paper_gate_actions_attempt_count_check",
            "c",
        ),
        (action_table, "agent_v02_paper_gate_actions_pkey", "p"),
        (action_table, "ck_agent_v02_paper_gate_action_workspace", "c"),
        (action_table, "ck_agent_v02_paper_gate_action_id", "c"),
        (action_table, "ck_agent_v02_paper_gate_hqa_operation", "c"),
        (action_table, "ck_agent_v02_paper_gate_action_receipt_pair", "c"),
        (action_table, "ck_agent_v02_paper_gate_action_error", "c"),
        (action_table, "ck_agent_v02_paper_gate_action_shape", "c"),
        (
            completion_table,
            "agent_v02_paper_gate_completions_pkey",
            "p",
        ),
        (
            completion_table,
            "agent_v02_paper_gate_completions_task_version_check",
            "c",
        ),
        (
            completion_table,
            "agent_v02_paper_gate_completions_task_status_check",
            "c",
        ),
        (
            completion_table,
            "agent_v02_paper_gate_completions_attempt_status_check",
            "c",
        ),
        (
            completion_table,
            "agent_v02_paper_gate_completions_domain_gate_outcome_check",
            "c",
        ),
        (
            completion_table,
            "agent_v02_paper_gate_completions_workflow_audit_status_check",
            "c",
        ),
        (
            completion_table,
            "ck_agent_v02_paper_completion_workspace",
            "c",
        ),
        (
            completion_table,
            "ck_agent_v02_paper_completion_refs",
            "c",
        ),
        (
            completion_table,
            "ck_agent_v02_paper_completion_digests",
            "c",
        ),
        (
            completion_table,
            "ck_agent_v02_paper_completion_events",
            "c",
        ),
    }
    constraints = conn.execute(
        """
        SELECT
            relation.relname,
            constraint_record.conname,
            constraint_record.contype,
            constraint_record.convalidated,
            pg_get_constraintdef(constraint_record.oid, TRUE)
        FROM pg_constraint AS constraint_record
        JOIN pg_class AS relation
          ON relation.oid = constraint_record.conrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = %s
          AND relation.relname = ANY(%s)
        """,
        (SCHEMA, [challenge_table, action_table, completion_table]),
    ).fetchall()
    observed_constraints = {
        (str(row[0]), str(row[1]), str(row[2])) for row in constraints if bool(row[3])
    }
    if not required_constraints.issubset(observed_constraints):
        return False
    normalized_constraint_defs = {
        (str(row[0]), " ".join(str(row[4]).split()).lower()) for row in constraints if bool(row[3])
    }
    required_fk_defs = {
        (
            challenge_table,
            "foreign key (owner_user_id) references quant_system.app_users(id)",
        ),
        (
            challenge_table,
            "foreign key (platform_session_id) references "
            "quant_system.hermes_workspace_sessions(platform_session_id)",
        ),
        (
            challenge_table,
            "foreign key (command_id) references quant_system.hermes_commands(command_id)",
        ),
        (
            challenge_table,
            "foreign key (parent_gate_id) references "
            "quant_system.agent_v02_paper_gate_challenges(gate_id)",
        ),
        (
            action_table,
            "foreign key (owner_user_id) references quant_system.app_users(id)",
        ),
        (
            action_table,
            "foreign key (gate_id) references "
            "quant_system.agent_v02_paper_gate_challenges(gate_id)",
        ),
        (challenge_table, "primary key (gate_id)"),
        (
            action_table,
            "primary key (owner_user_id, workspace_id, action_kind, client_action_id)",
        ),
        (
            completion_table,
            "foreign key (gate_id) references "
            "quant_system.agent_v02_paper_gate_challenges(gate_id)",
        ),
        (
            completion_table,
            "foreign key (owner_user_id) references quant_system.app_users(id)",
        ),
        (completion_table, "primary key (gate_id)"),
    }
    if not required_fk_defs.issubset(normalized_constraint_defs):
        return False

    expected_triggers = {
        "trg_agent_v02_paper_gate_ready_session": (
            challenge_table,
            "require_agent_v02_paper_gate_ready_session",
            "before insert or update",
        ),
        "trg_agent_v02_paper_gate_challenge_update": (
            challenge_table,
            "guard_agent_v02_paper_gate_challenge",
            "before update",
        ),
        "trg_agent_v02_paper_gate_challenge_delete": (
            challenge_table,
            "reject_agent_v02_paper_gate_delete",
            "before delete",
        ),
        "trg_agent_v02_paper_gate_challenge_truncate": (
            challenge_table,
            "reject_agent_v02_paper_gate_delete",
            "before truncate",
        ),
        "trg_agent_v02_paper_gate_action_update": (
            action_table,
            "guard_agent_v02_paper_gate_action",
            "before update",
        ),
        "trg_agent_v02_paper_gate_action_delete": (
            action_table,
            "reject_agent_v02_paper_gate_delete",
            "before delete",
        ),
        "trg_agent_v02_paper_gate_action_truncate": (
            action_table,
            "reject_agent_v02_paper_gate_delete",
            "before truncate",
        ),
        "trg_agent_v02_paper_completion_binding": (
            completion_table,
            "require_agent_v02_paper_completion_binding",
            "before insert",
        ),
        "trg_agent_v02_paper_completion_update": (
            completion_table,
            "reject_agent_v02_paper_gate_delete",
            "before update",
        ),
        "trg_agent_v02_paper_completion_delete": (
            completion_table,
            "reject_agent_v02_paper_gate_delete",
            "before delete",
        ),
        "trg_agent_v02_paper_completion_truncate": (
            completion_table,
            "reject_agent_v02_paper_gate_delete",
            "before truncate",
        ),
    }
    triggers = conn.execute(
        """
        SELECT
            trigger.tgname,
            relation.relname,
            procedure.proname,
            trigger.tgenabled,
            pg_get_triggerdef(trigger.oid, TRUE)
        FROM pg_trigger AS trigger
        JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
        WHERE namespace.nspname = %s
          AND trigger.tgname = ANY(%s)
          AND NOT trigger.tgisinternal
        """,
        (SCHEMA, list(expected_triggers)),
    ).fetchall()
    observed_triggers = {
        str(row[0]): (
            str(row[1]),
            str(row[2]),
            str(row[3]),
            " ".join(str(row[4]).split()).lower(),
        )
        for row in triggers
    }
    if set(observed_triggers) != set(expected_triggers):
        return False
    if any(
        observed_triggers[name][:3] != (table, function, "A")
        or event not in observed_triggers[name][3]
        or f"execute function {SCHEMA}.{function}()" not in observed_triggers[name][3]
        for name, (table, function, event) in expected_triggers.items()
    ):
        return False
    ready_session_function = conn.execute(
        """
        SELECT
            function_record.prosrc,
            function_record.provolatile,
            function_record.prosecdef,
            pg_get_userbyid(function_record.proowner)
        FROM pg_proc AS function_record
        JOIN pg_namespace AS namespace
          ON namespace.oid = function_record.pronamespace
        WHERE namespace.nspname = %s
          AND function_record.proname =
                'require_agent_v02_paper_gate_ready_session'
          AND function_record.pronargs = 0
        """,
        (SCHEMA,),
    ).fetchone()
    if (
        ready_session_function is None
        or hashlib.sha256(
            " ".join(str(ready_session_function[0]).split()).lower().encode("utf-8")
        ).hexdigest()
        != _READY_SESSION_FUNCTION_BODY_SHA256
        or ready_session_function[1:] != ("s", False, "quant_migrator")
    ):
        return False
    completion_function = conn.execute(
        """
        SELECT
            function_record.provolatile,
            function_record.prosecdef,
            pg_get_userbyid(function_record.proowner)
        FROM pg_proc AS function_record
        JOIN pg_namespace AS namespace
          ON namespace.oid = function_record.pronamespace
        WHERE namespace.nspname = %s
          AND function_record.proname =
                'require_agent_v02_paper_completion_binding'
          AND function_record.pronargs = 0
        """,
        (SCHEMA,),
    ).fetchone()
    if completion_function != ("s", False, "quant_migrator"):
        return False

    expected_indexes = {
        "ux_agent_v02_paper_gate_pending_gate1_target": (
            challenge_table,
            (
                "owner_user_id",
                "workspace_id",
                "task_ref",
                "reviewed_source_sha256",
            ),
            "((gate_kind = 'gate1'::text) and (status = 'pending'::text))",
        ),
        "ux_agent_v02_paper_gate_pending_gate2_target": (
            challenge_table,
            (
                "owner_user_id",
                "workspace_id",
                "candidate_id",
                "expected_digest",
            ),
            "((gate_kind = 'gate2'::text) and (status = 'pending'::text))",
        ),
        "ux_agent_v02_paper_gate_pending_gate3_target": (
            challenge_table,
            (
                "owner_user_id",
                "workspace_id",
                "candidate_id",
                "expected_digest",
                "final_backtest_receipt_id",
                "base_commit",
            ),
            "((gate_kind = 'gate3'::text) and (status = 'pending'::text))",
        ),
        "ux_agent_v02_paper_gate_single_action": (
            action_table,
            ("gate_id",),
            "",
        ),
    }
    indexes = conn.execute(
        """
        SELECT
            index_relation.relname,
            table_relation.relname,
            index_record.indisunique,
            ARRAY(
                SELECT attribute.attname
                FROM unnest(index_record.indkey)
                    WITH ORDINALITY AS key(attnum, position)
                JOIN pg_attribute AS attribute
                  ON attribute.attrelid = index_record.indrelid
                 AND attribute.attnum = key.attnum
                ORDER BY key.position
            ),
            COALESCE(
                pg_get_expr(index_record.indpred, index_record.indrelid),
                ''
            )
        FROM pg_index AS index_record
        JOIN pg_class AS index_relation
          ON index_relation.oid = index_record.indexrelid
        JOIN pg_class AS table_relation
          ON table_relation.oid = index_record.indrelid
        JOIN pg_namespace AS namespace
          ON namespace.oid = table_relation.relnamespace
        WHERE namespace.nspname = %s
          AND index_relation.relname = ANY(%s)
        """,
        (SCHEMA, list(expected_indexes)),
    ).fetchall()
    observed_indexes = {
        str(row[0]): (
            str(row[1]),
            tuple(str(item) for item in row[3]),
            " ".join(str(row[4]).split()).lower(),
            bool(row[2]),
        )
        for row in indexes
    }
    if set(observed_indexes) != set(expected_indexes):
        return False
    if any(
        observed_indexes[name] != (table, columns, predicate, True)
        for name, (table, columns, predicate) in expected_indexes.items()
    ):
        return False

    policies = conn.execute(
        """
        SELECT
            tablename,
            policyname,
            permissive,
            roles,
            cmd,
            qual,
            with_check
        FROM pg_policies
        WHERE schemaname = %s
          AND tablename = ANY(%s)
        """,
        (SCHEMA, [challenge_table, action_table, completion_table]),
    ).fetchall()
    root_qual = "(owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid)"
    observed_policies = {
        (str(row[0]), str(row[1])): (
            str(row[2]),
            frozenset(str(role) for role in row[3]),
            str(row[4]),
            " ".join(str(row[5]).split()).lower(),
            " ".join(str(row[6]).split()).lower(),
        )
        for row in policies
    }
    expected_policies = {}
    for table in (challenge_table, action_table, completion_table):
        expected_policies[(table, "v4r_root_scope")] = (
            "PERMISSIVE",
            frozenset({"quant_runtime", "quant_readonly"}),
            "ALL",
            root_qual,
            root_qual,
        )
        expected_policies[(table, "v4r_migrator_all")] = (
            "PERMISSIVE",
            frozenset({"quant_migrator"}),
            "ALL",
            "true",
            "true",
        )
    if observed_policies != expected_policies:
        return False

    privileges = conn.execute(
        """
        WITH roles(role_name) AS (
            VALUES
                ('quant_runtime'),
                ('quant_readonly'),
                ('quant_migrator')
        ),
        tables(table_name) AS (
            VALUES
                (%s),
                (%s),
                (%s),
                (%s)
        )
        SELECT
            role_name,
            table_name,
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'SELECT'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'INSERT'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'UPDATE'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'DELETE'
            ),
            has_table_privilege(
                role_name,
                %s || '.' || table_name,
                'TRUNCATE'
            )
        FROM roles CROSS JOIN tables
        """,
        (
            challenge_table,
            action_table,
            completion_table,
            meta_table,
            SCHEMA,
            SCHEMA,
            SCHEMA,
            SCHEMA,
            SCHEMA,
        ),
    ).fetchall()
    observed_privileges = {
        (str(row[0]), str(row[1])): tuple(bool(value) for value in row[2:]) for row in privileges
    }
    expected_privileges = {
        ("quant_runtime", challenge_table): (True, True, True, False, False),
        ("quant_runtime", action_table): (True, True, True, False, False),
        ("quant_runtime", completion_table): (
            True,
            True,
            False,
            False,
            False,
        ),
        ("quant_runtime", meta_table): (True, False, False, False, False),
        ("quant_readonly", challenge_table): (
            True,
            False,
            False,
            False,
            False,
        ),
        ("quant_readonly", action_table): (
            True,
            False,
            False,
            False,
            False,
        ),
        ("quant_readonly", completion_table): (
            True,
            False,
            False,
            False,
            False,
        ),
        ("quant_readonly", meta_table): (
            True,
            False,
            False,
            False,
            False,
        ),
        ("quant_migrator", challenge_table): (True, True, True, True, True),
        ("quant_migrator", action_table): (True, True, True, True, True),
        ("quant_migrator", completion_table): (
            True,
            True,
            True,
            True,
            True,
        ),
        ("quant_migrator", meta_table): (True, True, True, True, True),
    }
    if observed_privileges != expected_privileges:
        return False
    schema_privileges = conn.execute(
        """
        SELECT
            has_schema_privilege('quant_runtime', %s, 'USAGE'),
            has_schema_privilege('quant_runtime', %s, 'CREATE'),
            has_schema_privilege('quant_readonly', %s, 'USAGE'),
            has_schema_privilege('quant_readonly', %s, 'CREATE'),
            has_schema_privilege('quant_migrator', %s, 'USAGE')
        """,
        (SCHEMA, SCHEMA, SCHEMA, SCHEMA, SCHEMA),
    ).fetchone()
    return schema_privileges == (True, False, True, False, True)


def paper_gate_schema_ready(settings: Settings) -> bool:
    try:
        database = get_database(settings)
        if database is None:
            return False
        with database.connect() as conn:
            return paper_gate_schema_is_ready_on_connection(conn)
    except (DatabaseUnavailable, psycopg.Error):
        return False


def _hqa_operation_id(
    *,
    workspace_id: str,
    action_kind: str,
    client_action_id: str,
    action_digest: str,
) -> str:
    canonical = json.dumps(
        {
            "action_digest": action_digest,
            "action_kind": action_kind,
            "client_action_id": client_action_id,
            "owner_user_id": str(ROOT_USER_ID),
            "workspace_id": workspace_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "pgate-" + hashlib.sha256(canonical).hexdigest()[:32]


def _canonical_hqa_receipt_digest(response: Mapping[str, object]) -> str:
    evidence = {
        key: value
        for key, value in response.items()
        if key not in {"ok", "hqa_receipt_ref", "hqa_receipt_digest"}
    }
    try:
        payload = json.dumps(
            evidence,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperGateAuthorityUnavailable(
            "HQA paper gate receipt is not canonical JSON",
            code="paper_gate_invalid_hqa_receipt",
        ) from exc
    return hashlib.sha256(payload).hexdigest()


class PaperGateAuthority:
    """Durable single-user paper Gate authority."""

    def __init__(
        self,
        settings: Settings,
        *,
        database: Database | None = None,
        lease_seconds: int = _LEASE_SECONDS,
    ) -> None:
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or not 301 <= lease_seconds <= 3600
        ):
            raise ValueError("lease_seconds must be an integer in [301, 3600]")
        self._settings = settings
        self._database_override = database
        self._lease_seconds = lease_seconds

    def _database(self) -> Database:
        database = self._database_override or get_database(self._settings)
        if database is None:
            raise PaperGateAuthorityUnavailable("paper gate database is disabled")
        return database

    @staticmethod
    def _lock(conn: psycopg.Connection, workspace_id: str) -> None:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"paper-gate:{ROOT_USER_ID}:{workspace_id}",),
        )

    @staticmethod
    def _clock(conn: psycopg.Connection) -> datetime:
        row = conn.execute("SELECT clock_timestamp()").fetchone()
        if row is None or not isinstance(row[0], datetime):
            raise PaperGateAuthorityUnavailable("database clock unavailable")
        return row[0].astimezone(UTC)

    @staticmethod
    def _require_schema(conn: psycopg.Connection) -> None:
        if not paper_gate_schema_is_ready_on_connection(conn):
            raise PaperGateAuthorityUnavailable("paper gate schema is not ready")

    def register_challenge(
        self,
        request: RegisterPaperGateChallenge,
    ) -> PaperGateChallengeRecord:
        values = self._validate_registration(request)
        try:
            with self._database().connect() as conn, conn.transaction():
                self._require_schema(conn)
                self._lock(conn, values.workspace_id)
                existing = conn.execute(
                    f"""
                    SELECT {_CHALLENGE_COLUMNS}
                    FROM {SCHEMA}.agent_v02_paper_gate_challenges
                    WHERE gate_id = %s
                    FOR UPDATE
                    """,
                    (values.gate_id,),
                ).fetchone()
                if existing is not None:
                    record = _record_from_row(existing)
                    if self._same_registration(record, values):
                        return record
                    raise PaperGateAuthorityConflict(
                        "gate_id already exists with different exact bindings"
                    )
                self._validate_parent_and_session(conn, values)
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_paper_gate_challenges (
                        gate_id,
                        owner_user_id,
                        workspace_id,
                        gate_kind,
                        status,
                        task_ref,
                        expected_task_version,
                        attempt_ref,
                        hqa_gate_ref,
                        platform_session_id,
                        hermes_session_id,
                        command_id,
                        hermes_run_id,
                        hqa_run_ref,
                        parent_gate_id,
                        source_file_ref,
                        universe,
                        reviewed_source_sha256,
                        gate1_confirmation_id,
                        candidate_id,
                        expected_digest,
                        expected_status,
                        final_backtest_receipt_id,
                        base_commit
                    )
                    VALUES (
                        %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s
                    )
                    RETURNING {_CHALLENGE_COLUMNS}
                    """,
                    (
                        values.gate_id,
                        ROOT_USER_ID,
                        values.workspace_id,
                        values.gate_kind,
                        values.task_ref,
                        values.expected_task_version,
                        values.attempt_ref,
                        values.hqa_gate_ref,
                        values.platform_session_id,
                        values.hermes_session_id,
                        values.command_id,
                        values.hermes_run_id,
                        values.hqa_run_ref,
                        values.parent_gate_id,
                        values.source_file_ref,
                        values.universe,
                        values.reviewed_source_sha256,
                        values.gate1_confirmation_id,
                        values.candidate_id,
                        values.expected_digest,
                        values.expected_status,
                        values.final_backtest_receipt_id,
                        values.base_commit,
                    ),
                ).fetchone()
                if row is None:
                    raise PaperGateAuthorityUnavailable(
                        "paper gate registration did not return a row"
                    )
                return _record_from_row(row)
        except PaperGateAuthorityError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise PaperGateAuthorityConflict(
                "paper gate target already has a pending challenge or action"
            ) from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable("paper gate registration failed") from exc

    def _validate_registration(
        self,
        request: RegisterPaperGateChallenge,
    ) -> RegisterPaperGateChallenge:
        if type(request) is not RegisterPaperGateChallenge:
            raise TypeError("request must be RegisterPaperGateChallenge")
        gate_id = _identifier(request.gate_id, "gate_id", workflow=True)
        if request.gate_kind not in {"gate1", "gate2", "gate3"}:
            raise PaperGateAuthorityValidationError("gate_kind is invalid")
        workspace = _identifier(request.workspace_id, "workspace_id")
        task_ref = _optional_ref(request.task_ref, "task_ref", _TASK_REF_RE)
        assert task_ref is not None
        if (
            isinstance(request.expected_task_version, bool)
            or not isinstance(request.expected_task_version, int)
            or not 1 <= request.expected_task_version <= 2**63 - 1
        ):
            raise PaperGateAuthorityValidationError("expected_task_version must be positive")
        attempt = _optional_ref(
            request.attempt_ref,
            "attempt_ref",
            _ATTEMPT_REF_RE,
        )
        if attempt is None:
            raise PaperGateAuthorityValidationError("attempt_ref is required for every paper Gate")
        hqa_gate_ref = _optional_ref(
            request.hqa_gate_ref,
            "hqa_gate_ref",
            _GATE_REF_RE,
        )
        if hqa_gate_ref is None:
            raise PaperGateAuthorityValidationError("hqa_gate_ref is required for every paper Gate")
        session = _identifier(
            request.platform_session_id,
            "platform_session_id",
        )
        hermes_session_id = _identifier(
            request.hermes_session_id,
            "hermes_session_id",
        )
        command_id = _command_id(request.command_id)
        run_id = _identifier(request.hermes_run_id, "hermes_run_id")
        hqa_run_ref = _optional_ref(
            request.hqa_run_ref,
            "hqa_run_ref",
            _RUN_REF_RE,
        )
        parent = (
            None
            if request.parent_gate_id is None
            else _identifier(
                request.parent_gate_id,
                "parent_gate_id",
                workflow=True,
            )
        )
        source_digest = (
            None
            if request.reviewed_source_sha256 is None
            else _digest(
                request.reviewed_source_sha256,
                "reviewed_source_sha256",
            )
        )
        confirmation = _optional_ref(
            request.gate1_confirmation_id,
            "gate1_confirmation_id",
            _CONFIRMATION_RE,
        )
        candidate = (
            None
            if request.candidate_id is None
            else _identifier(request.candidate_id, "candidate_id", workflow=True)
        )
        candidate_digest = (
            None
            if request.expected_digest is None
            else _digest(request.expected_digest, "expected_digest")
        )
        receipt = _optional_ref(
            request.final_backtest_receipt_id,
            "final_backtest_receipt_id",
            _FINAL_RECEIPT_RE,
        )
        base = request.base_commit
        if base is not None and (type(base) is not str or _COMMIT_RE.fullmatch(base) is None):
            raise PaperGateAuthorityValidationError("base_commit is invalid")
        source_file = request.source_file_ref
        if source_file is not None and (
            type(source_file) is not str
            or not source_file.startswith("/")
            or len(source_file.encode("utf-8")) > 4096
            or not source_file.isprintable()
        ):
            raise PaperGateAuthorityValidationError(
                "source_file_ref must be a bounded absolute path"
            )
        universe = (
            None
            if request.universe is None
            else _bounded_text(request.universe, "universe", maximum=2000)
        )
        if request.gate_kind == "gate1":
            valid = (
                parent is None
                and source_file is not None
                and hqa_run_ref is None
                and universe is not None
                and source_digest is not None
                and confirmation is None
                and candidate is None
                and candidate_digest is None
                and request.expected_status is None
                and receipt is None
                and base is None
            )
        elif request.gate_kind == "gate2":
            valid = (
                parent is not None
                and hqa_run_ref is None
                and source_file is None
                and universe is None
                and source_digest is not None
                and confirmation is not None
                and candidate is not None
                and candidate_digest is not None
                and request.expected_status == "pending"
                and receipt is None
                and base is None
            )
        else:
            valid = (
                parent is not None
                and hqa_run_ref is not None
                and source_file is None
                and universe is None
                and source_digest is not None
                and confirmation is not None
                and candidate is not None
                and candidate_digest is not None
                and request.expected_status is None
                and receipt is not None
                and base is not None
            )
        if not valid:
            raise PaperGateAuthorityValidationError("gate challenge fields do not match gate_kind")
        return replace(
            request,
            gate_id=gate_id,
            workspace_id=workspace,
            task_ref=task_ref,
            attempt_ref=attempt,
            hqa_gate_ref=hqa_gate_ref,
            platform_session_id=session,
            hermes_session_id=hermes_session_id,
            command_id=command_id,
            hermes_run_id=run_id,
            hqa_run_ref=hqa_run_ref,
            parent_gate_id=parent,
            source_file_ref=source_file,
            universe=universe,
            reviewed_source_sha256=source_digest,
            gate1_confirmation_id=confirmation,
            candidate_id=candidate,
            expected_digest=candidate_digest,
            final_backtest_receipt_id=receipt,
            base_commit=base,
        )

    @staticmethod
    def _same_registration(
        record: PaperGateChallengeRecord,
        request: RegisterPaperGateChallenge,
    ) -> bool:
        return (
            record.owner_user_id == ROOT_USER_ID
            and record.workspace_id == request.workspace_id
            and record.gate_kind == request.gate_kind
            and record.task_ref == request.task_ref
            and record.expected_task_version == request.expected_task_version
            and record.attempt_ref == request.attempt_ref
            and record.hqa_gate_ref == request.hqa_gate_ref
            and record.platform_session_id == request.platform_session_id
            and record.hermes_session_id == request.hermes_session_id
            and str(record.command_id) == request.command_id
            and record.hermes_run_id == request.hermes_run_id
            and record.hqa_run_ref == request.hqa_run_ref
            and record.parent_gate_id == request.parent_gate_id
            and record.source_file_ref == request.source_file_ref
            and record.universe == request.universe
            and record.reviewed_source_sha256 == request.reviewed_source_sha256
            and record.gate1_confirmation_id == request.gate1_confirmation_id
            and record.candidate_id == request.candidate_id
            and record.expected_digest == request.expected_digest
            and record.expected_status == request.expected_status
            and record.final_backtest_receipt_id == request.final_backtest_receipt_id
            and record.base_commit == request.base_commit
        )

    @staticmethod
    def _validate_parent_and_session(
        conn: psycopg.Connection,
        request: RegisterPaperGateChallenge,
    ) -> None:
        session = conn.execute(
            f"""
            SELECT 1
            FROM {SCHEMA}.hermes_workspace_sessions AS session
            JOIN {SCHEMA}.hermes_commands AS command
              ON command.command_id = %s
             AND command.owner_user_id = session.owner_user_id
             AND command.platform_session_id =
                    session.platform_session_id
             AND command.candidate_admission_id
                    IS NOT DISTINCT FROM session.candidate_admission_id
             AND (
                    (
                        command.state = 'leased'
                        AND command.dispatch_started_at IS NOT NULL
                        AND command.hermes_session_id IS NULL
                        AND command.hermes_run_id IS NULL
                    )
                    OR (
                        command.state IN ('delivered', 'succeeded')
                        AND command.hermes_session_id =
                                session.hermes_session_id
                        AND command.hermes_run_id = %s
                    )
                 )
            WHERE session.platform_session_id = %s
              AND session.hermes_session_id = %s
              AND session.owner_user_id = %s
              AND session.workspace_id = %s
              AND session.kind = 'web_managed_session'
              AND session.writer = 'web_control_plane'
              AND session.provision_state = 'ready'
            """,
            (
                request.command_id,
                request.hermes_run_id,
                request.platform_session_id,
                request.hermes_session_id,
                ROOT_USER_ID,
                request.workspace_id,
            ),
        ).fetchone()
        if session is None:
            raise PaperGateAuthorityConflict("managed session binding is not ready")
        if request.gate_kind == "gate1":
            return
        parent_row = conn.execute(
            f"""
            SELECT {_CHALLENGE_COLUMNS}
            FROM {SCHEMA}.agent_v02_paper_gate_challenges
            WHERE gate_id = %s
              AND owner_user_id = %s
              AND workspace_id = %s
            FOR UPDATE
            """,
            (
                request.parent_gate_id,
                ROOT_USER_ID,
                request.workspace_id,
            ),
        ).fetchone()
        if parent_row is None:
            raise PaperGateAuthorityConflict("parent Gate is missing")
        parent = _record_from_row(parent_row)
        if request.gate_kind == "gate2":
            valid = (
                parent.gate_kind == "gate1"
                and parent.status == "confirmed"
                and parent.task_ref == request.task_ref
                and request.expected_task_version > parent.expected_task_version
                and parent.attempt_ref == request.attempt_ref
                and parent.hqa_gate_ref == request.hqa_gate_ref
                and parent.platform_session_id == request.platform_session_id
                and parent.hermes_session_id == request.hermes_session_id
                and parent.reviewed_source_sha256 == request.reviewed_source_sha256
                and parent.gate1_confirmation_id == request.gate1_confirmation_id
            )
        else:
            gate1_row = conn.execute(
                f"""
                SELECT {_CHALLENGE_COLUMNS}
                FROM {SCHEMA}.agent_v02_paper_gate_challenges
                WHERE gate_id = %s
                  AND owner_user_id = %s
                  AND workspace_id = %s
                FOR UPDATE
                """,
                (
                    parent.parent_gate_id,
                    ROOT_USER_ID,
                    request.workspace_id,
                ),
            ).fetchone()
            gate1 = None if gate1_row is None else _record_from_row(gate1_row)
            valid = (
                gate1 is not None
                and gate1.gate_kind == "gate1"
                and gate1.status == "confirmed"
                and parent.gate_kind == "gate2"
                and parent.status == "reviewed"
                and parent.task_ref == request.task_ref
                and gate1.task_ref == request.task_ref
                and request.expected_task_version > parent.expected_task_version
                and parent.attempt_ref != request.attempt_ref
                and parent.platform_session_id == request.platform_session_id
                and gate1.platform_session_id == request.platform_session_id
                and parent.hermes_session_id == request.hermes_session_id
                and gate1.hermes_session_id == request.hermes_session_id
                and parent.hermes_run_id != request.hermes_run_id
                and parent.reviewed_source_sha256 == request.reviewed_source_sha256
                and gate1.reviewed_source_sha256 == request.reviewed_source_sha256
                and parent.gate1_confirmation_id == request.gate1_confirmation_id
                and gate1.gate1_confirmation_id == request.gate1_confirmation_id
                and parent.candidate_id == request.candidate_id
                and parent.expected_digest == request.expected_digest
            )
        if not valid:
            raise PaperGateAuthorityConflict("parent Gate exact binding does not match")

    @staticmethod
    def _validated_completion(
        request: RegisterPaperGateCompletion,
    ) -> tuple[str, str, str, str, dict[str, object]]:
        if type(request) is not RegisterPaperGateCompletion:
            raise TypeError("request must be RegisterPaperGateCompletion")
        gate_id = _identifier(request.gate_id, "gate_id", workflow=True)
        workspace_id = _identifier(request.workspace_id, "workspace_id")
        receipt_ref = _bounded_text(
            request.hqa_completion_receipt_ref,
            "hqa_completion_receipt_ref",
            maximum=128,
        )
        if _HQA_COMPLETION_RECEIPT_RE.fullmatch(receipt_ref) is None:
            raise PaperGateAuthorityValidationError("hqa_completion_receipt_ref is invalid")
        receipt_digest = _digest(
            request.hqa_completion_receipt_digest,
            "hqa_completion_receipt_digest",
        )
        if receipt_ref != f"hqa-paper-completion:{receipt_digest[:32]}":
            raise PaperGateAuthorityValidationError(
                "HQA completion receipt ref does not bind its digest"
            )
        if not isinstance(request.completion_evidence, Mapping):
            raise PaperGateAuthorityValidationError("completion_evidence must be an object")
        evidence = dict(request.completion_evidence)
        if (
            any(type(key) is not str for key in evidence)
            or set(evidence) != _COMPLETION_EVIDENCE_FIELDS
        ):
            raise PaperGateAuthorityValidationError(
                "completion_evidence has an invalid exact field set"
            )
        if (
            evidence.get("schema_version") != "agent-v0.2-paper-completion/v1"
            or evidence.get("task_status") != "completed"
            or evidence.get("task_terminal_outcome") != "completed"
            or evidence.get("attempt_status") != "completed"
            or evidence.get("attempt_terminal_outcome") != "completed"
            or evidence.get("domain_gate_outcome") != "passed"
            or evidence.get("workflow_audit_status") != "consistent"
        ):
            raise PaperGateAuthorityValidationError(
                "completion_evidence is not terminal and consistent"
            )
        task_version = evidence.get("task_version")
        if (
            isinstance(task_version, bool)
            or not isinstance(task_version, int)
            or not 1 <= task_version <= 2**63 - 1
        ):
            raise PaperGateAuthorityValidationError("completion task_version must be positive")
        exact_patterns: tuple[
            tuple[str, re.Pattern[str]],
            ...,
        ] = (
            ("task_ref", _TASK_REF_RE),
            ("attempt_ref", _ATTEMPT_REF_RE),
            ("domain_gate_ref", _GATE_REF_RE),
            ("hqa_run_ref", _RUN_REF_RE),
            ("provider_evidence_ref", _PROVIDER_EVIDENCE_RE),
            ("promotion_id", _PROMOTION_RE),
            (
                "final_backtest_receipt_id",
                _FINAL_RECEIPT_RE,
            ),
            (
                "attempt_completion_operation_id",
                _WORKFLOW_OPERATION_RE,
            ),
            (
                "task_completion_operation_id",
                _WORKFLOW_OPERATION_RE,
            ),
            ("attempt_completion_event_id", _WORKFLOW_EVENT_RE),
            ("task_completion_event_id", _WORKFLOW_EVENT_RE),
            ("workflow_audit_ref", _WORKFLOW_AUDIT_REF_RE),
        )
        for field, pattern in exact_patterns:
            value = evidence.get(field)
            if type(value) is not str or pattern.fullmatch(value) is None:
                raise PaperGateAuthorityValidationError(f"completion_evidence {field} is invalid")
        if (
            evidence["attempt_completion_operation_id"] == evidence["task_completion_operation_id"]
            or evidence["attempt_completion_event_id"] == evidence["task_completion_event_id"]
        ):
            raise PaperGateAuthorityValidationError(
                "completion attempt/task events must be distinct"
            )
        candidate_id = evidence.get("candidate_id")
        if type(candidate_id) is not str or _WORKFLOW_ID_RE.fullmatch(candidate_id) is None:
            raise PaperGateAuthorityValidationError("completion_evidence candidate_id is invalid")
        for field in (
            "candidate_digest",
            "workflow_audit_digest",
        ):
            _digest(evidence.get(field), f"completion_evidence {field}")
        if evidence["workflow_audit_ref"] != (
            f"workflow-audit:{evidence['workflow_audit_digest']}"
        ):
            raise PaperGateAuthorityValidationError("workflow audit ref does not bind its digest")
        for field in ("reviewed_commit", "base_commit"):
            value = evidence.get(field)
            if type(value) is not str or _COMMIT_RE.fullmatch(value) is None:
                raise PaperGateAuthorityValidationError(f"completion_evidence {field} is invalid")
        if _canonical_completion_digest(evidence) != receipt_digest:
            raise PaperGateAuthorityValidationError(
                "HQA completion receipt digest does not match exact evidence"
            )
        return (
            gate_id,
            workspace_id,
            receipt_ref,
            receipt_digest,
            evidence,
        )

    def register_completion(
        self,
        request: RegisterPaperGateCompletion,
    ) -> PaperGateCompletionRecord:
        (
            gate_id,
            workspace_id,
            receipt_ref,
            receipt_digest,
            evidence,
        ) = self._validated_completion(request)
        try:
            with self._database().connect() as conn, conn.transaction():
                self._require_schema(conn)
                gate_row = conn.execute(
                    f"""
                    SELECT {_CHALLENGE_COLUMNS}
                    FROM {SCHEMA}.agent_v02_paper_gate_challenges
                    WHERE gate_id = %s
                      AND owner_user_id = %s
                      AND workspace_id = %s
                    FOR UPDATE
                    """,
                    (gate_id, ROOT_USER_ID, workspace_id),
                ).fetchone()
                if gate_row is None:
                    raise PaperGateNotFound()
                gate = _record_from_row(gate_row)
                if (
                    gate.gate_kind != "gate3"
                    or gate.status != "prepared"
                    or gate.task_ref != evidence["task_ref"]
                    or gate.attempt_ref != evidence["attempt_ref"]
                    or gate.hqa_gate_ref != evidence["domain_gate_ref"]
                    or gate.hqa_run_ref != evidence["hqa_run_ref"]
                    or gate.promotion_id != evidence["promotion_id"]
                    or gate.candidate_id != evidence["candidate_id"]
                    or gate.expected_digest != evidence["candidate_digest"]
                    or gate.final_backtest_receipt_id != evidence["final_backtest_receipt_id"]
                    or gate.base_commit != evidence["base_commit"]
                    or evidence["task_version"] != gate.expected_task_version + 4
                ):
                    raise PaperGateAuthorityConflict(
                        "terminal HQA completion does not match exact Gate 3"
                    )
                row = conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_paper_gate_completions (
                        gate_id,
                        owner_user_id,
                        workspace_id,
                        task_ref,
                        task_version,
                        task_status,
                        task_terminal_outcome,
                        attempt_ref,
                        attempt_status,
                        attempt_terminal_outcome,
                        domain_gate_ref,
                        domain_gate_outcome,
                        hqa_run_ref,
                        provider_evidence_ref,
                        promotion_id,
                        reviewed_commit,
                        candidate_id,
                        candidate_digest,
                        final_backtest_receipt_id,
                        base_commit,
                        attempt_completion_operation_id,
                        attempt_completion_event_id,
                        task_completion_operation_id,
                        task_completion_event_id,
                        workflow_audit_status,
                        workflow_audit_ref,
                        workflow_audit_digest,
                        hqa_completion_receipt_ref,
                        hqa_completion_receipt_digest,
                        completion_evidence
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (gate_id) DO NOTHING
                    RETURNING {_COMPLETION_COLUMNS}
                    """,
                    (
                        gate_id,
                        ROOT_USER_ID,
                        workspace_id,
                        evidence["task_ref"],
                        evidence["task_version"],
                        evidence["task_status"],
                        evidence["task_terminal_outcome"],
                        evidence["attempt_ref"],
                        evidence["attempt_status"],
                        evidence["attempt_terminal_outcome"],
                        evidence["domain_gate_ref"],
                        evidence["domain_gate_outcome"],
                        evidence["hqa_run_ref"],
                        evidence["provider_evidence_ref"],
                        evidence["promotion_id"],
                        evidence["reviewed_commit"],
                        evidence["candidate_id"],
                        evidence["candidate_digest"],
                        evidence["final_backtest_receipt_id"],
                        evidence["base_commit"],
                        evidence["attempt_completion_operation_id"],
                        evidence["attempt_completion_event_id"],
                        evidence["task_completion_operation_id"],
                        evidence["task_completion_event_id"],
                        evidence["workflow_audit_status"],
                        evidence["workflow_audit_ref"],
                        evidence["workflow_audit_digest"],
                        receipt_ref,
                        receipt_digest,
                        Jsonb(evidence),
                    ),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        f"""
                        SELECT {_COMPLETION_COLUMNS}
                        FROM {SCHEMA}.agent_v02_paper_gate_completions
                        WHERE gate_id = %s
                          AND owner_user_id = %s
                          AND workspace_id = %s
                        """,
                        (gate_id, ROOT_USER_ID, workspace_id),
                    ).fetchone()
                if row is None:
                    raise PaperGateAuthorityUnavailable(
                        "paper completion registration outcome is unknown"
                    )
                completion = _completion_from_row(row)
                if (
                    completion.hqa_completion_receipt_ref != receipt_ref
                    or completion.hqa_completion_receipt_digest != receipt_digest
                    or dict(completion.completion_evidence) != evidence
                ):
                    raise PaperGateAuthorityConflict(
                        "paper completion was already registered differently"
                    )
                return completion
        except PaperGateAuthorityError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise PaperGateAuthorityConflict(
                "HQA completion receipt is already bound to another Gate"
            ) from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable("paper completion registration failed") from exc

    def list_observed(
        self,
        workspace_id: str,
    ) -> list[dict[str, object]]:
        workspace = _identifier(workspace_id, "workspace_id")
        try:
            with self._database().connect() as conn:
                self._require_schema(conn)
                rows = conn.execute(
                    f"""
                    SELECT
                        {_QUALIFIED_CHALLENGE_COLUMNS},
                        action.action_state,
                        action.last_error_code
                    FROM {SCHEMA}.agent_v02_paper_gate_challenges AS challenge
                    LEFT JOIN {SCHEMA}.agent_v02_paper_gate_actions AS action
                      ON action.gate_id = challenge.gate_id
                    WHERE challenge.owner_user_id = %s
                      AND challenge.workspace_id = %s
                    ORDER BY challenge.created_at, challenge.gate_id
                    """,
                    (ROOT_USER_ID, workspace),
                ).fetchall()
                completion_rows = conn.execute(
                    f"""
                    SELECT {_COMPLETION_COLUMNS}
                    FROM {SCHEMA}.agent_v02_paper_gate_completions
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                    """,
                    (ROOT_USER_ID, workspace),
                ).fetchall()
            completions = {
                completion.gate_id: completion
                for completion in (_completion_from_row(row) for row in completion_rows)
            }
            return [
                _gate_public_projection(
                    _record_from_row(tuple(row[:36])),
                    action_state=None if row[36] is None else str(row[36]),
                    action_error=None if row[37] is None else str(row[37]),
                    completion=completions.get(str(row[0])),
                )
                for row in rows
            ]
        except PaperGateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable("paper gate observation failed") from exc

    def get_operator_record(self, gate_id: str) -> dict[str, object]:
        """Read one exact durable Gate record for the trusted local CLI."""

        exact_gate_id = _identifier(gate_id, "gate_id", workflow=True)
        try:
            with self._database().connect() as conn:
                self._require_schema(conn)
                row = conn.execute(
                    f"""
                    SELECT
                        {_QUALIFIED_CHALLENGE_COLUMNS},
                        action.action_state,
                        action.last_error_code
                    FROM {SCHEMA}.agent_v02_paper_gate_challenges AS challenge
                    LEFT JOIN {SCHEMA}.agent_v02_paper_gate_actions AS action
                      ON action.gate_id = challenge.gate_id
                    WHERE challenge.owner_user_id = %s
                      AND challenge.gate_id = %s
                    """,
                    (ROOT_USER_ID, exact_gate_id),
                ).fetchone()
                completion_row = conn.execute(
                    f"""
                    SELECT {_COMPLETION_COLUMNS}
                    FROM {SCHEMA}.agent_v02_paper_gate_completions
                    WHERE owner_user_id = %s
                      AND gate_id = %s
                    """,
                    (ROOT_USER_ID, exact_gate_id),
                ).fetchone()
            if row is None:
                raise PaperGateNotFound()
            return _gate_public_projection(
                _record_from_row(tuple(row[:36])),
                action_state=None if row[36] is None else str(row[36]),
                action_error=None if row[37] is None else str(row[37]),
                completion=(
                    None if completion_row is None else _completion_from_row(completion_row)
                ),
                operator=True,
            )
        except PaperGateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable("paper gate observation failed") from exc

    def execute_action(
        self,
        action: ConfirmFormulaSource | ReviewCandidateCAS | PreparePromotionReview,
        *,
        action_digest: str,
        port: PaperGateExecutionPort,
    ) -> PaperGateReceipt:
        if type(action) not in _ACTION_KIND:
            raise TypeError("unsupported paper gate action")
        exact_digest = canonical_action_digest(action)
        if _digest(action_digest, "action_digest") != exact_digest:
            raise PaperGateAuthorityValidationError(
                "action_digest does not match the canonical action"
            )
        claim_or_receipt = self._claim(action, action_digest=exact_digest)
        if isinstance(claim_or_receipt, PaperGateReceipt):
            return claim_or_receipt
        claim = claim_or_receipt
        request = self._port_request(action, claim)
        try:
            response = port.execute(claim.operation, request)
            self._validate_port_response(claim, response, action=action)
        except PaperGatePortError as exc:
            if exc.retryable:
                self._mark_retryable(claim, exc.code)
                raise PaperGateAuthorityUnavailable(
                    "paper gate HQA port is retryable",
                    code=exc.code,
                ) from exc
            status: PaperGateStatus = (
                "outcome_unknown" if exc.code == "paper_gate_outcome_unknown" else "rejected"
            )
            return self._finish_error(claim, status=status, reason_code=exc.code)
        except PaperGateAuthorityError:
            return self._finish_error(
                claim,
                status="outcome_unknown",
                reason_code="paper_gate_invalid_hqa_receipt",
            )
        try:
            return self._finish_success(claim, response)
        except Exception:
            # HQA has already accepted/mutated by this point. A database,
            # lease, or CAS failure is therefore an unknown outcome, never a
            # normal conflict that may encourage a differently keyed retry.
            # This deliberately catches programming/runtime exceptions too:
            # once the external success was observed, safety takes precedence
            # over surfacing an ordinary internal error.
            try:
                return self._finish_error(
                    claim,
                    status="outcome_unknown",
                    reason_code="paper_gate_finalization_outcome_unknown",
                )
            except Exception as recovery_exc:
                raise PaperGateAuthorityUnavailable(
                    "paper gate post-mutation finalization is unknown",
                    code="paper_gate_finalization_outcome_unknown",
                ) from recovery_exc

    def _claim(
        self,
        action: ConfirmFormulaSource | ReviewCandidateCAS | PreparePromotionReview,
        *,
        action_digest: str,
    ) -> _Claim | PaperGateReceipt:
        action_type = type(action)
        action_kind = _ACTION_KIND[action_type]
        operation = _OPERATION[action_type]
        workspace = action.workspace.workspace_id
        action_id = action.client_action_id
        hqa_operation = _hqa_operation_id(
            workspace_id=workspace,
            action_kind=action_kind,
            client_action_id=action_id,
            action_digest=action_digest,
        )
        lease_token = uuid4()
        try:
            with self._database().connect() as conn, conn.transaction():
                self._require_schema(conn)
                self._lock(conn, workspace)
                clock = self._clock(conn)
                existing = conn.execute(
                    f"""
                    SELECT
                        action_digest,
                        gate_id,
                        action_state,
                        lease_until,
                        hqa_operation_id,
                        receipt
                    FROM {SCHEMA}.agent_v02_paper_gate_actions
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND action_kind = %s
                      AND client_action_id = %s
                    FOR UPDATE
                    """,
                    (
                        ROOT_USER_ID,
                        workspace,
                        action_kind,
                        action_id,
                    ),
                ).fetchone()
                if existing is not None:
                    if str(existing[0]).strip() != action_digest:
                        raise PaperGateAuthorityConflict(
                            "client_action_id was reused with a different digest"
                        )
                    state = str(existing[2])
                    if state in {"succeeded", "outcome_unknown", "failed"}:
                        challenge = self._challenge_by_id(
                            conn,
                            str(existing[1]),
                            for_update=True,
                        )
                        receipt = _receipt_from_payload(
                            existing[5],
                            replay=True,
                        )
                        if (
                            receipt.gate_id != challenge.gate_id
                            or receipt.gate_kind != challenge.gate_kind
                            or receipt.workspace_id != workspace
                            or receipt.client_action_id != action_id
                            or receipt.action_digest != action_digest
                            or receipt.hqa_operation_id != str(existing[4])
                            or receipt.managed_session_ref
                            != f"session:{challenge.platform_session_id}"
                        ):
                            raise PaperGateAuthorityUnavailable(
                                "stored paper gate receipt substituted durable identity"
                            )
                        return receipt
                    if state == "executing":
                        lease_until = existing[3]
                        if isinstance(lease_until, datetime) and lease_until > clock:
                            raise PaperGateAuthorityUnavailable(
                                "paper gate action is still executing",
                                code="paper_gate_action_in_progress",
                            )
                        challenge = self._challenge_by_id(
                            conn,
                            str(existing[1]),
                            for_update=True,
                        )
                        receipt = PaperGateReceipt(
                            operation=operation,
                            gate_id=challenge.gate_id,
                            gate_kind=challenge.gate_kind,
                            workspace_id=workspace,
                            client_action_id=action_id,
                            action_digest=action_digest,
                            status="outcome_unknown",
                            hqa_operation_id=str(existing[4]),
                            managed_session_ref=(f"session:{challenge.platform_session_id}"),
                            occurred_at=clock,
                            reason_code=("paper_gate_interrupted_outcome_unknown"),
                        )
                        challenge_updated = conn.execute(
                            f"""
                            UPDATE {SCHEMA}.agent_v02_paper_gate_challenges
                            SET status = 'outcome_unknown',
                                decided_action_kind = %s,
                                decided_client_action_id = %s,
                                decided_action_digest = %s,
                                decided_at = %s
                            WHERE gate_id = %s
                              AND owner_user_id = %s
                              AND workspace_id = %s
                              AND status = 'pending'
                            RETURNING gate_id
                            """,
                            (
                                action_kind,
                                action_id,
                                action_digest,
                                clock,
                                challenge.gate_id,
                                ROOT_USER_ID,
                                workspace,
                            ),
                        ).fetchone()
                        if challenge_updated is None:
                            raise PaperGateAuthorityConflict(
                                "interrupted paper Gate is no longer pending"
                            )
                        action_updated = conn.execute(
                            f"""
                            UPDATE {SCHEMA}.agent_v02_paper_gate_actions
                            SET action_state = 'outcome_unknown',
                                lease_token = NULL,
                                lease_until = NULL,
                                receipt = %s,
                                last_error_code = %s
                            WHERE owner_user_id = %s
                              AND workspace_id = %s
                              AND action_kind = %s
                              AND client_action_id = %s
                              AND action_state = 'executing'
                            RETURNING gate_id
                            """,
                            (
                                Jsonb(receipt.to_storage_dict()),
                                receipt.reason_code,
                                ROOT_USER_ID,
                                workspace,
                                action_kind,
                                action_id,
                            ),
                        ).fetchone()
                        if action_updated is None:
                            raise PaperGateAuthorityConflict(
                                "interrupted paper Gate action CAS failed"
                            )
                        return receipt
                    if state != "retryable":
                        raise PaperGateAuthorityUnavailable("paper gate action state is invalid")
                    challenge = self._challenge_by_id(
                        conn,
                        str(existing[1]),
                        for_update=True,
                    )
                    updated = conn.execute(
                        f"""
                        UPDATE {SCHEMA}.agent_v02_paper_gate_actions
                        SET action_state = 'executing',
                            attempt_count = attempt_count + 1,
                            lease_token = %s,
                            lease_until = %s,
                            last_error_code = NULL
                        WHERE owner_user_id = %s
                          AND workspace_id = %s
                          AND action_kind = %s
                          AND client_action_id = %s
                          AND action_state = 'retryable'
                        RETURNING gate_id
                        """,
                        (
                            lease_token,
                            clock + timedelta(seconds=self._lease_seconds),
                            ROOT_USER_ID,
                            workspace,
                            action_kind,
                            action_id,
                        ),
                    ).fetchone()
                    if updated is None:
                        raise PaperGateAuthorityConflict("paper gate retry CAS failed")
                    return _Claim(
                        challenge=challenge,
                        action_kind=action_kind,
                        operation=operation,
                        client_action_id=action_id,
                        action_digest=action_digest,
                        hqa_operation_id=hqa_operation,
                        lease_token=lease_token,
                    )
                challenge = self._find_target(conn, action)
                conn.execute(
                    f"""
                    INSERT INTO {SCHEMA}.agent_v02_paper_gate_actions (
                        owner_user_id,
                        workspace_id,
                        action_kind,
                        client_action_id,
                        action_digest,
                        gate_id,
                        action_state,
                        attempt_count,
                        lease_token,
                        lease_until,
                        hqa_operation_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, 'executing', 1, %s, %s, %s
                    )
                    """,
                    (
                        ROOT_USER_ID,
                        workspace,
                        action_kind,
                        action_id,
                        action_digest,
                        challenge.gate_id,
                        lease_token,
                        clock + timedelta(seconds=self._lease_seconds),
                        hqa_operation,
                    ),
                )
                return _Claim(
                    challenge=challenge,
                    action_kind=action_kind,
                    operation=operation,
                    client_action_id=action_id,
                    action_digest=action_digest,
                    hqa_operation_id=hqa_operation,
                    lease_token=lease_token,
                )
        except PaperGateAuthorityError:
            raise
        except psycopg.errors.UniqueViolation as exc:
            raise PaperGateAuthorityConflict("paper gate already has a different action") from exc
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable("paper gate claim failed") from exc

    @staticmethod
    def _challenge_by_id(
        conn: psycopg.Connection,
        gate_id: str,
        *,
        for_update: bool,
    ) -> PaperGateChallengeRecord:
        row = conn.execute(
            f"""
            SELECT {_CHALLENGE_COLUMNS}
            FROM {SCHEMA}.agent_v02_paper_gate_challenges
            WHERE gate_id = %s
              AND owner_user_id = %s
            {"FOR UPDATE" if for_update else ""}
            """,
            (gate_id, ROOT_USER_ID),
        ).fetchone()
        if row is None:
            raise PaperGateAuthorityConflict("paper gate challenge is missing")
        return _record_from_row(row)

    @staticmethod
    def _find_target(
        conn: psycopg.Connection,
        action: ConfirmFormulaSource | ReviewCandidateCAS | PreparePromotionReview,
    ) -> PaperGateChallengeRecord:
        workspace = action.workspace.workspace_id
        if type(action) is ConfirmFormulaSource:
            clause = """
                gate_kind = 'gate1'
                AND task_ref = %s
                AND reviewed_source_sha256 = %s
            """
            params: tuple[object, ...] = (
                action.task_ref,
                action.reviewed_source_sha256,
            )
        elif type(action) is ReviewCandidateCAS:
            clause = """
                gate_kind = 'gate2'
                AND candidate_id = %s
                AND expected_digest = %s
                AND expected_status = %s
            """
            params = (
                action.candidate_ref.removeprefix("candidate:"),
                action.expected_digest,
                action.expected_status,
            )
        else:
            clause = """
                gate_kind = 'gate3'
                AND candidate_id = %s
                AND expected_digest = %s
                AND final_backtest_receipt_id = %s
                AND base_commit = %s
            """
            params = (
                action.candidate_ref.removeprefix("candidate:"),
                action.expected_digest,
                action.final_backtest_receipt_ref.removeprefix("receipt:"),
                action.base_commit,
            )
        rows = conn.execute(
            f"""
            SELECT {_CHALLENGE_COLUMNS}
            FROM {SCHEMA}.agent_v02_paper_gate_challenges
            WHERE owner_user_id = %s
              AND workspace_id = %s
              AND status = 'pending'
              AND {clause}
            FOR UPDATE
            """,
            (ROOT_USER_ID, workspace, *params),
        ).fetchall()
        if len(rows) != 1:
            raise PaperGateAuthorityConflict("exactly one pending paper gate target is required")
        return _record_from_row(rows[0])

    @staticmethod
    def _port_request(
        action: ConfirmFormulaSource | ReviewCandidateCAS | PreparePromotionReview,
        claim: _Claim,
    ) -> dict[str, object]:
        challenge = claim.challenge
        common = {
            "managed_session_ref": (f"session:{challenge.platform_session_id}"),
            "operation_id": claim.hqa_operation_id,
        }
        if type(action) is ConfirmFormulaSource:
            return {
                **common,
                "confirmation_note": action.confirmation_note,
                "expected_task_version": challenge.expected_task_version,
                "gate_ref": challenge.hqa_gate_ref,
                "reviewed_source_digest": action.reviewed_source_sha256,
                "source_file": challenge.source_file_ref,
                "task_ref": challenge.task_ref,
                "universe": challenge.universe,
            }
        if type(action) is ReviewCandidateCAS:
            return {
                **common,
                "candidate_id": challenge.candidate_id,
                "expected_digest": action.expected_digest,
                "expected_status": action.expected_status,
                "expected_task_version": challenge.expected_task_version,
                "gate1_confirmation_id": challenge.gate1_confirmation_id,
                "gate_ref": challenge.hqa_gate_ref,
                "note": action.note,
                "reviewed_source_digest": (challenge.reviewed_source_sha256),
                "task_ref": challenge.task_ref,
            }
        return {
            **common,
            "attempt_ref": challenge.attempt_ref,
            "base_commit": action.base_commit,
            "candidate_id": challenge.candidate_id,
            "expected_task_version": challenge.expected_task_version,
            "expected_digest": action.expected_digest,
            "final_backtest_receipt_id": (
                action.final_backtest_receipt_ref.removeprefix("receipt:")
            ),
            "gate_ref": challenge.hqa_gate_ref,
            "run_ref": challenge.hqa_run_ref,
            "task_ref": challenge.task_ref,
        }

    @staticmethod
    def _validate_port_response(
        claim: _Claim,
        response: Mapping[str, object],
        *,
        action: ConfirmFormulaSource | ReviewCandidateCAS | PreparePromotionReview,
    ) -> None:
        challenge = claim.challenge
        receipt_ref = response.get("hqa_receipt_ref")
        receipt_digest = response.get("hqa_receipt_digest")
        valid = (
            response.get("ok") is True
            and response.get("operation_id") == claim.hqa_operation_id
            and response.get("managed_session_ref") == f"session:{challenge.platform_session_id}"
            and receipt_ref == f"hqa-paper-gate:{claim.hqa_operation_id}"
            and type(receipt_ref) is str
            and _HQA_RECEIPT_RE.fullmatch(receipt_ref) is not None
            and type(receipt_digest) is str
            and _DIGEST_RE.fullmatch(receipt_digest) is not None
            and receipt_digest == _canonical_hqa_receipt_digest(response)
        )
        if claim.operation == "confirm-formula":
            valid = valid and (
                response.get("task_ref") == challenge.task_ref
                and response.get("attempt_ref") == challenge.attempt_ref
                and response.get("task_version") == challenge.expected_task_version + 1
                and response.get("gate_ref") == challenge.hqa_gate_ref
                and response.get("reviewed_source_digest") == challenge.reviewed_source_sha256
                and type(response.get("gate1_confirmation_id")) is str
                and _CONFIRMATION_RE.fullmatch(str(response["gate1_confirmation_id"])) is not None
            )
        elif claim.operation == "approve":
            assert type(action) is ReviewCandidateCAS
            valid = valid and (
                response.get("task_ref") == challenge.task_ref
                and response.get("attempt_ref") == challenge.attempt_ref
                and response.get("task_version") == challenge.expected_task_version + 1
                and response.get("gate_ref") == challenge.hqa_gate_ref
                and response.get("gate1_confirmation_id") == challenge.gate1_confirmation_id
                and response.get("reviewed_source_digest") == challenge.reviewed_source_sha256
                and response.get("candidate_id") == challenge.candidate_id
                and response.get("candidate_digest") == challenge.expected_digest
                and response.get("decision") == "approve"
                and response.get("registration") == "manual_required"
                and response.get("review_note_digest")
                == hashlib.sha256(action.note.encode("utf-8")).hexdigest()
            )
        else:
            gate_resolution_event_id = response.get("workflow_gate_resolution_event_id")
            gate3_event_id = response.get("workflow_gate3_event_id")
            valid = valid and (
                response.get("task_ref") == challenge.task_ref
                and response.get("attempt_ref") == challenge.attempt_ref
                and response.get("task_version") == challenge.expected_task_version + 2
                and type(gate_resolution_event_id) is str
                and _WORKFLOW_EVENT_RE.fullmatch(gate_resolution_event_id) is not None
                and type(gate3_event_id) is str
                and _WORKFLOW_EVENT_RE.fullmatch(gate3_event_id) is not None
                and gate_resolution_event_id != gate3_event_id
                and response.get("run_ref") == challenge.hqa_run_ref
                and response.get("gate_ref") == challenge.hqa_gate_ref
                and response.get("candidate_id") == challenge.candidate_id
                and response.get("candidate_digest") == challenge.expected_digest
                and response.get("final_backtest_receipt_id") == challenge.final_backtest_receipt_id
                and response.get("base_commit") == challenge.base_commit
                and type(response.get("promotion_id")) is str
                and response.get("promotion_status") == "awaiting_human_commit"
                and response.get("human_git_commit_required") is True
                and response.get("auto_commit") is False
                and all(
                    type(response.get(name)) is str and bool(response[name])
                    for name in ("worktree", "patch", "manifest")
                )
            )
        if not valid:
            raise PaperGateAuthorityUnavailable(
                "HQA paper gate receipt substituted exact bindings",
                code="paper_gate_invalid_hqa_receipt",
            )

    def _finish_success(
        self,
        claim: _Claim,
        response: Mapping[str, object],
    ) -> PaperGateReceipt:
        status: PaperGateStatus = {
            "confirm-formula": "confirmed",
            "approve": "reviewed",
            "promote": "prepared",
        }[claim.operation]  # type: ignore[assignment]
        try:
            with self._database().connect() as conn, conn.transaction():
                self._require_schema(conn)
                self._lock(conn, claim.challenge.workspace_id)
                clock = self._clock(conn)
                action_row = conn.execute(
                    f"""
                    SELECT action_state, lease_token
                    FROM {SCHEMA}.agent_v02_paper_gate_actions
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND action_kind = %s
                      AND client_action_id = %s
                    FOR UPDATE
                    """,
                    (
                        ROOT_USER_ID,
                        claim.challenge.workspace_id,
                        claim.action_kind,
                        claim.client_action_id,
                    ),
                ).fetchone()
                if action_row != ("executing", claim.lease_token):
                    raise PaperGateAuthorityConflict("paper gate finalization lease was lost")
                challenge = self._challenge_by_id(
                    conn,
                    claim.challenge.gate_id,
                    for_update=True,
                )
                if challenge.status != "pending":
                    raise PaperGateAuthorityConflict("paper gate challenge is no longer pending")
                receipt = PaperGateReceipt(
                    operation=claim.operation,
                    gate_id=challenge.gate_id,
                    gate_kind=challenge.gate_kind,
                    workspace_id=challenge.workspace_id,
                    client_action_id=claim.client_action_id,
                    action_digest=claim.action_digest,
                    status=status,
                    hqa_operation_id=claim.hqa_operation_id,
                    managed_session_ref=(f"session:{challenge.platform_session_id}"),
                    occurred_at=clock,
                    hqa_receipt_ref=str(response["hqa_receipt_ref"]),
                    hqa_receipt_digest=str(response["hqa_receipt_digest"]),
                    gate1_confirmation_id=(
                        str(response["gate1_confirmation_id"])
                        if claim.operation == "confirm-formula"
                        else challenge.gate1_confirmation_id
                    ),
                    promotion_id=(
                        str(response["promotion_id"]) if claim.operation == "promote" else None
                    ),
                    worktree=(str(response["worktree"]) if claim.operation == "promote" else None),
                    patch=(str(response["patch"]) if claim.operation == "promote" else None),
                    manifest=(str(response["manifest"]) if claim.operation == "promote" else None),
                    human_git_commit_required=(claim.operation == "promote"),
                    auto_commit=False,
                )
                updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_paper_gate_challenges
                    SET status = %s,
                        gate1_confirmation_id = %s,
                        hqa_receipt_ref = %s,
                        hqa_receipt_digest = %s,
                        promotion_id = %s,
                        worktree_ref = %s,
                        patch_ref = %s,
                        manifest_ref = %s,
                        decided_action_kind = %s,
                        decided_client_action_id = %s,
                        decided_action_digest = %s,
                        decided_at = %s
                    WHERE gate_id = %s
                      AND owner_user_id = %s
                      AND workspace_id = %s
                      AND status = 'pending'
                    RETURNING gate_id
                    """,
                    (
                        status,
                        receipt.gate1_confirmation_id,
                        receipt.hqa_receipt_ref,
                        receipt.hqa_receipt_digest,
                        receipt.promotion_id,
                        receipt.worktree,
                        receipt.patch,
                        receipt.manifest,
                        claim.action_kind,
                        claim.client_action_id,
                        claim.action_digest,
                        clock,
                        challenge.gate_id,
                        ROOT_USER_ID,
                        challenge.workspace_id,
                    ),
                ).fetchone()
                if updated is None:
                    raise PaperGateAuthorityConflict("paper gate challenge finalization CAS failed")
                action_updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_paper_gate_actions
                    SET action_state = 'succeeded',
                        lease_token = NULL,
                        lease_until = NULL,
                        hqa_receipt_ref = %s,
                        hqa_receipt_digest = %s,
                        receipt = %s,
                        last_error_code = NULL
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND action_kind = %s
                      AND client_action_id = %s
                      AND action_state = 'executing'
                      AND lease_token = %s
                    RETURNING gate_id
                    """,
                    (
                        receipt.hqa_receipt_ref,
                        receipt.hqa_receipt_digest,
                        Jsonb(receipt.to_storage_dict()),
                        ROOT_USER_ID,
                        challenge.workspace_id,
                        claim.action_kind,
                        claim.client_action_id,
                        claim.lease_token,
                    ),
                ).fetchone()
                if action_updated is None:
                    raise PaperGateAuthorityConflict("paper gate action finalization CAS failed")
                return receipt
        except PaperGateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable(
                "paper gate success finalization failed",
                code="paper_gate_finalization_outcome_unknown",
            ) from exc

    def _finish_error(
        self,
        claim: _Claim,
        *,
        status: Literal["rejected", "outcome_unknown"],
        reason_code: str,
    ) -> PaperGateReceipt:
        action_state = "failed" if status == "rejected" else "outcome_unknown"
        try:
            with self._database().connect() as conn, conn.transaction():
                self._require_schema(conn)
                self._lock(conn, claim.challenge.workspace_id)
                clock = self._clock(conn)
                receipt = PaperGateReceipt(
                    operation=claim.operation,
                    gate_id=claim.challenge.gate_id,
                    gate_kind=claim.challenge.gate_kind,
                    workspace_id=claim.challenge.workspace_id,
                    client_action_id=claim.client_action_id,
                    action_digest=claim.action_digest,
                    status=status,
                    hqa_operation_id=claim.hqa_operation_id,
                    managed_session_ref=(f"session:{claim.challenge.platform_session_id}"),
                    occurred_at=clock,
                    reason_code=reason_code,
                )
                challenge_updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_paper_gate_challenges
                    SET status = %s,
                        decided_action_kind = %s,
                        decided_client_action_id = %s,
                        decided_action_digest = %s,
                        decided_at = %s
                    WHERE gate_id = %s
                      AND owner_user_id = %s
                      AND workspace_id = %s
                      AND status = 'pending'
                    RETURNING gate_id
                    """,
                    (
                        status,
                        claim.action_kind,
                        claim.client_action_id,
                        claim.action_digest,
                        clock,
                        claim.challenge.gate_id,
                        ROOT_USER_ID,
                        claim.challenge.workspace_id,
                    ),
                ).fetchone()
                if challenge_updated is None:
                    raise PaperGateAuthorityConflict("paper gate error challenge CAS failed")
                updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_paper_gate_actions
                    SET action_state = %s,
                        lease_token = NULL,
                        lease_until = NULL,
                        receipt = %s,
                        last_error_code = %s
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND action_kind = %s
                      AND client_action_id = %s
                      AND action_state = 'executing'
                      AND lease_token = %s
                    RETURNING gate_id
                    """,
                    (
                        action_state,
                        Jsonb(receipt.to_storage_dict()),
                        reason_code,
                        ROOT_USER_ID,
                        claim.challenge.workspace_id,
                        claim.action_kind,
                        claim.client_action_id,
                        claim.lease_token,
                    ),
                ).fetchone()
                if updated is None:
                    raise PaperGateAuthorityConflict("paper gate error finalization CAS failed")
                return receipt
        except PaperGateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable(
                "paper gate error finalization failed",
                code="paper_gate_finalization_outcome_unknown",
            ) from exc

    def _mark_retryable(self, claim: _Claim, reason_code: str) -> None:
        try:
            with self._database().connect() as conn, conn.transaction():
                self._require_schema(conn)
                self._lock(conn, claim.challenge.workspace_id)
                updated = conn.execute(
                    f"""
                    UPDATE {SCHEMA}.agent_v02_paper_gate_actions
                    SET action_state = 'retryable',
                        lease_token = NULL,
                        lease_until = NULL,
                        last_error_code = %s
                    WHERE owner_user_id = %s
                      AND workspace_id = %s
                      AND action_kind = %s
                      AND client_action_id = %s
                      AND action_state = 'executing'
                      AND lease_token = %s
                    RETURNING gate_id
                    """,
                    (
                        reason_code,
                        ROOT_USER_ID,
                        claim.challenge.workspace_id,
                        claim.action_kind,
                        claim.client_action_id,
                        claim.lease_token,
                    ),
                ).fetchone()
                if updated is None:
                    raise PaperGateAuthorityConflict("paper gate retryable CAS failed")
        except PaperGateAuthorityError:
            raise
        except (DatabaseUnavailable, psycopg.Error) as exc:
            raise PaperGateAuthorityUnavailable(
                "paper gate retryable finalization failed",
                code="paper_gate_finalization_outcome_unknown",
            ) from exc


__all__ = [
    "PAPER_GATE_SCHEMA_VERSION",
    "PaperGateAuthority",
    "PaperGateAuthorityConflict",
    "PaperGateNotFound",
    "PaperGateAuthorityError",
    "PaperGateAuthorityUnavailable",
    "PaperGateAuthorityValidationError",
    "PaperGateChallengeRecord",
    "PaperGateCompletionRecord",
    "PaperGateExecutionPort",
    "PaperGateReceipt",
    "RegisterPaperGateChallenge",
    "RegisterPaperGateCompletion",
    "paper_gate_schema_is_ready_on_connection",
    "paper_gate_schema_ready",
]
