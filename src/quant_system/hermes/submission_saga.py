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
    BindFactorVerticalB,
    BindOptionsVerticalA,
    ConfirmFactorVerticalBPlan,
    ConfirmFormulaSource,
    SeedFactorVerticalBGate1,
    ConfirmFactorVerticalBGate1,
    SeedFactorVerticalBGate2,
    ConfirmResearchPlan,
    ContinueResearch,
    ConversationTurn,
    CreateManagedSession,
    DecideHermesCommandApproval,
    ForkIntoManagedSession,
    PreparePromotionReview,
    RequestStop,
    ReviewCandidateCAS,
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
    IssueCanaryGrant,
    RevokeCanaryGrant,
    AcceptCanaryDualVertical,
    OpenPublicCutover,
    ClosePublicCutover,
)
from quant_system.hermes.approval_release_port import (
    ApprovalReleaseError,
    default_approval_release_adapter,
    map_decision_to_release_choice,
)
from quant_system.hermes.run_stop_port import (
    RunStopError,
    build_layered_stop_receipt,
    default_run_stop_adapter,
    strip_run_ref,
)
from quant_system.hermes.command_approval_authority import (
    CommandApprovalAuthorityError,
    default_command_approval_authority,
)
from quant_system.hermes.gate_surface_authority import (
    GateSurfaceAuthorityError,
    default_gate_surface_authority,
)
from quant_system.hermes.public_cutover_authority import (
    PublicCutoverAuthorityError,
    default_public_cutover_authority,
)
from quant_system.hermes.public_cutover_observe import (
    note_public_cutover_closed,
    note_public_cutover_opened,
)
from quant_system.hermes.canary_grant_authority import (
    CanaryGrantAuthorityError,
    default_canary_grant_authority,
)
from quant_system.hermes.canary_observe import (
    note_canary_accepted,
    note_canary_issued,
    note_canary_revoked,
)

