from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class D34MandateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(default="default", min_length=1, max_length=128)
    duration_days: int = Field(default=30, ge=1, le=365)
    universe: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "DIA"],
        min_length=1,
        max_length=64,
    )
    hypotheses_per_cycle: int = Field(default=1, ge=1, le=100)
    max_iterations: int = Field(default=3, ge=1, le=100)
    max_experiments_per_iteration: int = Field(default=3, ge=1, le=100)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=32)
    llm_budget_usd: str = Field(default="100.00", pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$")
    llm_warning_fraction: str = Field(default="0.80", pattern=r"^0\.[0-9]{1,4}$")
    paper_execution_allowed: bool = True


class D34MandateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = Field(pattern=r"^hqa\.mandate/v1$")
    mandate_id: str = Field(min_length=1, max_length=256)
    owner_user_id: str = Field(min_length=36, max_length=36)
    workspace_id: str = Field(min_length=1, max_length=128)
    status: str = Field(pattern=r"^(active|paused|revoked|expired)$")
    universe: list[str] = Field(min_length=1, max_length=64)
    hypotheses_per_cycle: int = Field(ge=1, le=100)
    max_iterations: int = Field(ge=1, le=100)
    max_experiments_per_iteration: int = Field(ge=1, le=100)
    max_concurrent_jobs: int = Field(ge=1, le=32)
    llm_budget_usd: Decimal = Field(gt=Decimal("0"), le=Decimal("100000"))
    llm_warning_fraction: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    paper_execution_allowed: bool
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    starts_at: datetime
    expires_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class D34MandateListResponse(BaseModel):
    contract: str = Field(pattern=r"^hqa\.mandate-list/v1$")
    items: list[D34MandateResponse]


class D34MandateTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class D34MandateRenewRequest(D34MandateTransitionRequest):
    duration_days: int = Field(default=30, ge=1, le=365)


class D34ExperimentJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = Field(pattern=r"^hqa\.d34_experiment_job/v1$")
    job_id: str = Field(min_length=1, max_length=256)
    mandate_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=128)
    job_key: str = Field(min_length=1, max_length=512)
    state: str = Field(
        pattern=r"^(queued|leased|running|succeeded|rejected|outcome_unknown|cancelled)$"
    )
    attempt_count: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    input_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    budget_reserved_usd: Decimal = Field(ge=Decimal("0"))
    budget_spent_usd: Decimal = Field(ge=Decimal("0"))
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)
    outcome_code: str | None = None


class D34ExperimentJobListResponse(BaseModel):
    contract: str = Field(pattern=r"^hqa\.d34_experiment_job-list/v1$")
    items: list[D34ExperimentJobResponse]


class D34ArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = Field(pattern=r"^hqa\.d34_artifact/v1$")
    artifact_id: str
    mandate_id: str
    workspace_id: str
    status: str = Field(pattern=r"^(qualified|canary_active|paused|demoted|rejected|rolled_back)$")
    qualification_scope: str = Field(pattern=r"^paper_only$")
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_code_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    qlib_config_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    rdagent_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    qlib_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    docker_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    qlib_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    platform_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    comparison_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_decision_id: str
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class D34ArtifactListResponse(BaseModel):
    contract: str = Field(pattern=r"^hqa\.d34_artifact-list/v1$")
    items: list[D34ArtifactResponse]


class D34CanaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = Field(pattern=r"^hqa\.d34_canary/v1$")
    canary_id: str
    artifact_id: str
    mandate_id: str
    workspace_id: str
    sleeve_id: str
    status: str = Field(pattern=r"^(provisioning|running|paused|demoted|rolled_back)$")
    allocated_cash: Decimal = Field(ge=Decimal("0"))
    nav_fraction: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    daily_pnl: Decimal
    drawdown_fraction: Decimal = Field(ge=Decimal("0"))
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class D34CanaryListResponse(BaseModel):
    contract: str = Field(pattern=r"^hqa\.d34_canary-list/v1$")
    items: list[D34CanaryResponse]


class D34CanaryTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class D34RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(default="default", min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=1000)


class D34RollbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = Field(pattern=r"^hqa\.d34_rollback/v1$")
    mandate_id: str | None = None
    mandate_status: str | None = Field(default=None, pattern=r"^paused$")
    jobs_cancelled: int = Field(ge=0)
    transitioned: int = Field(ge=0)
    canary_ids: list[str]
