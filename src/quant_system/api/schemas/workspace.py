"""Public response contracts for the Agent v0.2 workspace transport."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_DIGEST = r"^[0-9a-f]{64}$"


class _WorkspaceSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceRefResponse(_WorkspaceSchema):
    workspace_id: str = Field(min_length=1, max_length=200)


class DualVerticalAcceptanceResponse(_WorkspaceSchema):
    acceptance_id: str
    grant_id: str
    grant_digest: str = Field(pattern=_DIGEST)
    build_digest: str = Field(pattern=_DIGEST)
    options_a_task_id: str
    options_a_result_id: str
    factor_b_task_id: str
    factor_b_result_id: str
    acceptance_note: str
    accepted_at: str
    kind: Literal["v8.canary.dual_vertical_acceptance"]
    public_write_authorized: Literal[False]
    chat_write_ready: Literal[False]
    release_authorized: Literal[False]


class CanaryGrantResponse(_WorkspaceSchema):
    grant_id: str
    canary_ref: str
    build_digest: str = Field(pattern=_DIGEST)
    route: Literal["/hermes"]
    grant_digest: str = Field(pattern=_DIGEST)
    issued_at: str
    expires_at: str
    status: Literal["active", "revoked", "expired", "consumed"]
    kind: Literal["v8.canary.grant"]
    public_write_authorized: Literal[False]
    chat_write_ready: Literal[False]
    release_authorized: Literal[False]
    grant_note: str | None = None
    revoked_at: str | None = None
    revoke_reason: str | None = None
    acceptance: DualVerticalAcceptanceResponse | None = None


class PublicCutoverResponse(_WorkspaceSchema):
    cutover_id: str
    cutover_ref: str
    build_digest: str = Field(pattern=_DIGEST)
    route: Literal["/hermes"]
    cutover_digest: str = Field(pattern=_DIGEST)
    acceptance_id: str
    opened_at: str
    status: Literal["open", "closed"]
    public_flag_open: bool
    kind: Literal["v8.public.cutover"]
    release_authorized: Literal[False]
    m6_gate2_decide_authorized: Literal[False]
    v2_durable_live: Literal[False]
    kill_switch_unchanged: Literal[True]
    public_write_authorized: bool
    chat_write_ready: bool
    open_note: str | None = None
    closed_at: str | None = None
    close_reason: str | None = None


class GateProjectionResponse(_WorkspaceSchema):
    gate_id: str
    attempt_ref: str | None = Field(
        default=None,
        pattern=r"^attempt:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
    )
    command_id: str | None = Field(
        default=None,
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        ),
    )
    command_ref: str | None = Field(
        default=None,
        pattern=(
            r"^command:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        ),
    )
    hermes_session_id: str | None = Field(default=None, min_length=1, max_length=255)
    hermes_run_id: str | None = Field(default=None, min_length=1, max_length=255)
    hqa_run_ref: str | None = Field(
        default=None,
        pattern=r"^run:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
    )
    hqa_gate_ref: str | None = Field(
        default=None,
        pattern=r"^gate:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
    )
    managed_session_ref: str | None = Field(
        default=None,
        pattern=r"^session:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
    )
    gate_kind: Literal["gate1", "gate2", "gate3"]
    kind: Literal[
        "gate1.formula_source",
        "gate2.candidate",
        "gate3.promotion_review",
    ]
    status: Literal[
        "pending",
        "confirmed",
        "reviewed",
        "prepared",
        "completed",
        "outcome_unknown",
        "rejected",
        "expired",
    ]
    expected_status: str
    task_id: str | None = None
    task_ref: str | None = None
    reviewed_source_sha256: str | None = None
    candidate_id: str | None = None
    candidate_ref: str | None = None
    expected_digest: str | None = None
    final_backtest_receipt_id: str | None = None
    final_backtest_receipt_ref: str | None = None
    base_commit: str | None = None
    hqa_receipt_ref: str | None = Field(default=None, max_length=200)
    hqa_receipt_digest: str | None = Field(default=None, pattern=_DIGEST)
    promotion_id: str | None = Field(
        default=None,
        pattern=r"^promo-[0-9a-f]{32}(?:-r(?:[2-9]|[1-9][0-9]+))?$",
    )
    worktree: str | None = Field(default=None, max_length=4096)
    patch: str | None = Field(default=None, max_length=4096)
    manifest: str | None = Field(default=None, max_length=4096)
    human_git_commit_required: bool | None = None
    auto_commit: Literal[False] | None = None
    reviewed_commit: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )
    task_version: int | None = Field(default=None, ge=1, le=2**63 - 1)
    task_status: Literal["completed"] | None = None
    task_terminal_outcome: Literal["completed"] | None = None
    attempt_status: Literal["completed"] | None = None
    attempt_terminal_outcome: Literal["completed"] | None = None
    domain_gate_outcome: Literal["passed"] | None = None
    provider_evidence_ref: str | None = Field(
        default=None,
        pattern=r"^provider-evidence:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
    )
    workflow_audit_status: Literal["consistent"] | None = None
    workflow_audit_ref: str | None = Field(
        default=None,
        pattern=r"^workflow-audit:[0-9a-f]{64}$",
    )
    workflow_audit_digest: str | None = Field(default=None, pattern=_DIGEST)
    hqa_completion_receipt_ref: str | None = Field(
        default=None,
        pattern=r"^hqa-paper-completion:[0-9a-f]{32}$",
    )
    hqa_completion_receipt_digest: str | None = Field(
        default=None,
        pattern=_DIGEST,
    )
    expires_at: str | None = None
    note: str | None = None
    decided_at: str | None = None


class ManagedSessionProjectionResponse(_WorkspaceSchema):
    platform_session_id: str = Field(min_length=1, max_length=200)
    session_ref: str = Field(min_length=9, max_length=220)
    hermes_session_id: str = Field(min_length=1, max_length=255)
    provision_state: Literal[
        "pending",
        "leased",
        "retryable",
        "ready",
        "failed",
    ]
    web_writable: bool
    attempt_count: int = Field(ge=0)
    lease_until: str | None = Field(default=None, max_length=64)
    retry_at: str | None = Field(default=None, max_length=64)
    last_error_code: str | None = Field(default=None, max_length=200)
    provisioned_at: str | None = Field(default=None, max_length=64)
    parent_session_ref: str | None = Field(default=None, max_length=220)
    fork_point: str | None = Field(default=None, max_length=200)
    created_at: str | None = Field(default=None, max_length=64)
    updated_at: str | None = Field(default=None, max_length=64)


class OptionsRequestResponse(_WorkspaceSchema):
    action_digest: str = Field(pattern=_DIGEST)
    admission_digest: str = Field(pattern=_DIGEST)
    admission_id: str = Field(min_length=1, max_length=200)
    client_action_id: str = Field(min_length=1, max_length=200)
    domain_request_id: str = Field(min_length=1, max_length=200)
    domain_request_ref: str = Field(pattern=r"^options-request:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
    expiry: str = Field(min_length=1, max_length=200)
    recovery_action: (
        Literal[
            "follow_workspace",
            "operator_reconcile_no_provider_replay",
        ]
        | None
    )
    state: Literal["awaiting_run", "completed", "outcome_unknown"]
    strike: float = Field(gt=0, allow_inf_nan=False)
    ticker: str = Field(min_length=1, max_length=32)
    created_at: str = Field(min_length=1, max_length=64)
    claim_id: str | None = Field(default=None, min_length=1, max_length=200)
    session_ref: str | None = Field(
        default=None,
        pattern=r"^session:[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$",
    )
    run_ref: str | None = Field(
        default=None,
        pattern=r"^run:[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$",
    )
    result_id: str | None = Field(default=None, min_length=1, max_length=200)


class WorkspaceSnapshotResponse(_WorkspaceSchema):
    workspace: WorkspaceRefResponse
    owner_user_id: str = Field(min_length=1, max_length=64)
    snapshot_workspace_cursor: int = Field(ge=0, le=2**63 - 1)
    sessions: list[str]
    managed_sessions: list[ManagedSessionProjectionResponse]
    tasks: list[str]
    attempts: list[str]
    commands: list[dict[str, Any]]
    runs: list[str]
    results: list[dict[str, Any]]
    options_requests: list[OptionsRequestResponse] = Field(default_factory=list)
    approvals: list[dict[str, Any]]
    gates: list[GateProjectionResponse]
    canary_grants: list[CanaryGrantResponse]
    public_cutovers: list[PublicCutoverResponse]
    authority_health: dict[str, str]
    mutation_enabled: bool
    observed_at: str = Field(min_length=1, max_length=64)


class WorkspaceFollowResponse(_WorkspaceSchema):
    events: list[dict[str, Any]]
    after_cursor: int | None = Field(default=None, ge=0, le=2**63 - 1)
    next_cursor: int | None = Field(default=None, ge=0, le=2**63 - 1)
    resync_required: bool
    recovery_action: str | None = None
    mutation_enabled: bool
    approvals: list[dict[str, Any]] | None = None
    gates: list[GateProjectionResponse] | None = None
    canary_grants: list[CanaryGrantResponse] | None = None
    public_cutovers: list[PublicCutoverResponse] | None = None
    results: list[dict[str, Any]] | None = None
    options_requests: list[OptionsRequestResponse] | None = None
    tasks: list[str] | None = None
    attempts: list[str] | None = None
    runs: list[str] | None = None
    authority_health: dict[str, str] | None = None


class WorkspaceAuthoritiesResponse(_WorkspaceSchema):
    command_ledger_schema_ready: bool
    command_ledger_schema_version: int | None
    session_registry_schema_ready: bool
    session_registry_schema_version: int | None
    workflow_binding_schema_ready: bool
    workflow_binding_schema_version: int | None
    schema_ready: bool
    ready: bool
    research_binding_schema_ready: bool
    research_binding_ready: bool
    runtime_security_ready: bool
    write_authority_ready: bool
    dark_dispatch_schema_ready: bool
    dark_dispatch_ready: bool
    connector_liveness_ready: bool
    connector_liveness_reason: str
    connector_worker_id: str | None
    connector_mode: str | None
    connector_heartbeat_age_seconds: float | None
    admission_mode: Literal["closed", "candidate", "release"]
    release_authorized: bool
    release_blockers: list[str]
    final_release_blockers: list[str]
    release_stamp_id: str | None
    public_cutover_id: str | None
    candidate_admission_id: str | None
    candidate_admission_digest: str | None
    candidate_chat_write_ready: bool
    release_event_cursor: int = Field(ge=0, le=2**63 - 1)
    mutation_enabled: bool
    local_chat_write_ready: bool
    composer_write_ready: bool
    public_write_authorized: bool
    public_chat_write_ready: bool
    chat_write_ready: bool
    platform_delivery_blockers: list[str]
    platform_delivery_blocker_count: int = Field(ge=0)
    composer_open: bool


class WorkspaceActionReceiptResponse(_WorkspaceSchema):
    status: Literal[
        "accepted",
        "reconciling",
        "conflict",
        "unavailable",
        "outcome_unknown",
    ]
    client_action_id: str = Field(min_length=1, max_length=200)
    action_digest: str = Field(pattern=_DIGEST)
    workspace: WorkspaceRefResponse
    recovery_action: str | None = None
    mutation_enabled: bool
    command_id: str | None = None
    run_id: str | None = None
    platform_session_id: str | None = None
    session_ref: str | None = None
    hermes_session_id: str | None = None
    reason_code: str | None = None
    stop_layers: dict[str, Any] | None = None
    task_id: str | None = None
    attempt_id: str | None = None
    result_id: str | None = None
    terminal_status: str | None = None
    domain_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    domain_request_ref: str | None = Field(
        default=None,
        pattern=r"^options-request:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
    )
    domain_request_status: (
        Literal[
            "awaiting_run",
            "completed",
            "outcome_unknown",
        ]
        | None
    ) = None
    gate_id: str | None = None
    grant_id: str | None = None
    grant_digest: str | None = Field(default=None, pattern=_DIGEST)
    canary_ref: str | None = None
    acceptance_id: str | None = None
    cutover_id: str | None = None
    cutover_digest: str | None = Field(default=None, pattern=_DIGEST)
    cutover_ref: str | None = None
    public_flag_open: bool | None = None
    public_write_authorized: bool | None = None
    chat_write_ready: bool | None = None
    release_authorized: Literal[False] | None = None
    m6_gate2_decide_authorized: Literal[False] | None = None
    v2_durable_live: Literal[False] | None = None
    kill_switch_unchanged: Literal[True] | None = None


class CompositeTurnReceiptResponse(WorkspaceActionReceiptResponse):
    payload_ref: str = Field(min_length=1)
    payload_digest: str = Field(pattern=_DIGEST)
    kind: Literal["conversation.turn"]


__all__ = [
    "CanaryGrantResponse",
    "CompositeTurnReceiptResponse",
    "DualVerticalAcceptanceResponse",
    "GateProjectionResponse",
    "OptionsRequestResponse",
    "PublicCutoverResponse",
    "WorkspaceActionReceiptResponse",
    "WorkspaceAuthoritiesResponse",
    "WorkspaceFollowResponse",
    "WorkspaceRefResponse",
    "WorkspaceSnapshotResponse",
]
