"""Closed UserActionV1 documents for the platform AgentWorkspace (V4).

Field shapes and canonical digests intentionally match HQA
``hqa.agent_workspace_actions`` so cross-repo receipts stay comparable.
This module does not import HQA (not on platform PYTHONPATH).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Union

_ACTION_KINDS = frozenset(
    {
        "managed_session.create",
        "managed_session.fork",
        "conversation.turn",
        "research.start",
        "research.continue",
        "research.plan.confirm",
        "run.stop.request",
        "hermes.command_approval.decide",
        "gate1.formula_source.confirm",
        "gate2.candidate.review",
        "gate3.promotion_review.prepare",
    }
)
_COMMON_DOCUMENT_FIELDS = frozenset(
    {"schema_version", "kind", "client_action_id", "workspace"}
)
_ACTION_FIELDS = {
    "managed_session.create": _COMMON_DOCUMENT_FIELDS
    | {"provider_policy_digest", "payload_ttl_days"},
    "managed_session.fork": _COMMON_DOCUMENT_FIELDS
    | {
        "source_session_ref",
        "source_channel",
        "fork_point",
        "new_provider_policy_digest",
        "payload_ttl_days",
    },
    "conversation.turn": _COMMON_DOCUMENT_FIELDS
    | {"managed_session_ref", "payload_ref", "payload_digest"},
    "research.start": _COMMON_DOCUMENT_FIELDS
    | {
        "managed_session_ref",
        "payload_ref",
        "payload_digest",
        "initial_mode",
    },
    "research.continue": _COMMON_DOCUMENT_FIELDS
    | {"managed_session_ref", "task_ref", "payload_ref", "payload_digest"},
    "research.plan.confirm": _COMMON_DOCUMENT_FIELDS
    | {"task_ref", "plan_version", "plan_digest", "confirmation_note"},
    "run.stop.request": _COMMON_DOCUMENT_FIELDS
    | {"run_ref", "task_ref", "attempt_ref", "platform_job_ref"},
    "hermes.command_approval.decide": _COMMON_DOCUMENT_FIELDS
    | {
        "approval_ref",
        "run_ref",
        "command_digest",
        "expected_status",
        "expected_expires_at",
        "decision",
    },
    "gate1.formula_source.confirm": _COMMON_DOCUMENT_FIELDS
    | {"task_ref", "reviewed_source_sha256", "confirmation_note"},
    "gate2.candidate.review": _COMMON_DOCUMENT_FIELDS
    | {"candidate_ref", "expected_digest", "expected_status", "note"},
    "gate3.promotion_review.prepare": _COMMON_DOCUMENT_FIELDS
    | {
        "candidate_ref",
        "expected_digest",
        "final_backtest_receipt_ref",
        "base_commit",
    },
}
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}\Z")
_HEX40_RE = re.compile(r"[0-9a-f]{40}\Z")
_RFC3339_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)


class AgentWorkspaceActionError(ValueError):
    """Malformed or unsupported user action document."""


@dataclass(frozen=True)
class WorkspaceRef:
    workspace_id: str

    def __post_init__(self) -> None:
        if (
            type(self.workspace_id) is not str
            or _IDENTIFIER_RE.fullmatch(self.workspace_id) is None
        ):
            raise AgentWorkspaceActionError("workspace_id must be a bounded identifier")


def _validate_common(client_action_id: Any, workspace: Any) -> None:
    if (
        type(client_action_id) is not str
        or _IDENTIFIER_RE.fullmatch(client_action_id) is None
    ):
        raise AgentWorkspaceActionError("client_action_id must be a bounded identifier")
    if type(workspace) is not WorkspaceRef:
        raise TypeError("workspace must be a WorkspaceRef")


def _parse_workspace(value: Any) -> WorkspaceRef:
    if type(value) is not dict:
        raise TypeError("workspace must be a JSON object")
    workspace = dict(value)
    if any(type(key) is not str for key in workspace):
        raise AgentWorkspaceActionError("workspace object keys must be exact strings")
    if set(workspace) != {"workspace_id"}:
        raise AgentWorkspaceActionError("workspace requires exact fields")
    return WorkspaceRef(workspace_id=workspace["workspace_id"])


def _validate_digest(value: Any, field: str) -> None:
    if type(value) is not str or _HEX64_RE.fullmatch(value) is None:
        raise AgentWorkspaceActionError(
            "{} must be a lowercase SHA-256 digest".format(field)
        )


def _validate_payload_ttl_days(value: Any) -> None:
    if type(value) is not int or not 1 <= value <= 30:
        raise AgentWorkspaceActionError(
            "payload_ttl_days must be an integer from 1 through 30"
        )


def _validate_ref(value: Any, field: str, prefix: str) -> None:
    if (
        type(value) is not str
        or not value.startswith(prefix)
        or len(value) == len(prefix)
        or _IDENTIFIER_RE.fullmatch(value) is None
    ):
        raise AgentWorkspaceActionError(
            "{} must be a bounded {} reference".format(field, prefix)
        )


def _validate_optional_ref(value: Any, field: str, prefix: str) -> None:
    if value is not None:
        _validate_ref(value, field, prefix)


def _validate_source_cursor(value: Any) -> None:
    if (
        type(value) is not str
        or not value
        or len(value) > 2_000
        or not value.isprintable()
    ):
        raise AgentWorkspaceActionError(
            "fork_point must be a bounded printable source cursor"
        )


def _validate_payload_binding(payload_ref: Any, payload_digest: Any) -> None:
    _validate_digest(payload_digest, "payload_digest")
    if type(payload_ref) is not str or payload_ref != (
        "payload:sha256:" + payload_digest
    ):
        raise AgentWorkspaceActionError("payload_ref must exactly match payload_digest")


def _normalize_timestamp(value: Any) -> str:
    """Normalize RFC3339 timestamps to canonical UTC microsecond Z form.

    Matches HQA ``hqa.agent_workspace_actions._normalize_timestamp`` so
    ``hermes.command_approval.decide`` digests stay cross-repo stable.
    """
    if type(value) is not str or _RFC3339_RE.fullmatch(value) is None:
        raise AgentWorkspaceActionError(
            "expected_expires_at must be a canonical timezone-aware timestamp"
        )
    parsed_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parsed_value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise AgentWorkspaceActionError(
                "expected_expires_at must be timezone-aware"
            )
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (ValueError, OverflowError, OSError) as exc:
        raise AgentWorkspaceActionError(
            "expected_expires_at must be a canonical timezone-aware timestamp"
        ) from exc


def _validate_note(value: Any, field: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 2_000
        or not value.isprintable()
    ):
        raise AgentWorkspaceActionError(
            "{} must be bounded nonempty printable text".format(field)
        )


def _validate_strict_json(value: Any) -> None:
    if value is None or type(value) in (str, int, bool):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise AgentWorkspaceActionError(
                "action document requires finite strict JSON numbers"
            )
        return
    if type(value) is list:
        for item in value:
            _validate_strict_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("action document requires strict JSON object keys")
            _validate_strict_json(item)
        return
    raise TypeError("action document requires strict JSON primitives")


def _strict_json_document(document: dict[str, Any]) -> dict[str, Any]:
    _validate_strict_json(document)
    return document


@dataclass(frozen=True)
class CreateManagedSession:
    client_action_id: str
    workspace: WorkspaceRef
    provider_policy_digest: str
    payload_ttl_days: int

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_digest(self.provider_policy_digest, "provider_policy_digest")
        _validate_payload_ttl_days(self.payload_ttl_days)


@dataclass(frozen=True)
class ForkIntoManagedSession:
    client_action_id: str
    workspace: WorkspaceRef
    source_session_ref: str
    source_channel: str
    fork_point: str
    new_provider_policy_digest: str
    payload_ttl_days: int

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(self.source_session_ref, "source_session_ref", "session:")
        if type(self.source_channel) is not str or self.source_channel not in (
            "discord",
            "historical",
            "web_managed",
        ):
            raise AgentWorkspaceActionError(
                "source_channel must be discord, historical, or web_managed"
            )
        _validate_source_cursor(self.fork_point)
        _validate_digest(
            self.new_provider_policy_digest, "new_provider_policy_digest"
        )
        _validate_payload_ttl_days(self.payload_ttl_days)


@dataclass(frozen=True)
class ConversationTurn:
    client_action_id: str
    workspace: WorkspaceRef
    managed_session_ref: str
    payload_ref: str
    payload_digest: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(
            self.managed_session_ref, "managed_session_ref", "session:"
        )
        _validate_payload_binding(self.payload_ref, self.payload_digest)


@dataclass(frozen=True)
class StartResearch:
    """HQA-aligned research.start. Executable path still dark on platform BFF."""

    client_action_id: str
    workspace: WorkspaceRef
    managed_session_ref: str
    payload_ref: str
    payload_digest: str
    initial_mode: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(
            self.managed_session_ref, "managed_session_ref", "session:"
        )
        _validate_payload_binding(self.payload_ref, self.payload_digest)
        if type(self.initial_mode) is not str or self.initial_mode != "plan_only":
            raise AgentWorkspaceActionError("initial_mode must be plan_only")


@dataclass(frozen=True)
class ContinueResearch:
    client_action_id: str
    workspace: WorkspaceRef
    managed_session_ref: str
    task_ref: str
    payload_ref: str
    payload_digest: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(
            self.managed_session_ref, "managed_session_ref", "session:"
        )
        _validate_ref(self.task_ref, "task_ref", "task:")
        _validate_payload_binding(self.payload_ref, self.payload_digest)


@dataclass(frozen=True)
class ConfirmResearchPlan:
    client_action_id: str
    workspace: WorkspaceRef
    task_ref: str
    plan_version: int
    plan_digest: str
    confirmation_note: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(self.task_ref, "task_ref", "task:")
        if type(self.plan_version) is not int or isinstance(
            self.plan_version, bool
        ) or self.plan_version < 1:
            raise AgentWorkspaceActionError(
                "plan_version must be a positive integer"
            )
        _validate_digest(self.plan_digest, "plan_digest")
        _validate_note(self.confirmation_note, "confirmation_note")


@dataclass(frozen=True)
class DecideHermesCommandApproval:
    """V7a: exact single-use Hermes command-approval decision (allow_once|deny).

    Not Gate 1/2/3. Not always-allow. CAS binds approval_ref + run_ref +
    command_digest + expected_status=pending + expected_expires_at.
    """

    client_action_id: str
    workspace: WorkspaceRef
    approval_ref: str
    run_ref: str
    command_digest: str
    expected_status: str
    expected_expires_at: str
    decision: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(self.approval_ref, "approval_ref", "approval:")
        _validate_ref(self.run_ref, "run_ref", "run:")
        _validate_digest(self.command_digest, "command_digest")
        if (
            type(self.expected_status) is not str
            or self.expected_status != "pending"
        ):
            raise AgentWorkspaceActionError("expected_status must be pending")
        if type(self.decision) is not str or self.decision not in (
            "allow_once",
            "deny",
        ):
            raise AgentWorkspaceActionError("decision must be allow_once or deny")
        object.__setattr__(
            self,
            "expected_expires_at",
            _normalize_timestamp(self.expected_expires_at),
        )


@dataclass(frozen=True)
class RequestStop:
    """V7c: Run-scoped stop intent with optional layered target refs.

    Required ``run_ref``; optional ``task_ref`` / ``attempt_ref`` /
    ``platform_job_ref`` stay nullable. M1 hermetic stop never invents Task
    stopped from a single run confirmation alone.
    """

    client_action_id: str
    workspace: WorkspaceRef
    run_ref: str
    task_ref: str | None
    attempt_ref: str | None
    platform_job_ref: str | None

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(self.run_ref, "run_ref", "run:")
        _validate_optional_ref(self.task_ref, "task_ref", "task:")
        _validate_optional_ref(self.attempt_ref, "attempt_ref", "attempt:")
        _validate_optional_ref(
            self.platform_job_ref, "platform_job_ref", "job:"
        )



@dataclass(frozen=True)
class ConfirmFormulaSource:
    """V7e Gate 1: exact reviewed source SHA-256 + nonempty note.

    ConfirmResearchPlan is **not** Gate 1. Not command-approval.
    """

    client_action_id: str
    workspace: WorkspaceRef
    task_ref: str
    reviewed_source_sha256: str
    confirmation_note: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(self.task_ref, "task_ref", "task:")
        _validate_digest(self.reviewed_source_sha256, "reviewed_source_sha256")
        _validate_note(self.confirmation_note, "confirmation_note")


@dataclass(frozen=True)
class ReviewCandidateCAS:
    """V7e Gate 2: exact candidate/digest/pending/note CAS (no-refetch)."""

    client_action_id: str
    workspace: WorkspaceRef
    candidate_ref: str
    expected_digest: str
    expected_status: str
    note: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(self.candidate_ref, "candidate_ref", "candidate:")
        _validate_digest(self.expected_digest, "expected_digest")
        if (
            type(self.expected_status) is not str
            or self.expected_status != "pending"
        ):
            raise AgentWorkspaceActionError("expected_status must be pending")
        _validate_note(self.note, "note")


@dataclass(frozen=True)
class PreparePromotionReview:
    """V7e Gate 3: prepare promotion review only — web never Git-commits."""

    client_action_id: str
    workspace: WorkspaceRef
    candidate_ref: str
    expected_digest: str
    final_backtest_receipt_ref: str
    base_commit: str

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        _validate_ref(self.candidate_ref, "candidate_ref", "candidate:")
        _validate_digest(self.expected_digest, "expected_digest")
        _validate_ref(
            self.final_backtest_receipt_ref,
            "final_backtest_receipt_ref",
            "receipt:",
        )
        if (
            type(self.base_commit) is not str
            or _HEX40_RE.fullmatch(self.base_commit) is None
        ):
            raise AgentWorkspaceActionError(
                "base_commit must be a lowercase 40-hex commit"
            )


@dataclass(frozen=True)
class UnsupportedWorkspaceAction:
    """Placeholder for action kinds not yet implemented on the platform BFF."""

    kind: str
    client_action_id: str
    workspace: WorkspaceRef
    document: dict[str, Any]

    def __post_init__(self) -> None:
        _validate_common(self.client_action_id, self.workspace)
        if type(self.kind) is not str or self.kind not in _ACTION_KINDS:
            raise AgentWorkspaceActionError("unknown UserActionV1 kind")


UserActionV1 = Union[
    CreateManagedSession,
    ForkIntoManagedSession,
    ConversationTurn,
    StartResearch,
    ContinueResearch,
    ConfirmResearchPlan,
    DecideHermesCommandApproval,
    RequestStop,
    ConfirmFormulaSource,
    ReviewCandidateCAS,
    PreparePromotionReview,
    UnsupportedWorkspaceAction,
]

# Fully executable on the hermetic saga path (mutation gate still required).
_IMPLEMENTED_TYPES = (
    CreateManagedSession,
    ForkIntoManagedSession,
    ConversationTurn,
    DecideHermesCommandApproval,
    RequestStop,
    ConfirmFormulaSource,
    ReviewCandidateCAS,
    PreparePromotionReview,
)

# Typed + validated, but browser/saga submission stays fail-closed in V4.
_TYPED_RESEARCH_TYPES = (
    StartResearch,
    ContinueResearch,
    ConfirmResearchPlan,
)


def _action_to_raw_document(action: UserActionV1) -> dict[str, Any]:
    if type(action) is UnsupportedWorkspaceAction:
        return _strict_json_document(dict(action.document))
    if type(action) not in _IMPLEMENTED_TYPES + _TYPED_RESEARCH_TYPES:
        raise TypeError("unknown UserActionV1 type")
    document: dict[str, Any] = {
        "schema_version": 1,
        "client_action_id": action.client_action_id,
        "workspace": {"workspace_id": action.workspace.workspace_id},
    }
    if type(action) is CreateManagedSession:
        document.update(
            {
                "kind": "managed_session.create",
                "provider_policy_digest": action.provider_policy_digest,
                "payload_ttl_days": action.payload_ttl_days,
            }
        )
        return _strict_json_document(document)
    if type(action) is ForkIntoManagedSession:
        document.update(
            {
                "kind": "managed_session.fork",
                "source_session_ref": action.source_session_ref,
                "source_channel": action.source_channel,
                "fork_point": action.fork_point,
                "new_provider_policy_digest": action.new_provider_policy_digest,
                "payload_ttl_days": action.payload_ttl_days,
            }
        )
        return _strict_json_document(document)
    if type(action) is ConversationTurn:
        document.update(
            {
                "kind": "conversation.turn",
                "managed_session_ref": action.managed_session_ref,
                "payload_ref": action.payload_ref,
                "payload_digest": action.payload_digest,
            }
        )
        return _strict_json_document(document)
    if type(action) is StartResearch:
        document.update(
            {
                "kind": "research.start",
                "managed_session_ref": action.managed_session_ref,
                "payload_ref": action.payload_ref,
                "payload_digest": action.payload_digest,
                "initial_mode": action.initial_mode,
            }
        )
        return _strict_json_document(document)
    if type(action) is ContinueResearch:
        document.update(
            {
                "kind": "research.continue",
                "managed_session_ref": action.managed_session_ref,
                "task_ref": action.task_ref,
                "payload_ref": action.payload_ref,
                "payload_digest": action.payload_digest,
            }
        )
        return _strict_json_document(document)
    if type(action) is ConfirmResearchPlan:
        document.update(
            {
                "kind": "research.plan.confirm",
                "task_ref": action.task_ref,
                "plan_version": action.plan_version,
                "plan_digest": action.plan_digest,
                "confirmation_note": action.confirmation_note,
            }
        )
        return _strict_json_document(document)
    if type(action) is DecideHermesCommandApproval:
        document.update(
            {
                "kind": "hermes.command_approval.decide",
                "approval_ref": action.approval_ref,
                "run_ref": action.run_ref,
                "command_digest": action.command_digest,
                "expected_status": action.expected_status,
                "expected_expires_at": action.expected_expires_at,
                "decision": action.decision,
            }
        )
        return _strict_json_document(document)
    if type(action) is RequestStop:
        document.update(
            {
                "kind": "run.stop.request",
                "run_ref": action.run_ref,
                "task_ref": action.task_ref,
                "attempt_ref": action.attempt_ref,
                "platform_job_ref": action.platform_job_ref,
            }
        )
        return _strict_json_document(document)
    if type(action) is ConfirmFormulaSource:
        document.update(
            {
                "kind": "gate1.formula_source.confirm",
                "task_ref": action.task_ref,
                "reviewed_source_sha256": action.reviewed_source_sha256,
                "confirmation_note": action.confirmation_note,
            }
        )
        return _strict_json_document(document)
    if type(action) is ReviewCandidateCAS:
        document.update(
            {
                "kind": "gate2.candidate.review",
                "candidate_ref": action.candidate_ref,
                "expected_digest": action.expected_digest,
                "expected_status": action.expected_status,
                "note": action.note,
            }
        )
        return _strict_json_document(document)
    if type(action) is PreparePromotionReview:
        document.update(
            {
                "kind": "gate3.promotion_review.prepare",
                "candidate_ref": action.candidate_ref,
                "expected_digest": action.expected_digest,
                "final_backtest_receipt_ref": action.final_backtest_receipt_ref,
                "base_commit": action.base_commit,
            }
        )
        return _strict_json_document(document)
    raise TypeError("unknown UserActionV1 type")


def action_to_document(action: UserActionV1) -> dict[str, Any]:
    return _action_to_raw_document(action)


def canonical_action_digest(action: UserActionV1) -> str:
    canonical_json = json.dumps(
        action_to_document(action),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def parse_user_action_v1(document: Mapping[str, Any]) -> UserActionV1:
    if type(document) is not dict:
        raise TypeError("UserActionV1 document must be a built-in dict")
    document = dict(document)
    if any(type(key) is not str for key in document):
        raise AgentWorkspaceActionError("UserActionV1 document keys must be exact strings")
    if "kind" not in document:
        raise AgentWorkspaceActionError("UserActionV1 document requires exact fields")
    kind = document.get("kind")
    if type(kind) is not str or kind not in _ACTION_KINDS:
        raise AgentWorkspaceActionError("unknown UserActionV1 kind")
    if set(document) != _ACTION_FIELDS[kind]:
        raise AgentWorkspaceActionError("UserActionV1 document requires exact fields")
    if type(document.get("schema_version")) is not int or document.get(
        "schema_version"
    ) != 1:
        raise AgentWorkspaceActionError("schema_version must be the integer 1")
    common = {
        "client_action_id": document["client_action_id"],
        "workspace": _parse_workspace(document["workspace"]),
    }
    if kind == "managed_session.create":
        return CreateManagedSession(
            **common,
            provider_policy_digest=document["provider_policy_digest"],
            payload_ttl_days=document["payload_ttl_days"],
        )
    if kind == "managed_session.fork":
        return ForkIntoManagedSession(
            **common,
            source_session_ref=document["source_session_ref"],
            source_channel=document["source_channel"],
            fork_point=document["fork_point"],
            new_provider_policy_digest=document["new_provider_policy_digest"],
            payload_ttl_days=document["payload_ttl_days"],
        )
    if kind == "conversation.turn":
        return ConversationTurn(
            **common,
            managed_session_ref=document["managed_session_ref"],
            payload_ref=document["payload_ref"],
            payload_digest=document["payload_digest"],
        )
    if kind == "research.start":
        return StartResearch(
            **common,
            managed_session_ref=document["managed_session_ref"],
            payload_ref=document["payload_ref"],
            payload_digest=document["payload_digest"],
            initial_mode=document["initial_mode"],
        )
    if kind == "research.continue":
        return ContinueResearch(
            **common,
            managed_session_ref=document["managed_session_ref"],
            task_ref=document["task_ref"],
            payload_ref=document["payload_ref"],
            payload_digest=document["payload_digest"],
        )
    if kind == "research.plan.confirm":
        return ConfirmResearchPlan(
            **common,
            task_ref=document["task_ref"],
            plan_version=document["plan_version"],
            plan_digest=document["plan_digest"],
            confirmation_note=document["confirmation_note"],
        )
    if kind == "hermes.command_approval.decide":
        return DecideHermesCommandApproval(
            **common,
            approval_ref=document["approval_ref"],
            run_ref=document["run_ref"],
            command_digest=document["command_digest"],
            expected_status=document["expected_status"],
            expected_expires_at=document["expected_expires_at"],
            decision=document["decision"],
        )
    if kind == "run.stop.request":
        return RequestStop(
            **common,
            run_ref=document["run_ref"],
            task_ref=document["task_ref"],
            attempt_ref=document["attempt_ref"],
            platform_job_ref=document["platform_job_ref"],
        )
    if kind == "gate1.formula_source.confirm":
        return ConfirmFormulaSource(
            **common,
            task_ref=document["task_ref"],
            reviewed_source_sha256=document["reviewed_source_sha256"],
            confirmation_note=document["confirmation_note"],
        )
    if kind == "gate2.candidate.review":
        return ReviewCandidateCAS(
            **common,
            candidate_ref=document["candidate_ref"],
            expected_digest=document["expected_digest"],
            expected_status=document["expected_status"],
            note=document["note"],
        )
    if kind == "gate3.promotion_review.prepare":
        return PreparePromotionReview(
            **common,
            candidate_ref=document["candidate_ref"],
            expected_digest=document["expected_digest"],
            final_backtest_receipt_ref=document["final_backtest_receipt_ref"],
            base_commit=document["base_commit"],
        )
    # Remaining kinds are accepted as typed documents but not executable yet.
    return UnsupportedWorkspaceAction(
        kind=kind,
        client_action_id=str(document["client_action_id"]),
        workspace=common["workspace"],
        document=document,
    )


def session_ref(platform_session_id: str) -> str:
    if _IDENTIFIER_RE.fullmatch(platform_session_id) is None:
        raise AgentWorkspaceActionError("invalid platform_session_id for session ref")
    return "session:" + platform_session_id


def strip_session_ref(session_ref_value: str) -> str:
    _validate_ref(session_ref_value, "session_ref", "session:")
    return session_ref_value[len("session:") :]


def hqa_payload_to_platform_payload_ref(payload_digest: str) -> str:
    """Map content-addressed HQA payload digest to ledger-safe opaque ref.

    Never embeds prompt text. Matches command_ledger ``platform-payload://`` regex.
    """
    _validate_digest(payload_digest, "payload_digest")
    return f"platform-payload://sha256/{payload_digest}"


def action_payload_ref_for_digest(action_digest: str) -> str:
    _validate_digest(action_digest, "action_digest")
    return f"platform-payload://action/{action_digest}"


__all__ = [
    "AgentWorkspaceActionError",
    "ConfirmFormulaSource",
    "ConfirmResearchPlan",
    "ContinueResearch",
    "ConversationTurn",
    "CreateManagedSession",
    "DecideHermesCommandApproval",
    "ForkIntoManagedSession",
    "PreparePromotionReview",
    "RequestStop",
    "ReviewCandidateCAS",
    "StartResearch",
    "UnsupportedWorkspaceAction",
    "UserActionV1",
    "WorkspaceRef",
    "action_payload_ref_for_digest",
    "action_to_document",
    "canonical_action_digest",
    "hqa_payload_to_platform_payload_ref",
    "parse_user_action_v1",
    "session_ref",
    "strip_session_ref",
]