from quant_system.hermes.gate_observe import note_gate_decided, note_gate_raised
from quant_system.hermes.result_observe import note_result_raised
from quant_system.hermes.vertical_binding_authority import (
    VerticalBindingAuthorityError,
    default_vertical_binding_authority,
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
    # V7c plan §5.5 layered stop observation (optional; stop actions only).
    stop_layers: dict[str, object] | None = None
    # V7g-A-M1: hermetic vertical bind outcome ids (optional).
    task_id: str | None = None
    attempt_id: str | None = None
    result_id: str | None = None
    terminal_status: str | None = None
    # V7g-B-M3: optional Gate1 id after vertical.factor_b.gate1_seed.
    gate_id: str | None = None
    # V8-M5: optional canary grant identity (issue/revoke/accept).
    grant_id: str | None = None
    grant_digest: str | None = None
    canary_ref: str | None = None
    acceptance_id: str | None = None
    # V8-M5: force honesty triad on canary-kind receipts (incl. conflict/unavailable).
    canary_honesty: bool = False
    # V8-M6 public cutover (G7/G8)
    cutover_id: str | None = None
    cutover_digest: str | None = None
    cutover_ref: str | None = None
    public_flag_open: bool | None = None
    public_cutover_honesty: bool = False

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
        if self.stop_layers is not None:
            payload["stop_layers"] = dict(self.stop_layers)
        if self.task_id is not None:
            payload["task_id"] = self.task_id
        if self.attempt_id is not None:
            payload["attempt_id"] = self.attempt_id
        if self.result_id is not None:
            payload["result_id"] = self.result_id
        if self.terminal_status is not None:
            payload["terminal_status"] = self.terminal_status
        if self.gate_id is not None:
            payload["gate_id"] = self.gate_id
        if self.grant_id is not None:
            payload["grant_id"] = self.grant_id
        if self.grant_digest is not None:
            payload["grant_digest"] = self.grant_digest
        if self.canary_ref is not None:
            payload["canary_ref"] = self.canary_ref
        if self.acceptance_id is not None:
            payload["acceptance_id"] = self.acceptance_id
        # Honesty: canary-kind receipts never authorize public write,
        # including conflict/unavailable paths that lack grant_id yet.
        if self.cutover_id is not None:
            payload["cutover_id"] = self.cutover_id
        if self.cutover_digest is not None:
            payload["cutover_digest"] = self.cutover_digest
        if self.cutover_ref is not None:
            payload["cutover_ref"] = self.cutover_ref
        if self.public_flag_open is not None:
            payload["public_flag_open"] = self.public_flag_open
        if (
            self.canary_honesty
            or self.grant_id is not None
            or self.canary_ref is not None
            or self.acceptance_id is not None
        ):
            payload["public_write_authorized"] = False
            payload["chat_write_ready"] = False
            payload["release_authorized"] = False
        if self.public_cutover_honesty or self.cutover_id is not None or self.cutover_ref is not None:
            # Rails honesty: release / Gate2 decide / V2 durable / kill_switch never flip.
            payload["release_authorized"] = False
            payload["m6_gate2_decide_authorized"] = False
            payload["v2_durable_live"] = False
            payload["kill_switch_unchanged"] = True
            if self.public_flag_open is True:
                payload["public_write_authorized"] = True
                payload["chat_write_ready"] = True
            else:
                # closed / conflict / unavailable → public write OFF
                payload["public_write_authorized"] = False
                payload["chat_write_ready"] = False
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
    stop_layers: dict[str, object] | None = None,
    task_id: str | None = None,
    attempt_id: str | None = None,
    result_id: str | None = None,
    terminal_status: str | None = None,
    gate_id: str | None = None,
    grant_id: str | None = None,
    grant_digest: str | None = None,
    canary_ref: str | None = None,
    acceptance_id: str | None = None,
    canary_honesty: bool = False,
    cutover_id: str | None = None,
    cutover_digest: str | None = None,
    cutover_ref: str | None = None,
    public_flag_open: bool | None = None,
    public_cutover_honesty: bool = False,
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
        stop_layers=stop_layers,
        task_id=task_id,
        attempt_id=attempt_id,
        result_id=result_id,
        terminal_status=terminal_status,
        gate_id=gate_id,
        grant_id=grant_id,
        grant_digest=grant_digest,
        canary_ref=canary_ref,
        acceptance_id=acceptance_id,
        canary_honesty=bool(canary_honesty),
        cutover_id=cutover_id,
        cutover_digest=cutover_digest,
        cutover_ref=cutover_ref,
        public_flag_open=public_flag_open,
        public_cutover_honesty=bool(public_cutover_honesty),
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


def submit_stop_run_request(
    settings: Settings,
    action: RequestStop,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7c: hermetic Run-scoped stop with plan §5.5 layered receipt.

    Calls the hermetic stop port (no ``import hqa``). Hermes Run layer is real;
    Attempt/job layers are ``not_applicable`` when refs are absent and
    ``unknown`` when present without an authority in M1. Overall is ``stopped``
    / ``already_terminal`` only when every artifact-producing target is known
    terminal — an unknown Attempt keeps overall ``reconciling`` even if the
    run is confirmed. Partial-stop (committed, ack lost) returns reconciling
    and heals on exact client_action_id+digest replay. No Task invention, no
    Gate, no live HTTP, no public write.
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

    try:
        run_id = strip_run_ref(action.run_ref)
    except RunStopError as exc:
        raise SubmissionSagaError("validation", exc.message) from exc

    adapter = default_run_stop_adapter()
    identity = adapter.remember_request(
        workspace_id=action.workspace.workspace_id,
        client_action_id=action.client_action_id,
        action_digest=digest,
    )
    if identity == "conflict":
        return _receipt(
            status="conflict",
            action=action,
            digest=digest,
            reason_code="idempotency_digest_conflict",
            mutation_enabled=mutation_enabled,
        )

    try:
        result = adapter.stop(run_id)
    except RunStopError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code == "transport_error":
            # PARTIAL_STOP: durable commit happened; ack lost. Layer unknown.
            layers = build_layered_stop_receipt(
                stop=None,
                hermes_run_layer="unknown",
                attempt_ref=action.attempt_ref,
                platform_job_ref=action.platform_job_ref,
                transport_unknown=True,
            )
            return _receipt(
                status="reconciling",
                action=action,
                digest=digest,
                run_id=run_id,
                reason_code=exc.code,
                mutation_enabled=mutation_enabled,
                stop_layers=layers.to_public_dict(),
            )
        if exc.code == "run_not_found":
            layers = build_layered_stop_receipt(
                stop=None,
                hermes_run_layer="unknown",
                attempt_ref=action.attempt_ref,
                platform_job_ref=action.platform_job_ref,
                transport_unknown=True,
            )
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                run_id=run_id,
                reason_code=exc.code,
                mutation_enabled=mutation_enabled,
                stop_layers=layers.to_public_dict(),
            )
        layers = build_layered_stop_receipt(
            stop=None,
            hermes_run_layer="unknown",
            attempt_ref=action.attempt_ref,
            platform_job_ref=action.platform_job_ref,
            transport_unknown=True,
        )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            run_id=run_id,
            reason_code=exc.code or "stop_unavailable",
            mutation_enabled=mutation_enabled,
            stop_layers=layers.to_public_dict(),
        )

    hermes_layer = (
        "already_terminal" if result.idempotent_replay else "confirmed"
    )
    layers = build_layered_stop_receipt(
        stop=result,
        hermes_run_layer=hermes_layer,  # type: ignore[arg-type]
        attempt_ref=action.attempt_ref,
        platform_job_ref=action.platform_job_ref,
    )
    # Map overall → ActionReceipt.status. Keep reconciling when any layer
    # is unknown so clients never paint Task stopped early.
    if layers.overall == "reconciling":
        receipt_status: ReceiptStatus = "reconciling"
    elif layers.overall in ("stopped", "already_terminal"):
        receipt_status = "accepted"
    else:
        receipt_status = "reconciling"

    # Best-effort durable audit row on the control-plane session.
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="run_stop_request",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except SubmissionSagaError as exc:
            # Stop already committed on the hermetic port. A ledger digest
            # conflict is an audit-rail problem only — do not report conflict
            # as if the stop failed (Reviewer M1 / same honesty as V7a CAS).
            if exc.code == "conflict":
                command_id = None
            else:
                command_id = None

    return _receipt(
        status=receipt_status,
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=result.run_id,
        reason_code=None if receipt_status == "accepted" else "stop_layers_reconciling",
        mutation_enabled=mutation_enabled,
        stop_layers=layers.to_public_dict(),
    )



