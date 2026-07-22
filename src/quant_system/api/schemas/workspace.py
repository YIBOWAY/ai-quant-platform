"""Public response contracts for the AgentWorkspace HTTP transport."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _WorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceRefResponse(_WorkspaceResponse):
    workspace_id: str = Field(min_length=1, max_length=200)


class WorkspaceSnapshotResponse(_WorkspaceResponse):
    workspace: WorkspaceRefResponse
    owner_user_id: str = Field(min_length=1, max_length=64)
    snapshot_workspace_cursor: int = Field(ge=0, le=2**63 - 1)
    sessions: list[str]
    tasks: list[str]
    attempts: list[str]
    commands: list[dict[str, Any]]
    runs: list[str]
    results: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    authority_health: dict[str, str]
    mutation_enabled: bool
    observed_at: str = Field(min_length=1, max_length=64)


class WorkspaceFollowResponse(_WorkspaceResponse):
    events: list[dict[str, Any]]
    after_cursor: int | None = Field(default=None, ge=0, le=2**63 - 1)
    next_cursor: int | None = Field(default=None, ge=0, le=2**63 - 1)
    resync_required: bool
    recovery_action: str | None = None
    mutation_enabled: bool
    approvals: list[dict[str, Any]] | None = None
    gates: list[dict[str, Any]] | None = None
    results: list[dict[str, Any]] | None = None
    tasks: list[str] | None = None
    attempts: list[str] | None = None
    runs: list[str] | None = None
    authority_health: dict[str, str] | None = None


class WorkspaceAuthoritiesResponse(_WorkspaceResponse):
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
    mutation_enabled: bool
    local_chat_write_ready: bool
    composer_write_ready: bool
    public_chat_write_ready: bool
    chat_write_ready: bool
    platform_delivery_blockers: list[str]
    platform_delivery_blocker_count: int = Field(ge=0)
    composer_open: bool


class WorkspaceActionReceiptResponse(_WorkspaceResponse):
    status: Literal[
        "accepted",
        "reconciling",
        "conflict",
        "unavailable",
        "outcome_unknown",
    ]
    client_action_id: str = Field(min_length=1, max_length=200)
    action_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
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


class CompositeTurnReceiptResponse(WorkspaceActionReceiptResponse):
    payload_ref: str = Field(min_length=1)
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["conversation.turn"]


__all__ = [
    "CompositeTurnReceiptResponse",
    "WorkspaceActionReceiptResponse",
    "WorkspaceAuthoritiesResponse",
    "WorkspaceFollowResponse",
    "WorkspaceRefResponse",
    "WorkspaceSnapshotResponse",
]
