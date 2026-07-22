"""Public response contracts for the owner-local browser session boundary."""

from pydantic import BaseModel, ConfigDict, Field


class _LocalSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OwnerSessionStatusResponse(_LocalSessionResponse):
    owner_user_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=128)
    expires_at: str = Field(min_length=1, max_length=64)
    mutation_enabled: bool
    security_ready: bool


class OwnerBootstrapResponse(OwnerSessionStatusResponse):
    csrf_token: str = Field(min_length=1, max_length=256)
    csrf_header: str = Field(min_length=1, max_length=128)


class OwnerLogoutResponse(_LocalSessionResponse):
    ok: bool
    mutation_enabled: bool


__all__ = [
    "OwnerBootstrapResponse",
    "OwnerLogoutResponse",
    "OwnerSessionStatusResponse",
]