def submit_confirm_formula_source(
    settings: Settings,
    action: ConfirmFormulaSource,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7e Gate 1: hermetic formula-source confirm CAS (not command-approval)."""
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
    authority = default_gate_surface_authority()
    try:
        decided = authority.confirm_formula_source(
            workspace_id=action.workspace.workspace_id,
            task_ref=action.task_ref,
            reviewed_source_sha256=action.reviewed_source_sha256,
            confirmation_note=action.confirmation_note,
            client_action_id=action.client_action_id,
            action_digest=digest,
        )
    except GateSurfaceAuthorityError as exc:
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
            reason_code=exc.message or "gate_surface_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_gate_decided(
            workspace_id=action.workspace.workspace_id,
            gate=decided,
        )
    except Exception:
        pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="gate1_formula_source_confirm",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except SubmissionSagaError:
            # CAS already committed; audit-rail problems must not look like Gate failure.
            command_id = None
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        mutation_enabled=mutation_enabled,
    )


def submit_review_candidate_cas(
    settings: Settings,
    action: ReviewCandidateCAS,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7e Gate 2: hermetic candidate review CAS (no-refetch)."""
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
    authority = default_gate_surface_authority()
    try:
        decided = authority.review_candidate(
            workspace_id=action.workspace.workspace_id,
            candidate_ref=action.candidate_ref,
            expected_digest=action.expected_digest,
            expected_status=action.expected_status,
            note=action.note,
            client_action_id=action.client_action_id,
            action_digest=digest,
        )
    except GateSurfaceAuthorityError as exc:
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
            reason_code=exc.message or "gate_surface_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_gate_decided(
            workspace_id=action.workspace.workspace_id,
            gate=decided,
        )
    except Exception:
        pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="gate2_candidate_review",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except SubmissionSagaError:
            # CAS already committed; audit-rail problems must not look like Gate failure.
            command_id = None
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        mutation_enabled=mutation_enabled,
    )


