"""Dark Identity Profile — shared BFF/worker constants for L2a-Send.

Maps platform workspace/session/owner fields into Intent Payload Store scope
and the locked chat ``provider_policy`` digest. FE never supplies store
owner/policy/ttl; create session and composite put must use the same digest.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_system.hermes.agent_workspace_actions import (
    AgentWorkspaceActionError,
    session_ref,
    strip_session_ref,
)

# Platform-side workspace id admitted by L2a-Send.
PLATFORM_WORKSPACE_ID = "ws-local-main"

# Intent Payload Store scope (not the UUID owner cookie).
STORE_OWNER_ID = "owner-local-root"
STORE_WORKSPACE_ID = "workspace:ws-local-main"

STORE_KIND = "conversation_turn"
STORE_SCHEMA_VERSION = "2.0"
STORE_TTL_DAYS = 7

# Locked chat provider_policy. Digest is SHA-256 of store-canonical JSON
# (sort_keys=True, separators=(",", ":"), no trailing newline).
PROVIDER_POLICY: dict[str, Any] = {
    "primary": {"provider": "openai", "model": "gpt-5"},
    "fallbacks": [],
}
PROVIDER_POLICY_DIGEST = (
    "be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31"
)

CHAT_PROMPT_MAX_BYTES = 16_384


class DarkIdentityProfileError(ValueError):
    """Fail-closed profile mapping error (secret-free)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def require_l2a_workspace(workspace_id: str) -> str:
    if type(workspace_id) is not str or workspace_id != PLATFORM_WORKSPACE_ID:
        raise DarkIdentityProfileError(
            "workspace_not_admitted",
            "L2a-Send only admits workspace ws-local-main",
        )
    return workspace_id


def require_server_managed_session_policy(
    *, provider_policy_digest: object, payload_ttl_days: object
) -> None:
    """Admit the one server-owned v0.2 provider policy and immutable TTL."""

    if provider_policy_digest != PROVIDER_POLICY_DIGEST:
        raise DarkIdentityProfileError(
            "provider_policy_not_admitted",
            "managed session provider policy is not server-admitted",
        )
    if type(payload_ttl_days) is not int or payload_ttl_days != STORE_TTL_DAYS:
        raise DarkIdentityProfileError(
            "invalid_payload_ttl_days",
            f"payload_ttl_days must equal the server policy {STORE_TTL_DAYS}",
        )


def store_session_id(managed_session_ref: str) -> str:
    """Normalize managed_session_ref to store ``session:…`` form."""
    if type(managed_session_ref) is not str or not managed_session_ref:
        raise DarkIdentityProfileError(
            "invalid_session_ref",
            "managed_session_ref must be a nonempty string",
        )
    if managed_session_ref.startswith("session:"):
        # Validate via strip (raises AgentWorkspaceActionError on bad shape).
        try:
            bare = strip_session_ref(managed_session_ref)
        except AgentWorkspaceActionError as exc:
            raise DarkIdentityProfileError(
                "invalid_session_ref",
                str(exc) or "invalid managed_session_ref",
            ) from exc
        return session_ref(bare)
    try:
        return session_ref(managed_session_ref)
    except AgentWorkspaceActionError as exc:
        raise DarkIdentityProfileError(
            "invalid_session_ref",
            str(exc) or "invalid managed_session_ref",
        ) from exc


def normalize_payload_ref(value: str) -> str:
    """Normalize any supported surface form to ``payload:sha256:<digest>``."""
    if type(value) is not str or not value:
        raise DarkIdentityProfileError(
            "invalid_payload_ref",
            "payload_ref must be a nonempty string",
        )
    if value.startswith("payload:sha256:"):
        digest = value[len("payload:sha256:") :]
    elif value.startswith("platform-payload://sha256/"):
        digest = value[len("platform-payload://sha256/") :]
    elif value.startswith("hqa-payload:sha256:"):
        digest = value[len("hqa-payload:sha256:") :]
    else:
        # Bare 64-hex digest is accepted for worker convenience.
        digest = value
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise DarkIdentityProfileError(
            "invalid_payload_ref",
            "payload_ref digest must be lowercase SHA-256 hex",
        )
    return "payload:sha256:" + digest


