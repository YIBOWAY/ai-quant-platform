from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quant_system.hermes.models import (
    HermesArtifactFeedResponse,
    HermesArtifactItemResponse,
    HermesArtifactKind,
    HermesArtifactQuality,
    HermesArtifactReadStatus,
    HermesArtifactSourceResponse,
    HermesArtifactSourceStatus,
    HermesArtifactWarningResponse,
)


class _HermesGatewayReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HermesGatewayWarningResponse(_HermesGatewayReadModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=500)


class HermesGatewayStatusResponse(_HermesGatewayReadModel):
    read_status: Literal["available", "degraded", "unavailable"]
    connected: bool
    model: str | None = Field(default=None, max_length=256)
    session_api_available: bool
    chat_write_ready: bool
    features: dict[str, bool]
    # Upstream capability gaps are necessary-but-not-sufficient chat blockers.
    # Platform delivery/security gaps must independently reach zero as well.
    upstream_blockers: list[str] = Field(max_length=64)
    platform_delivery_blockers: list[str] = Field(max_length=64)
    blockers: list[str] = Field(max_length=64)
    warnings: list[HermesGatewayWarningResponse] = Field(max_length=20)


class HermesSessionSummaryResponse(_HermesGatewayReadModel):
    id: str = Field(min_length=1, max_length=256)
    title: str | None = Field(default=None, max_length=1000)
    source: str | None = Field(default=None, max_length=1000)
    model: str | None = Field(default=None, max_length=1000)
    message_count: int | None = Field(default=None, ge=0)
    last_active: str | None = Field(default=None, max_length=1000)
    preview: str | None = Field(default=None, max_length=1000)
    parent_session_id: str | None = Field(default=None, max_length=1000)
    ended_at: str | None = Field(default=None, max_length=1000)


class HermesSessionsResponse(_HermesGatewayReadModel):
    read_status: Literal["available", "unavailable"]
    sessions: list[HermesSessionSummaryResponse] = Field(max_length=200)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0, le=1_000_000)
    has_more: bool
    warnings: list[HermesGatewayWarningResponse] = Field(max_length=20)


class HermesSessionDetailResponse(_HermesGatewayReadModel):
    read_status: Literal["available", "unavailable"]
    session: HermesSessionSummaryResponse | None
    warnings: list[HermesGatewayWarningResponse] = Field(max_length=20)


class HermesMessageResponse(_HermesGatewayReadModel):
    id: str = Field(min_length=1, max_length=256)
    role: Literal["user", "assistant"]
    content: str = Field(max_length=100_000)
    timestamp: str | None = Field(default=None, max_length=128)


class HermesSessionMessagesResponse(_HermesGatewayReadModel):
    read_status: Literal["available", "unavailable"]
    session_id: str = Field(min_length=1, max_length=256)
    messages: list[HermesMessageResponse] = Field(max_length=1000)
    omitted_message_count: int = Field(ge=0)
    warnings: list[HermesGatewayWarningResponse] = Field(max_length=20)


__all__ = [
    "HermesArtifactFeedResponse",
    "HermesArtifactItemResponse",
    "HermesArtifactKind",
    "HermesArtifactQuality",
    "HermesArtifactReadStatus",
    "HermesArtifactSourceStatus",
    "HermesArtifactSourceResponse",
    "HermesArtifactWarningResponse",
    "HermesGatewayStatusResponse",
    "HermesGatewayWarningResponse",
    "HermesMessageResponse",
    "HermesSessionDetailResponse",
    "HermesSessionMessagesResponse",
    "HermesSessionSummaryResponse",
    "HermesSessionsResponse",
]