def submit_prepare_promotion_review(
    settings: Settings,
    action: PreparePromotionReview,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7e Gate 3: hermetic prepare only — never performs a Git commit."""
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
    authority = default_gate_surface_authority()
    try:
        decided = authority.prepare_promotion_review(
            workspace_id=action.workspace.workspace_id,
            candidate_ref=action.candidate_ref,
            expected_digest=action.expected_digest,
            final_backtest_receipt_ref=action.final_backtest_receipt_ref,
            base_commit=action.base_commit,
            client_action_id=action.client_action_id,
            action_digest=digest,
        )
    except GateSurfaceAuthorityError as exc:
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
            reason_code=exc.message or "gate_surface_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_gate_decided(
            workspace_id=action.workspace.workspace_id,
            gate=decided,
        )
    except Exception:
        pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="gate3_promotion_review_prepare",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except SubmissionSagaError:
            # CAS already committed; audit-rail problems must not look like Gate failure.
            command_id = None
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        mutation_enabled=mutation_enabled,
    )



def submit_bind_options_vertical_a(
    settings: Settings,
    action: BindOptionsVerticalA,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7g-A: Vertical A options research bind (hermetic + live Futu RO).

    Hermetic fixture or authorized live_futu_ro with auth envelope.
    Zero orders/account mutation. Not StartResearch. Not public write.
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
    authority = default_vertical_binding_authority()
    try:
        outcome = authority.bind_options_vertical_a(
            workspace_id=action.workspace.workspace_id,
            client_action_id=action.client_action_id,
            action_digest=digest,
            ticker=action.ticker,
            goal_note=action.goal_note,
            expiry=action.expiry,
            strike=action.strike,
            bid=action.bid,
            ask=action.ask,
            delta=action.delta,
            iv=action.iv,
            apr=action.apr,
            include_provider_evidence=action.include_provider_evidence,
            provider_mode=action.provider_mode,
            auth_envelope=action.auth_envelope,
            settings=settings,
        )
    except VerticalBindingAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code in {
            "auth_envelope_missing",
            "auth_envelope_invalid",
            "auth_envelope_denied",
            "auth_envelope_budget_exceeded",
        }:
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                reason_code=exc.code,
                mutation_enabled=mutation_enabled,
            )
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
            reason_code=exc.message or "vertical_binding_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_result_raised(
            workspace_id=action.workspace.workspace_id,
            result=outcome.result,
        )
    except Exception:
        pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="vertical_options_a_bind",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except SubmissionSagaError:
            # Bind already committed; audit-rail problems must not look like bind failure.
            command_id = None
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=outcome.run.run_id,
        task_id=outcome.task.task_id,
        attempt_id=outcome.attempt.attempt_id,
        result_id=outcome.result.result_id,
        terminal_status=outcome.terminal,
        mutation_enabled=mutation_enabled,
    )


def submit_bind_factor_vertical_b(
    settings: Settings,
    action: BindFactorVerticalB,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7g-B-M1: Vertical B factor research bind (hermetic only).

    Never StartResearch/Confirm/Gate/backtest/Git. Zero orders. Not public write.
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
    authority = default_vertical_binding_authority()
    try:
        outcome = authority.bind_factor_vertical_b(
            workspace_id=action.workspace.workspace_id,
            client_action_id=action.client_action_id,
            action_digest=digest,
            goal_note=action.goal_note,
            paper_ref=action.paper_ref,
            paper_digest=action.paper_digest,
            factor_name=action.factor_name,
            formula_sketch=action.formula_sketch,
            universe_note=action.universe_note,
            include_provider_evidence=action.include_provider_evidence,
        )
    except VerticalBindingAuthorityError as exc:
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
            reason_code=exc.message or "vertical_binding_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_result_raised(
            workspace_id=action.workspace.workspace_id,
            result=outcome.result,
        )
    except Exception:
        pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="vertical_factor_b_bind",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except SubmissionSagaError:
            command_id = None
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=outcome.run.run_id,
        task_id=outcome.task.task_id,
        attempt_id=outcome.attempt.attempt_id,
        result_id=outcome.result.result_id,
        terminal_status=outcome.terminal,
        mutation_enabled=mutation_enabled,
    )


def submit_confirm_factor_vertical_b_plan(
    settings: Settings,
    action: ConfirmFactorVerticalBPlan,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7g-B-M2: hermetic factor_b plan-confirm cascade notch.

    Never StartResearch / global ConfirmResearchPlan / Gate / backtest / Git.
    Zero orders. Not public write. M1 bind acceptance is not standing auth.
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
    authority = default_vertical_binding_authority()
    try:
        outcome = authority.confirm_factor_vertical_b_plan(
            workspace_id=action.workspace.workspace_id,
            client_action_id=action.client_action_id,
            action_digest=digest,
            task_ref=action.task_ref,
            expected_bind_digest=action.expected_bind_digest,
            plan_version=action.plan_version,
            plan_digest=action.plan_digest,
            confirmation_note=action.confirmation_note,
        )
    except VerticalBindingAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code in {
            "factor_b_task_not_found",
            "factor_b_task_wrong_vertical",
            "factor_b_bind_digest_mismatch",
            "factor_b_bind_not_confirmable",
            "factor_b_plan_digest_mismatch",
        }:
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                reason_code=exc.code,
                mutation_enabled=mutation_enabled,
            )
        if exc.code in {"conflict", "cascade_already_plan_confirmed"}:
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.code if exc.code != "conflict" else exc.message,
                mutation_enabled=mutation_enabled,
            )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message or "vertical_binding_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_result_raised(
            workspace_id=action.workspace.workspace_id,
            result=outcome.result,
        )
    except Exception:
        pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="vertical_factor_b_plan_confirm",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=outcome.run.run_id,
        task_id=outcome.task.task_id,
        attempt_id=outcome.attempt.attempt_id,
        result_id=outcome.result.result_id,
        terminal_status=outcome.terminal,
        mutation_enabled=mutation_enabled,
    )



def submit_seed_factor_vertical_b_gate1(
    settings: Settings,
    action: SeedFactorVerticalBGate1,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7g-B-M3: hermetic factor_b Gate1 seed cascade notch.

    Never decides Gate1 / lifts gate_cascade_locked / StartResearch /
    global ConfirmResearchPlan / Gate2-3 / backtest / Git. Zero orders.
    M2 plan_confirm acceptance is not standing auth for M3.
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
    authority = default_vertical_binding_authority()
    try:
        outcome = authority.seed_factor_vertical_b_gate1(
            workspace_id=action.workspace.workspace_id,
            client_action_id=action.client_action_id,
            action_digest=digest,
            task_ref=action.task_ref,
            expected_bind_digest=action.expected_bind_digest,
            expected_plan_digest=action.expected_plan_digest,
            reviewed_source_sha256=action.reviewed_source_sha256,
            seed_note=action.seed_note,
        )
    except VerticalBindingAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code in {
            "factor_b_task_not_found",
            "factor_b_task_wrong_vertical",
            "factor_b_bind_digest_mismatch",
            "factor_b_gate1_not_seedable",
            "factor_b_plan_digest_mismatch",
            "factor_b_formula_source_unavailable",
            "factor_b_formula_source_digest_mismatch",
        }:
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                reason_code=exc.code,
                mutation_enabled=mutation_enabled,
            )
        if exc.code in {"conflict", "cascade_already_gate1_seeded"}:
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.code if exc.code != "conflict" else exc.message,
                mutation_enabled=mutation_enabled,
            )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message or "vertical_binding_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_result_raised(
            workspace_id=action.workspace.workspace_id,
            result=outcome.result,
        )
    except Exception:
        pass
    if outcome.gate_id is not None:
        try:
            gauth = default_gate_surface_authority()
            gate_row = gauth.get(action.workspace.workspace_id, outcome.gate_id)
            if gate_row is not None:
                note_gate_raised(
                    workspace_id=action.workspace.workspace_id,
                    gate=gate_row,
                )
        except Exception:
            pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="vertical_factor_b_gate1_seed",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=outcome.run.run_id,
        task_id=outcome.task.task_id,
        attempt_id=outcome.attempt.attempt_id,
        result_id=outcome.result.result_id,
        terminal_status=outcome.terminal,
        mutation_enabled=mutation_enabled,
        gate_id=outcome.gate_id,
    )


def submit_confirm_factor_vertical_b_gate1(
    settings: Settings,
    action: ConfirmFactorVerticalBGate1,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7g-B-M4: hermetic factor_b Gate1 decide→cascade coupler.

    Dual-path: confirm pending Gate1 when needed, or cascade-only after V7e.
    Never lifts gate_cascade_locked / auto Gate2 / StartResearch /
    global ConfirmResearchPlan / Gate2-3 cascade / backtest / Git. Zero orders.
    M3 seed acceptance is not standing auth for M4.
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
    authority = default_vertical_binding_authority()
    try:
        outcome = authority.confirm_factor_vertical_b_gate1(
            workspace_id=action.workspace.workspace_id,
            client_action_id=action.client_action_id,
            action_digest=digest,
            task_ref=action.task_ref,
            expected_bind_digest=action.expected_bind_digest,
            expected_plan_digest=action.expected_plan_digest,
            expected_gate1_id=action.expected_gate1_id,
            reviewed_source_sha256=action.reviewed_source_sha256,
            confirmation_note=action.confirmation_note,
        )
    except VerticalBindingAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code in {
            "factor_b_task_not_found",
            "factor_b_task_wrong_vertical",
            "factor_b_bind_digest_mismatch",
            "factor_b_gate1_not_confirmable",
            "factor_b_plan_digest_mismatch",
            "factor_b_gate1_id_mismatch",
            "factor_b_formula_source_unavailable",
            "factor_b_formula_source_digest_mismatch",
        }:
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                reason_code=exc.code,
                mutation_enabled=mutation_enabled,
            )
        if exc.code in {"conflict", "cascade_already_gate1_confirmed"}:
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.code if exc.code != "conflict" else exc.message,
                mutation_enabled=mutation_enabled,
            )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message or "vertical_binding_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_result_raised(
            workspace_id=action.workspace.workspace_id,
            result=outcome.result,
        )
    except Exception:
        pass
    # note_gate_decided only when this act confirmed the surface (decision_action
    # matches). CASCADE-ONLY after V7e leaves V7e's decision facts untouched.
    if outcome.gate_id is not None:
        try:
            gauth = default_gate_surface_authority()
            gate_row = gauth.get(action.workspace.workspace_id, outcome.gate_id)
            if (
                gate_row is not None
                and gate_row.status == "confirmed"
                and gate_row.decision_action_id == action.client_action_id
                and gate_row.decision_action_digest == digest
            ):
                note_gate_decided(
                    workspace_id=action.workspace.workspace_id,
                    gate=gate_row,
                )
        except Exception:
            pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="vertical_factor_b_gate1_confirm",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=outcome.run.run_id,
        task_id=outcome.task.task_id,
        attempt_id=outcome.attempt.attempt_id,
        result_id=outcome.result.result_id,
        terminal_status=outcome.terminal,
        mutation_enabled=mutation_enabled,
        gate_id=outcome.gate_id,
    )


def submit_seed_factor_vertical_b_gate2(
    settings: Settings,
    action: SeedFactorVerticalBGate2,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V7g-B-M5: hermetic factor_b Gate2 seed cascade notch.

    Never decides Gate2 / lifts gate_cascade_locked / StartResearch /
    global ConfirmResearchPlan / Gate3 / backtest / Git. Zero orders.
    M4 gate1_confirm acceptance is not standing auth for M5.
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
    authority = default_vertical_binding_authority()
    try:
        outcome = authority.seed_factor_vertical_b_gate2(
            workspace_id=action.workspace.workspace_id,
            client_action_id=action.client_action_id,
            action_digest=digest,
            task_ref=action.task_ref,
            expected_bind_digest=action.expected_bind_digest,
            expected_plan_digest=action.expected_plan_digest,
            expected_gate1_id=action.expected_gate1_id,
            expected_gate1_confirm_digest=action.expected_gate1_confirm_digest,
            expected_candidate_digest=action.expected_candidate_digest,
            seed_note=action.seed_note,
        )
    except VerticalBindingAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code in {
            "factor_b_task_not_found",
            "factor_b_task_wrong_vertical",
            "factor_b_bind_digest_mismatch",
            "factor_b_gate2_not_seedable",
            "factor_b_plan_digest_mismatch",
            "factor_b_gate1_id_mismatch",
            "factor_b_gate1_confirm_digest_mismatch",
            "factor_b_formula_source_unavailable",
            "factor_b_candidate_digest_mismatch",
        }:
            return _receipt(
                status="unavailable",
                action=action,
                digest=digest,
                reason_code=exc.code,
                mutation_enabled=mutation_enabled,
            )
        if exc.code in {"conflict", "cascade_already_gate2_seeded"}:
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.code if exc.code != "conflict" else exc.message,
                mutation_enabled=mutation_enabled,
            )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message or "vertical_binding_authority_unavailable",
            mutation_enabled=mutation_enabled,
        )
    try:
        note_result_raised(
            workspace_id=action.workspace.workspace_id,
            result=outcome.result,
        )
    except Exception:
        pass
    if outcome.gate_id is not None:
        try:
            gauth = default_gate_surface_authority()
            gate_row = gauth.get(action.workspace.workspace_id, outcome.gate_id)
            if gate_row is not None:
                note_gate_raised(
                    workspace_id=action.workspace.workspace_id,
                    gate=gate_row,
                )
        except Exception:
            pass
    command_id: str | None = None
    if _ensure_ready(settings):
        control_session = control_plane_session_id(action.workspace.workspace_id)
        try:
            cmd = _create_idempotent_command(
                settings,
                platform_session_id=control_session,
                client_request_id=action.client_action_id,
                kind="vertical_factor_b_gate2_seed",
                action_digest=digest,
                payload_ref=action_payload_ref_for_digest(digest),
                provider_policy_digest=None,
            )
            command_id = str(cmd.command.command_id)
        except Exception:
            command_id = None
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        command_id=command_id,
        run_id=outcome.run.run_id,
        task_id=outcome.task.task_id,
        attempt_id=outcome.attempt.attempt_id,
        result_id=outcome.result.result_id,
        terminal_status=outcome.terminal,
        mutation_enabled=mutation_enabled,
        gate_id=outcome.gate_id,
    )



def submit_issue_canary_grant(
    settings: Settings,
    action: IssueCanaryGrant,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V8-M5: hermetic canary grant issue (owner-only, short TTL, build digest).

    Never opens public write / chat_write_ready / kill_switch / M6 / V2 durable.
    """
    _ = settings  # hermetic in-process; no PG required
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
    _require_root_actor(actor_owner_user_id)
    authority = default_canary_grant_authority()
    try:
        grant = authority.issue(
            workspace_id=action.workspace.workspace_id,
            build_digest=action.build_digest,
            route=action.route,
            ttl_seconds=action.ttl_seconds,
            grant_note=action.grant_note,
            client_action_id=action.client_action_id,
            action_digest=digest,
        )
    except CanaryGrantAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.message,
                mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message,
            mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
    note_canary_issued(
        workspace_id=action.workspace.workspace_id, grant=grant
    )
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        mutation_enabled=mutation_enabled,
        grant_id=grant.grant_id,
        grant_digest=grant.grant_digest,
        canary_ref=grant.canary_ref,
        terminal_status=grant.status,
            canary_honesty=True,
        )


