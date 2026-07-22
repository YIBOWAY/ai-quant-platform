"""HQA↔PG crash-safe submission helpers for AgentWorkspace act() (V4).

Public browser mutation stays OFF. Callers must pass ``mutation_enabled=True``
explicitly (hermetic tests / future gated BFF). This module never calls Hermes
or any provider.

Identity derivation (create/fork)
---------------------------------
``platform_session_id`` and ``hermes_session_id`` are deterministic functions of
the canonical action digest so retries after process death re-register the same
row. Idempotency of *receipts* is anchored on the command ledger unique key
``(owner, control_plane_session_id, client_action_id)`` where
``control_plane_session_id = awctl_{workspace_id}`` (truncated to 200).

Crash windows
-------------
1. After create_command commit, before register_workspace_session:
   retry sees existing command + matching digest, then completes registration.
2. After both commit: retry returns the same accepted receipt (created=False).
3. Same client_action_id / different digest: ledger raises conflict; zero new
   session or command rows beyond the original.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from quant_system.config.settings import Settings
from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    ConfirmResearchPlan,
    ContinueResearch,
    ConversationTurn,
    CreateManagedSession,
    DecideHermesCommandApproval,
    ForkIntoManagedSession,
    StartResearch,
    UnsupportedWorkspaceAction,
    UserActionV1,
    action_payload_ref_for_digest,
    action_to_document,
    canonical_action_digest,
    hqa_payload_to_platform_payload_ref,
    parse_user_action_v1,
    session_ref,
    strip_session_ref,
)
from quant_system.hermes.approval_release_port import (
    ApprovalReleaseError,
    default_approval_release_adapter,
    map_decision_to_release_choice,
)
from quant_system.hermes.command_approval_authority import (
    CommandApprovalAuthorityError,
    default_command_approval_authority,
)
from quant_system.hermes.command_ledger import (
    ROOT_USER_ID,
    CreateHermesCommandResult,
    HermesCommandConflict,
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
    HermesCommandValidationError,
)
from quant_system.hermes.session_registry import (
    HermesSessionNotWritable,
    HermesSessionRegistryConflict,
    HermesSessionRegistryUnavailable,
    HermesSessionRegistryValidationError,
    RegisterWorkspaceSession,
    get_workspace_session,
    register_workspace_session,
    require_web_writable_session,
)

ReceiptStatus = Literal[
    "accepted",
    "reconciling",
    "conflict",
    "unavailable",
    "outcome_unknown",
]

_RECOVERY = {
    "accepted": None,
    "reconciling": "follow_workspace",
    "conflict": "choose_legal_target_or_new_action",
    "unavailable": "retry_read_or_reconcile_original_action",
    "outcome_unknown": "follow_and_reconcile_original_action",
}

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_CONTROL_PREFIX = "awctl_"


@dataclass(frozen=True)
class ActionReceipt:
    status: ReceiptStatus
    client_action_id: str
    action_digest: str
    workspace_id: str
    command_id: str | None = None
    run_id: str | None = None
    platform_session_id: str | None = None
    hermes_session_id: str | None = None
    recovery_action: str | None = None
    reason_code: str | None = None
    mutation_enabled: bool = False

    def __post_init__(self) -> None:
        expected = _RECOVERY[self.status]
        if self.recovery_action != expected:
            object.__setattr__(self, "recovery_action", expected)

    def to_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": self.status,
            "client_action_id": self.client_action_id,
            "action_digest": self.action_digest,
            "workspace": {"workspace_id": self.workspace_id},
            "recovery_action": self.recovery_action,
            "mutation_enabled": bool(self.mutation_enabled),
        }
        if self.command_id is not None:
            payload["command_id"] = self.command_id
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.platform_session_id is not None:
            payload["platform_session_id"] = self.platform_session_id
            payload["session_ref"] = session_ref(self.platform_session_id)
        if self.hermes_session_id is not None:
            payload["hermes_session_id"] = self.hermes_session_id
        if self.reason_code is not None:
            payload["reason_code"] = self.reason_code
        return payload


class SubmissionSagaError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def control_plane_session_id(workspace_id: str) -> str:
    """Synthetic platform_session_id used only as the ledger idempotency namespace."""
    if _SESSION_ID_RE.fullmatch(workspace_id) is None:
        raise SubmissionSagaError("validation", "invalid workspace_id")
    # Keep total length <= 200 and identifier-safe.
    raw = f"{_CONTROL_PREFIX}{workspace_id}"
    if len(raw) > 200:
        raw = raw[:200]
    if _SESSION_ID_RE.fullmatch(raw) is None:
        raise SubmissionSagaError("validation", "invalid control plane session id")
    return raw


def derive_managed_platform_session_id(action_digest: str) -> str:
    # wm_ + 32 hex chars = 35; stable across retries of the same action digest.
    return f"wm_{action_digest[:32]}"


def derive_managed_hermes_session_id(action_digest: str) -> str:
    # Dark install: no Hermes call. Identity is platform-allocated and durable.
    return f"web_{action_digest[:40]}"


def authorities_ready(settings: Settings) -> dict[str, object]:
    """Schema readiness for managed-session + research authorities.

    Delegates to ``composer_readiness.authority_readiness`` so gateway, health,
    workspace snapshot, and saga share one probe surface. Public mutation and
    composer write flags stay hard OFF regardless of schema readiness.
    """
    from quant_system.hermes.composer_readiness import authority_readiness

    return authority_readiness(settings)


def _receipt(
    *,
    status: ReceiptStatus,
    action: UserActionV1,
    digest: str,
    command_id: str | None = None,
    run_id: str | None = None,
    platform_session_id: str | None = None,
    hermes_session_id: str | None = None,
    reason_code: str | None = None,
    mutation_enabled: bool = False,
) -> ActionReceipt:
    return ActionReceipt(
        status=status,
        client_action_id=action.client_action_id,
        action_digest=digest,
        workspace_id=action.workspace.workspace_id,
        command_id=command_id,
        run_id=run_id,
        platform_session_id=platform_session_id,
        hermes_session_id=hermes_session_id,
        reason_code=reason_code,
        mutation_enabled=bool(mutation_enabled),
    )


def _require_root_actor(actor_owner_user_id: UUID | str) -> UUID:
    if isinstance(actor_owner_user_id, UUID):
        owner = actor_owner_user_id
    else:
        try:
            owner = UUID(str(actor_owner_user_id))
        except (TypeError, ValueError) as exc:
            raise SubmissionSagaError("auth", "invalid actor") from exc
    if owner != ROOT_USER_ID:
        raise SubmissionSagaError("forbidden", "owner_user_id must be the root user")
    return owner


def _ensure_ready(settings: Settings) -> bool:
    return bool(authorities_ready(settings)["ready"])


def _create_idempotent_command(
    settings: Settings,
    *,
    platform_session_id: str,
    client_request_id: str,
    kind: str,
    action_digest: str,
    payload_ref: str,
    provider_policy_digest: str | None,
) -> CreateHermesCommandResult:
    ledger = HermesCommandLedger(settings)
    try:
        return ledger.create_command(
            platform_session_id=platform_session_id,
            client_request_id=client_request_id,
            kind=kind,
            canonical_request_digest=action_digest,
            payload_ref=payload_ref,
            provider_policy_digest=provider_policy_digest,
        )
    except HermesCommandConflict as exc:
        raise SubmissionSagaError("conflict", str(exc) or "workspace_conflict") from exc
    except HermesCommandValidationError as exc:
        raise SubmissionSagaError("validation", str(exc)) from exc
    except HermesCommandLedgerUnavailable as exc:
        raise SubmissionSagaError("unavailable", str(exc)) from exc


def submit_create_managed_session(
    settings: Settings,
    action: CreateManagedSession,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
)
    _require_root_actor(actor_owner_user_id)
    if not _ensure_ready(settings):
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="workspace_authority_unavailable",
            mutation_enabled=mutation_enabled,
)

    control_session = control_plane_session_id(action.workspace.workspace_id)
    try:
        cmd = _create_idempotent_command(
            settings,
            platform_session_id=control_session,
            client_request_id=action.client_action_id,
            kind="managed_session_create",
            action_digest=digest,
            payload_ref=action_payload_ref_for_digest(digest),
            provider_policy_digest=action.provider_policy_digest,
        )
    except SubmissionSagaError as exc:
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code="idempotency_digest_conflict",
                mutation_enabled=mutation_enabled,
)
        if exc.code == "unavailable":
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                reason_code="authority_unavailable",
                mutation_enabled=mutation_enabled,
)
        raise

    platform_session_id = derive_managed_platform_session_id(digest)
    hermes_session_id = derive_managed_hermes_session_id(digest)
    try:
        record, _created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id=platform_session_id,
                hermes_session_id=hermes_session_id,
                workspace_id=action.workspace.workspace_id,
                kind="web_managed_session",
                provider_policy_digest=action.provider_policy_digest,
            ),
        )
    except HermesSessionRegistryConflict:
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            command_id=str(cmd.command.command_id),
            reason_code="session_identity_conflict",
            mutation_enabled=mutation_enabled,
)
    except HermesSessionRegistryUnavailable:
        # Command durable; session not yet — caller should retry same action.
        return _receipt(
            status="reconciling",
            action=action,
            digest=digest,
            command_id=str(cmd.command.command_id),
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
            reason_code="session_registry_pending",
            mutation_enabled=mutation_enabled,
)
    except HermesSessionRegistryValidationError:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            command_id=str(cmd.command.command_id),
            reason_code="session_registry_validation",
            mutation_enabled=mutation_enabled,
)

    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=str(cmd.command.command_id),
        platform_session_id=record.platform_session_id,
        hermes_session_id=record.hermes_session_id,
        mutation_enabled=mutation_enabled,
)


def submit_fork_into_managed_session(
    settings: Settings,
    action: ForkIntoManagedSession,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
)
    _require_root_actor(actor_owner_user_id)
    if not _ensure_ready(settings):
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="workspace_authority_unavailable",
            mutation_enabled=mutation_enabled,
)

    source_platform_session_id = strip_session_ref(action.source_session_ref)
    try:
        source = get_workspace_session(
            settings, platform_session_id=source_platform_session_id
        )
    except LookupError:
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            reason_code="source_session_missing",
            mutation_enabled=mutation_enabled,
)
    except (
        HermesSessionRegistryUnavailable,
        HermesSessionRegistryValidationError,
    ):
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="session_registry_unavailable",
            mutation_enabled=mutation_enabled,
)

    if source.workspace_id != action.workspace.workspace_id:
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            reason_code="source_workspace_mismatch",
            mutation_enabled=mutation_enabled,
)

    control_session = control_plane_session_id(action.workspace.workspace_id)
    try:
        cmd = _create_idempotent_command(
            settings,
            platform_session_id=control_session,
            client_request_id=action.client_action_id,
            kind="managed_session_fork",
            action_digest=digest,
            payload_ref=action_payload_ref_for_digest(digest),
            provider_policy_digest=action.new_provider_policy_digest,
        )
    except SubmissionSagaError as exc:
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code="idempotency_digest_conflict",
                mutation_enabled=mutation_enabled,
)
        if exc.code == "unavailable":
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                reason_code="authority_unavailable",
                mutation_enabled=mutation_enabled,
)
        raise

    platform_session_id = derive_managed_platform_session_id(digest)
    hermes_session_id = derive_managed_hermes_session_id(digest)
    try:
        record, _created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id=platform_session_id,
                hermes_session_id=hermes_session_id,
                workspace_id=action.workspace.workspace_id,
                kind="web_managed_session",
                source_channel=action.source_channel,
                parent_platform_session_id=source.platform_session_id,
                fork_point=action.fork_point,
                provider_policy_digest=action.new_provider_policy_digest,
            ),
        )
    except HermesSessionRegistryConflict:
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            command_id=str(cmd.command.command_id),
            reason_code="session_identity_conflict",
            mutation_enabled=mutation_enabled,
)
    except HermesSessionRegistryUnavailable:
        return _receipt(
            status="reconciling",
            action=action,
            digest=digest,
            command_id=str(cmd.command.command_id),
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
            reason_code="session_registry_pending",
            mutation_enabled=mutation_enabled,
)
    except HermesSessionRegistryValidationError:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            command_id=str(cmd.command.command_id),
            reason_code="session_registry_validation",
            mutation_enabled=mutation_enabled,
)

    # Source external/managed row must remain unchanged (fork is additive).
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=str(cmd.command.command_id),
        platform_session_id=record.platform_session_id,
        hermes_session_id=record.hermes_session_id,
        mutation_enabled=mutation_enabled,
)


def submit_conversation_turn(
    settings: Settings,
    action: ConversationTurn,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
)
    _require_root_actor(actor_owner_user_id)
    if not _ensure_ready(settings):
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="workspace_authority_unavailable",
            mutation_enabled=mutation_enabled,
)

    platform_session_id = strip_session_ref(action.managed_session_ref)
    try:
        session = require_web_writable_session(
            settings, platform_session_id=platform_session_id
        )
    except HermesSessionNotWritable:
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            platform_session_id=platform_session_id,
            reason_code="external_session_not_writable",
            mutation_enabled=mutation_enabled,
)
    except LookupError:
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            reason_code="managed_session_missing",
            mutation_enabled=mutation_enabled,
)
    except (
        HermesSessionRegistryUnavailable,
        HermesSessionRegistryValidationError,
    ):
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="session_registry_unavailable",
            mutation_enabled=mutation_enabled,
)

    if session.workspace_id != action.workspace.workspace_id:
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            platform_session_id=platform_session_id,
            reason_code="session_workspace_mismatch",
            mutation_enabled=mutation_enabled,
)

    platform_payload_ref = hqa_payload_to_platform_payload_ref(action.payload_digest)
    try:
        cmd = _create_idempotent_command(
            settings,
            platform_session_id=platform_session_id,
            client_request_id=action.client_action_id,
            kind="conversation_turn",
            action_digest=digest,
            payload_ref=platform_payload_ref,
            provider_policy_digest=session.provider_policy_digest,
        )
    except SubmissionSagaError as exc:
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                platform_session_id=platform_session_id,
                hermes_session_id=session.hermes_session_id,
                reason_code="idempotency_digest_conflict",
                mutation_enabled=mutation_enabled,
)
        if exc.code == "unavailable":
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                platform_session_id=platform_session_id,
                reason_code="authority_unavailable",
                mutation_enabled=mutation_enabled,
)
        raise

    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=str(cmd.command.command_id),
        platform_session_id=session.platform_session_id,
        hermes_session_id=session.hermes_session_id,
        mutation_enabled=mutation_enabled,
)


def submit_decide_hermes_command_approval(
    settings: Settings,
    action: DecideHermesCommandApproval,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7a+V7b: exact CAS decide then hermetic respond_approval release/signal.

    Challenge CAS is owned by ``CommandApprovalAuthority``. After a successful
    decide (including exact client_action_id+digest replay), the saga maps
    ``allow_once``→``once`` / ``deny``→``deny`` and calls the hermetic approval
    release port so the waiter can be signalled. Release failure does **not**
    roll back the CAS; the receipt becomes ``reconciling`` so the client
    follows workspace state (pending already empty). No always-allow; no Gate
    1/2/3; no live HTTP Hermes in M1.
    """
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
        )
    _require_root_actor(actor_owner_user_id)

    authority = default_command_approval_authority()
    try:
        decided = authority.decide(
            workspace_id=action.workspace.workspace_id,
            approval_ref=action.approval_ref,
            run_ref=action.run_ref,
            command_digest=action.command_digest,
            expected_status=action.expected_status,
            expected_expires_at=action.expected_expires_at,
            decision=action.decision,
            client_action_id=action.client_action_id,
            action_digest=digest,
        )
    except CommandApprovalAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.message,
                mutation_enabled=mutation_enabled,
            )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message or "command_approval_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )

    # V7b: release + signal after CAS. Authority already committed; never
    # resurrect pending on release failure. Exact decide replay also re-enters
    # respond_approval so the release side can idempotent-replay.
    try:
        choice = map_decision_to_release_choice(action.decision)
        default_approval_release_adapter().respond_approval(
            decided.run_id,
            choice=choice,
            challenge_id=decided.approval_id,
            action_digest=decided.command_digest,
        )
    except ApprovalReleaseError as exc:
        return _receipt(
            status="reconciling",
            action=action,
            digest=digest,
            run_id=decided.run_id,
            reason_code=exc.code or "approval_release_failed",
            mutation_enabled=mutation_enabled,
        )

    # Best-effort durable audit row on the control-plane session. Challenge CAS
    # + release already committed above; ledger outage must not undo them.
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="hermes_command_approval_decide",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except SubmissionSagaError as exc:
            if exc.code == "conflict":
                # Same client_action_id / different digest is a true conflict on
                # the audit rail; challenge already matches action_digest so
                # treat as accepted with no new command id.
                if exc.message and "digest" in exc.message.lower():
                    return _receipt(
                        status="conflict",
                        action=action,
                        digest=digest,
                        reason_code="idempotency_digest_conflict",
                        mutation_enabled=mutation_enabled,
                    )
            # Authority + release already decided; return accepted without command_id.
            command_id = None

    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=decided.run_id,
        mutation_enabled=mutation_enabled,
    )