def build_put_request(
    *,
    managed_session_ref: str,
    client_intent_id: str,
    prompt: str,
    payload_ttl_days: int,
    workspace_id: str = PLATFORM_WORKSPACE_ID,
) -> dict[str, Any]:
    """Build closed-schema stdin body for ``intent_payload_cli put``."""
    require_l2a_workspace(workspace_id)
    if type(client_intent_id) is not str or not client_intent_id:
        raise DarkIdentityProfileError(
            "invalid_client_intent_id",
            "client_intent_id must be a nonempty string",
        )
    if type(prompt) is not str:
        raise DarkIdentityProfileError("invalid_prompt", "prompt must be a string")
    if not prompt.strip():
        raise DarkIdentityProfileError(
            "invalid_prompt",
            "prompt must be non-empty after stripping whitespace",
        )
    encoded = prompt.encode("utf-8")
    if len(encoded) > CHAT_PROMPT_MAX_BYTES:
        raise DarkIdentityProfileError(
            "prompt_too_large",
            "prompt exceeds 16 KiB UTF-8 chat ceiling",
        )
    require_server_managed_session_policy(
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
        payload_ttl_days=payload_ttl_days,
    )
    return {
        "schema_version": STORE_SCHEMA_VERSION,
        "kind": STORE_KIND,
        "owner_id": STORE_OWNER_ID,
        "workspace_id": STORE_WORKSPACE_ID,
        "session_id": store_session_id(managed_session_ref),
        "client_intent_id": client_intent_id,
        "provider_policy": dict(PROVIDER_POLICY),
        "prompt": prompt,
        "ttl_days": payload_ttl_days,
    }


def build_bind_resolve_request(
    *,
    payload_ref: str,
    managed_session_ref: str,
    consumer_ref: str,
    workspace_id: str = PLATFORM_WORKSPACE_ID,
) -> dict[str, Any]:
    """Build closed-schema stdin body for ``intent_payload_cli bind_resolve``."""
    require_l2a_workspace(workspace_id)
    if type(consumer_ref) is not str or not consumer_ref:
        raise DarkIdentityProfileError(
            "invalid_consumer_ref",
            "consumer_ref must be a nonempty string",
        )
    return {
        "payload_ref": normalize_payload_ref(payload_ref),
        "owner_id": STORE_OWNER_ID,
        "workspace_id": STORE_WORKSPACE_ID,
        "session_id": store_session_id(managed_session_ref),
        "consumer_ref": consumer_ref,
    }


def profile_public_constants() -> Mapping[str, object]:
    """Secret-free constants for diagnostics / tests (no prompt)."""
    return {
        "platform_workspace_id": PLATFORM_WORKSPACE_ID,
        "store_owner_id": STORE_OWNER_ID,
        "store_workspace_id": STORE_WORKSPACE_ID,
        "kind": STORE_KIND,
        "schema_version": STORE_SCHEMA_VERSION,
        "ttl_days": STORE_TTL_DAYS,
        "provider_policy_digest": PROVIDER_POLICY_DIGEST,
        "chat_prompt_max_bytes": CHAT_PROMPT_MAX_BYTES,
    }


__all__ = [
    "CHAT_PROMPT_MAX_BYTES",
    "DarkIdentityProfileError",
    "PLATFORM_WORKSPACE_ID",
    "PROVIDER_POLICY",
    "PROVIDER_POLICY_DIGEST",
    "STORE_KIND",
    "STORE_OWNER_ID",
    "STORE_SCHEMA_VERSION",
    "STORE_TTL_DAYS",
    "STORE_WORKSPACE_ID",
    "build_bind_resolve_request",
    "build_put_request",
    "normalize_payload_ref",
    "profile_public_constants",
    "require_l2a_workspace",
    "require_server_managed_session_policy",
    "store_session_id",
]