def submit_revoke_canary_grant(
    settings: Settings,
    action: RevokeCanaryGrant,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V8-M5: revoke active canary grant by exact grant_digest CAS."""
    _ = settings
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
    _require_root_actor(actor_owner_user_id)
    authority = default_canary_grant_authority()
    try:
        grant = authority.revoke(
            workspace_id=action.workspace.workspace_id,
            canary_ref=action.canary_ref,
            expected_grant_digest=action.expected_grant_digest,
            reason=action.reason,
            client_action_id=action.client_action_id,
            action_digest=digest,
            terminal_status="revoked",
        )
    except CanaryGrantAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.message,
                mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message,
            mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
    note_canary_revoked(
        workspace_id=action.workspace.workspace_id, grant=grant
    )
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        mutation_enabled=mutation_enabled,
        grant_id=grant.grant_id,
        grant_digest=grant.grant_digest,
        canary_ref=grant.canary_ref,
        terminal_status=grant.status,
            canary_honesty=True,
        )


def submit_accept_canary_dual_vertical(
    settings: Settings,
    action: AcceptCanaryDualVertical,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V8-M5: dual-vertical owner accept under canary; consumes grant.

    Public write / release_authorized stay false on every path.
    """
    _ = settings
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
    _require_root_actor(actor_owner_user_id)

    def _strip(ref: str, prefix: str) -> str:
        return ref[len(prefix) :]

    authority = default_canary_grant_authority()
    try:
        grant, acceptance = authority.accept_dual_vertical(
            workspace_id=action.workspace.workspace_id,
            canary_ref=action.canary_ref,
            expected_build_digest=action.expected_build_digest,
            expected_grant_digest=action.expected_grant_digest,
            options_a_task_id=_strip(action.options_a_task_ref, "task:"),
            options_a_result_id=_strip(action.options_a_result_ref, "result:"),
            factor_b_task_id=_strip(action.factor_b_task_ref, "task:"),
            factor_b_result_id=_strip(action.factor_b_result_ref, "result:"),
            acceptance_note=action.acceptance_note,
            client_action_id=action.client_action_id,
            action_digest=digest,
        )
    except CanaryGrantAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.message,
                mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message,
            mutation_enabled=mutation_enabled,
            canary_honesty=True,
        )
    note_canary_accepted(
        workspace_id=action.workspace.workspace_id,
        grant=grant,
        acceptance=acceptance,
    )
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        mutation_enabled=mutation_enabled,
        grant_id=grant.grant_id,
        grant_digest=grant.grant_digest,
        canary_ref=grant.canary_ref,
        acceptance_id=acceptance.acceptance_id,
        terminal_status=grant.status,
        task_id=acceptance.options_a_task_id,
        result_id=acceptance.options_a_result_id,
            canary_honesty=True,
        )