def submit_action(
    settings: Settings,
    action: UserActionV1 | dict[str, object],
    *,
    mutation_enabled: bool = False,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """Dispatch one closed action through the crash-safe submission path."""
    if isinstance(action, dict):
        try:
            parsed: UserActionV1 = parse_user_action_v1(action)
        except (AgentWorkspaceActionError, TypeError, ValueError) as exc:
            raise SubmissionSagaError("validation", str(exc) or "validation") from exc
    else:
        parsed = action
        # Re-validate via round-trip for frozen dataclasses.
        try:
            parsed = parse_user_action_v1(action_to_document(parsed))
        except (AgentWorkspaceActionError, TypeError, ValueError) as exc:
            raise SubmissionSagaError("validation", str(exc) or "validation") from exc

    if type(parsed) is CreateManagedSession:
        return submit_create_managed_session(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is ForkIntoManagedSession:
        return submit_fork_into_managed_session(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is ConversationTurn:
        return submit_conversation_turn(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is DecideHermesCommandApproval:
        return submit_decide_hermes_command_approval(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) in (StartResearch, ContinueResearch, ConfirmResearchPlan):
        # Research kinds are typed and digest-stable, but the HQA prepare →
        # ensure_bound_command browser path stays dark in V4. Public mutation
        # gate still wins first when OFF; hermetic mutation=True still refuses
        # with an explicit research submission blocker (zero PG writes).
        digest = canonical_action_digest(parsed)
        if not mutation_enabled:
            return _receipt(
                status="unavailable",
                action=parsed,
                digest=digest,
                reason_code="authenticated_mutation_bff_unavailable",
                mutation_enabled=mutation_enabled,
)
        return _receipt(
            status="unavailable",
            action=parsed,
            digest=digest,
            reason_code="research_workflow_submission_unavailable",
            mutation_enabled=mutation_enabled,
)
    if type(parsed) is UnsupportedWorkspaceAction:
        digest = canonical_action_digest(parsed)
        return _receipt(
            status="unavailable",
            action=parsed,
            digest=digest,
            reason_code="action_kind_not_implemented",
            mutation_enabled=mutation_enabled,
)
    raise SubmissionSagaError("validation", "unknown action type")


__all__ = [
    "ActionReceipt",
    "SubmissionSagaError",
    "authorities_ready",
    "control_plane_session_id",
    "derive_managed_hermes_session_id",
    "derive_managed_platform_session_id",
    "submit_action",
    "submit_conversation_turn",
    "submit_create_managed_session",
    "submit_decide_hermes_command_approval",
    "submit_fork_into_managed_session",
]
