"""Server-owned bridge from an observed Hermes session into a Web session.

The browser selects only an exact message cursor.  It never supplies platform
registry identity, source-channel classification, provider policy, or TTL.
Those authority-bearing facts are derived and revalidated here before the
existing managed-session fork saga is invoked.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from uuid import UUID

from quant_system.config.settings import Settings
from quant_system.hermes.agent_workspace_actions import (
    ForkIntoManagedSession,
    WorkspaceRef,
    session_ref,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.dark_identity_profile import (
    PLATFORM_WORKSPACE_ID,
    PROVIDER_POLICY_DIGEST,
    STORE_TTL_DAYS,
)
from quant_system.hermes.gateway_client import (
    HermesApiReadClient,
    validate_hermes_session_id,
)
from quant_system.hermes.session_registry import (
    HermesSessionRegistryConflict,
    HermesSessionRegistryUnavailable,
    HermesSessionRegistryValidationError,
    RegisterWorkspaceSession,
    register_workspace_session,
)
from quant_system.hermes.submission_saga import (
    ActionReceipt,
    submit_fork_into_managed_session,
)

_FORK_POINT_RE = re.compile(r"^message:[1-9][0-9]*$")
_HISTORICAL_SOURCES = frozenset(
    {
        "local",
        "desktop",
        "tui",
        "cli",
        "telegram",
        "whatsapp",
        "whatsapp_cloud",
        "slack",
        "signal",
        "mattermost",
        "matrix",
        "homeassistant",
        "email",
        "sms",
        "dingtalk",
        "webhook",
        "msgraph_webhook",
        "feishu",
        "wecom",
        "wecom_callback",
        "weixin",
        "bluebubbles",
        "qqbot",
        "yuanbao",
        "relay",
    }
)


class ExternalSessionForkError(RuntimeError):
    """Stable, secret-free refusal from the observed-session fork bridge."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def external_session_fork_context(
    detail: Mapping[str, object],
) -> dict[str, object]:
    """Project read-only eligibility without registering or mutating anything."""

    source = detail.get("source")
    if source == "discord":
        return {
            "eligible": True,
            "source_channel": "discord",
            "reason_code": None,
        }
    if isinstance(source, str) and source in _HISTORICAL_SOURCES:
        return {
            "eligible": True,
            "source_channel": "historical",
            "reason_code": None,
        }
    return {
        "eligible": False,
        "source_channel": None,
        "reason_code": "source_session_not_external",
    }


def _observed_platform_session_id(hermes_session_id: str) -> str:
    safe_id = validate_hermes_session_id(hermes_session_id)
    digest = hashlib.sha256(
        b"agent-v0.2-observed-session\x00" + safe_id.encode("utf-8")
    ).hexdigest()
    return f"ext_{digest[:32]}"


def _require_session_resources(gateway: HermesApiReadClient) -> None:
    capabilities = gateway.capabilities()
    features = capabilities.get("features")
    if not isinstance(features, Mapping) or features.get("session_resources") is not True:
        raise ExternalSessionForkError(
            "session_resources_unavailable",
            "Hermes API does not advertise persisted session resources",
        )


def _require_exact_message(
    gateway: HermesApiReadClient,
    *,
    hermes_session_id: str,
    fork_point: str,
) -> None:
    if _FORK_POINT_RE.fullmatch(fork_point) is None:
        raise ExternalSessionForkError(
            "fork_point_invalid",
            "fork_point must be an exact message:<positive-integer> cursor",
        )
    history = gateway.session_messages(hermes_session_id)
    if history.get("session_id") != hermes_session_id:
        raise ExternalSessionForkError(
            "session_identity_mismatch",
            "Hermes message response does not match the selected session",
        )
    rows = history.get("data")
    if not isinstance(rows, list) or not any(
        isinstance(row, Mapping) and row.get("fork_point") == fork_point for row in rows
    ):
        raise ExternalSessionForkError(
            "fork_point_not_authoritative",
            "fork_point does not identify an authoritative active Hermes message",
        )


def submit_external_session_fork(
    settings: Settings,
    gateway: HermesApiReadClient,
    *,
    hermes_session_id: str,
    fork_point: str,
    new_provider_policy_digest: str,
    client_action_id: str,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str,
) -> ActionReceipt:
    """Register one immutable observed source and fork it through the saga."""

    safe_session_id = validate_hermes_session_id(hermes_session_id)
    try:
        owner_user_id = UUID(str(actor_owner_user_id))
    except (TypeError, ValueError) as exc:
        raise ExternalSessionForkError(
            "actor_invalid",
            "authenticated owner identity is invalid",
        ) from exc
    if owner_user_id != ROOT_USER_ID:
        raise ExternalSessionForkError(
            "actor_invalid",
            "only the local root owner may fork an external session",
        )
    if new_provider_policy_digest != PROVIDER_POLICY_DIGEST:
        raise ExternalSessionForkError(
            "provider_policy_not_admitted",
            "the explicitly selected provider policy is not admitted",
        )

    _require_session_resources(gateway)
    detail = gateway.session_detail(safe_session_id)
    if detail.get("id") != safe_session_id:
        raise ExternalSessionForkError(
            "session_identity_mismatch",
            "Hermes session response does not match the selected session",
        )
    context = external_session_fork_context(detail)
    source_channel = context.get("source_channel")
    if context.get("eligible") is not True or source_channel not in {
        "discord",
        "historical",
    }:
        raise ExternalSessionForkError(
            "source_session_not_external",
            "Hermes session is not an eligible external or historical session",
        )
    _require_exact_message(
        gateway,
        hermes_session_id=safe_session_id,
        fork_point=fork_point,
    )

    observed_id = _observed_platform_session_id(safe_session_id)
    try:
        observed, _created = register_workspace_session(
            settings,
            RegisterWorkspaceSession(
                platform_session_id=observed_id,
                hermes_session_id=safe_session_id,
                workspace_id=PLATFORM_WORKSPACE_ID,
                kind="observed_external_session",
                source_channel=source_channel,
                owner_user_id=owner_user_id,
            ),
        )
    except HermesSessionRegistryConflict as exc:
        raise ExternalSessionForkError(
            "source_session_identity_conflict",
            "observed session identity conflicts with the durable registry",
        ) from exc
    except (
        HermesSessionRegistryUnavailable,
        HermesSessionRegistryValidationError,
    ) as exc:
        raise ExternalSessionForkError(
            "source_session_registry_unavailable",
            "observed session registry is unavailable",
        ) from exc

    action = ForkIntoManagedSession(
        client_action_id=client_action_id,
        workspace=WorkspaceRef(workspace_id=PLATFORM_WORKSPACE_ID),
        source_session_ref=session_ref(observed.platform_session_id),
        source_channel=source_channel,
        fork_point=fork_point,
        new_provider_policy_digest=new_provider_policy_digest,
        payload_ttl_days=STORE_TTL_DAYS,
    )
    return submit_fork_into_managed_session(
        settings,
        action,
        mutation_enabled=mutation_enabled,
        actor_owner_user_id=owner_user_id,
    )


__all__ = [
    "ExternalSessionForkError",
    "external_session_fork_context",
    "submit_external_session_fork",
]