def submit_open_public_cutover(
    settings: Settings,
    action: OpenPublicCutover,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V8-M6 G7: open single public flag after G6 dual-vertical acceptance.

    Never opens kill_switch / Gate2 decide / V2 durable / release_authorized.
    """
    _ = settings  # hermetic in-process; no PG required
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
            public_cutover_honesty=True,
            public_flag_open=False,
        )
    _require_root_actor(actor_owner_user_id)

    # Prerequisite: G6 dual-vertical acceptance must exist in canary authority.
    canary_auth = default_canary_grant_authority()
    acceptances = canary_auth.list_acceptances(action.workspace.workspace_id)
    acceptance_exists = any(
        a.acceptance_id == action.acceptance_id for a in acceptances
    )

    authority = default_public_cutover_authority()
    try:
        cutover = authority.open(
            workspace_id=action.workspace.workspace_id,
            build_digest=action.build_digest,
            route=action.route,
            acceptance_id=action.acceptance_id,
            open_note=action.open_note,
            client_action_id=action.client_action_id,
            action_digest=digest,
            acceptance_exists=acceptance_exists,
        )
    except PublicCutoverAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.message,
                mutation_enabled=mutation_enabled,
                public_cutover_honesty=True,
                public_flag_open=False,
            )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message if exc.message else exc.code,
            mutation_enabled=mutation_enabled,
            public_cutover_honesty=True,
            public_flag_open=False,
        )

    note_public_cutover_opened(
        workspace_id=action.workspace.workspace_id, cutover=cutover
    )
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        mutation_enabled=mutation_enabled,
        cutover_id=cutover.cutover_id,
        cutover_digest=cutover.cutover_digest,
        cutover_ref=cutover.cutover_ref,
        public_flag_open=True,
        public_cutover_honesty=True,
        acceptance_id=cutover.acceptance_id,
    )


def submit_close_public_cutover(
    settings: Settings,
    action: ClosePublicCutover,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
) -> ActionReceipt:
    """V8-M6 G8: one-click public flag rollback. Facts retained."""
    _ = settings
    digest = canonical_action_digest(action)
    if not mutation_enabled:
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code="authenticated_mutation_bff_unavailable",
            mutation_enabled=mutation_enabled,
            public_cutover_honesty=True,
            public_flag_open=False,
        )
    _require_root_actor(actor_owner_user_id)

    authority = default_public_cutover_authority()
    try:
        cutover = authority.close(
            workspace_id=action.workspace.workspace_id,
            cutover_ref=action.cutover_ref,
            expected_cutover_digest=action.expected_cutover_digest,
            reason=action.reason,
            client_action_id=action.client_action_id,
            action_digest=digest,
        )
    except PublicCutoverAuthorityError as exc:
        if exc.code == "validation":
            raise SubmissionSagaError("validation", exc.message) from exc
        if exc.code == "conflict":
            return _receipt(
                status="conflict",
                action=action,
                digest=digest,
                reason_code=exc.message,
                mutation_enabled=mutation_enabled,
                public_cutover_honesty=True,
                public_flag_open=False,
            )
        return _receipt(
            status="unavailable",
            action=action,
            digest=digest,
            reason_code=exc.message if exc.message else exc.code,
            mutation_enabled=mutation_enabled,
            public_cutover_honesty=True,
            public_flag_open=False,
        )

    note_public_cutover_closed(
        workspace_id=action.workspace.workspace_id, cutover=cutover
    )
    return _receipt(
        status="accepted",
        action=action,
        digest=digest,
        mutation_enabled=mutation_enabled,
        cutover_id=cutover.cutover_id,
        cutover_digest=cutover.cutover_digest,
        cutover_ref=cutover.cutover_ref,
        public_flag_open=False,
        public_cutover_honesty=True,
        acceptance_id=cutover.acceptance_id,
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
    if type(parsed) is RequestStop:
        return submit_stop_run_request(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is ConfirmFormulaSource:
        return submit_confirm_formula_source(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is ReviewCandidateCAS:
        return submit_review_candidate_cas(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is PreparePromotionReview:
        return submit_prepare_promotion_review(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is BindOptionsVerticalA:
        return submit_bind_options_vertical_a(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is BindFactorVerticalB:
        return submit_bind_factor_vertical_b(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is ConfirmFactorVerticalBPlan:
        return submit_confirm_factor_vertical_b_plan(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is SeedFactorVerticalBGate1:
        return submit_seed_factor_vertical_b_gate1(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is ConfirmFactorVerticalBGate1:
        return submit_confirm_factor_vertical_b_gate1(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is SeedFactorVerticalBGate2:
        return submit_seed_factor_vertical_b_gate2(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is IssueCanaryGrant:
        return submit_issue_canary_grant(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is RevokeCanaryGrant:
        return submit_revoke_canary_grant(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is OpenPublicCutover:
        return submit_open_public_cutover(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is ClosePublicCutover:
        return submit_close_public_cutover(
            settings,
            parsed,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    if type(parsed) is AcceptCanaryDualVertical:
        return submit_accept_canary_dual_vertical(
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
    "submit_bind_factor_vertical_b",
    "submit_bind_options_vertical_a",
    "submit_confirm_factor_vertical_b_plan",
    "submit_seed_factor_vertical_b_gate1",
    "submit_confirm_factor_vertical_b_gate1",
    "submit_seed_factor_vertical_b_gate2",
    "submit_issue_canary_grant",
    "submit_revoke_canary_grant",
    "submit_accept_canary_dual_vertical",
    "submit_open_public_cutover",
    "submit_close_public_cutover",
    "submit_conversation_turn",
    "submit_create_managed_session",
    "submit_decide_hermes_command_approval",
    "submit_fork_into_managed_session",
    "submit_stop_run_request",
]
