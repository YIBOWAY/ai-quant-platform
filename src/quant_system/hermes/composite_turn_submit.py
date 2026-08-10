"""Composite Turn Submit (A2) — BFF put-then-turn for L2a-Send.

Browser never coordinates dual calls. ``/act`` stays prompt-free; this module
is the only place the BFF sees chat prompt plaintext, and only long enough to
hand it to the Intent Payload CLI Port.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from quant_system.config.settings import Settings
from quant_system.hermes.agent_workspace_actions import (
    ConversationTurn,
    WorkspaceRef,
    session_ref,
    strip_session_ref,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.dark_identity_profile import (
    CHAT_PROMPT_MAX_BYTES,
    PLATFORM_WORKSPACE_ID,
    DarkIdentityProfileError,
    build_put_request,
    require_l2a_workspace,
    require_server_managed_session_policy,
    store_session_id,
)
from quant_system.hermes.intent_payload_port import (
    IntentPayloadCliSettings,
    IntentPayloadPort,
    IntentPayloadPortError,
    build_intent_payload_port,
)
from quant_system.hermes.paper_intake_port import (
    PaperIntakePortError,
    PaperIntakePreparationPort,
    SubprocessPaperIntakePreparationPort,
)
from quant_system.hermes.session_registry import (
    HermesSessionAdmissionClosed,
    HermesSessionAdmissionMismatch,
    HermesSessionNotWritable,
    HermesSessionRegistryUnavailable,
    HermesSessionRegistryValidationError,
    require_current_session_admission,
    require_web_writable_session,
)
from quant_system.hermes.submission_saga import (
    ActionReceipt,
    SubmissionSagaError,
    submit_conversation_turn,
)


@dataclass(frozen=True)
class CompositeTurnRequest:
    workspace_id: str
    managed_session_ref: str
    client_action_id: str
    prompt: str


@dataclass(frozen=True)
class PaperIntakeTurnRequest(CompositeTurnRequest):
    paper_title: str
    universe: tuple[str, ...]


@dataclass
class _PaperIntakeIntentAdapter:
    preparation_port: PaperIntakePreparationPort
    paper_request: PaperIntakeTurnRequest
    receipt: dict[str, object] | None = None

    def put_intent(self, request: Mapping[str, Any]) -> dict[str, Any]:
        prepare_request = {
            **dict(request),
            "kind": "paper_intake",
            "paper_title": self.paper_request.paper_title,
            "universe": list(self.paper_request.universe),
        }
        try:
            receipt = self.preparation_port.prepare(prepare_request)
        except PaperIntakePortError as exc:
            raise IntentPayloadPortError(
                exc.code,
                exc.message,
                retryable=exc.retryable,
            ) from exc
        self.receipt = dict(receipt)
        return dict(receipt)


class CompositeTurnSubmitError(Exception):
    """HTTP-mappable failure before or around the put/turn boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 400,
        retryable: bool = False,
        receipt: ActionReceipt | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = bool(retryable)
        self.receipt = receipt


def _validate_request(request: CompositeTurnRequest) -> None:
    try:
        require_l2a_workspace(request.workspace_id)
    except DarkIdentityProfileError as exc:
        raise CompositeTurnSubmitError(
            exc.code,
            exc.message,
            http_status=400,
        ) from exc

    if type(request.client_action_id) is not str or not request.client_action_id:
        raise CompositeTurnSubmitError(
            "validation",
            "client_action_id must be a nonempty string",
            http_status=400,
        )
    if len(request.client_action_id) > 200:
        raise CompositeTurnSubmitError(
            "validation",
            "client_action_id exceeds bound",
            http_status=400,
        )

    if type(request.prompt) is not str:
        raise CompositeTurnSubmitError(
            "validation",
            "prompt must be a string",
            http_status=400,
        )
    if not request.prompt.strip():
        raise CompositeTurnSubmitError(
            "validation",
            "prompt must be non-empty",
            http_status=400,
        )
    if len(request.prompt.encode("utf-8")) > CHAT_PROMPT_MAX_BYTES:
        raise CompositeTurnSubmitError(
            "prompt_too_large",
            "prompt exceeds 16 KiB UTF-8 chat ceiling",
            http_status=400,
        )

    # Normalize/validate session ref shape early (no put on bad ref).
    try:
        store_session_id(request.managed_session_ref)
    except DarkIdentityProfileError as exc:
        raise CompositeTurnSubmitError(
            exc.code,
            exc.message,
            http_status=400,
        ) from exc


def _managed_session_ref_for_action(managed_session_ref: str) -> str:
    """ConversationTurn requires ``session:…`` form."""
    if managed_session_ref.startswith("session:"):
        return managed_session_ref
    return session_ref(managed_session_ref)


def _require_exact_session_admission(
    settings: Settings,
    session: object,
) -> None:
    """Reject a stale candidate Session before the prompt payload is stored."""

    try:
        require_current_session_admission(settings, session)
    except HermesSessionAdmissionClosed as exc:
        raise CompositeTurnSubmitError(
            "unavailable",
            "Agent v0.2 durable write admission is closed",
            http_status=503,
            retryable=True,
        ) from exc
    except HermesSessionAdmissionMismatch as exc:
        raise CompositeTurnSubmitError(
            "managed_session_admission_mismatch",
            "managed session belongs to a different candidate admission",
            http_status=409,
            retryable=False,
        ) from exc


def _map_port_error(exc: IntentPayloadPortError) -> CompositeTurnSubmitError:
    code = exc.code
    if (
        code.startswith("crypto_")
        or code.startswith("intent_crypto_")
        or code in {"key_not_found", "key_corrupt", "keychain_unavailable"}
    ):
        return CompositeTurnSubmitError(
            "intent_crypto_unavailable",
            "intent crypto is unavailable",
            http_status=503,
            retryable=True,
        )
    if code in {"intent_idempotency_conflict"}:
        return CompositeTurnSubmitError(
            "conflict",
            exc.message,
            http_status=409,
            retryable=False,
        )
    if code == "prompt_too_large":
        return CompositeTurnSubmitError(
            code,
            exc.message,
            http_status=400,
            retryable=False,
        )
    if code.startswith("paper_intake_"):
        return CompositeTurnSubmitError(
            code,
            "paper intake preparation failed",
            http_status=503 if exc.retryable else 400,
            retryable=exc.retryable,
        )
    if code in {
        "intent_invalid_request",
        "intent_invalid_arguments",
        "intent_invalid_json",
        "invalid_prompt",
        "invalid_session_ref",
        "workspace_not_admitted",
    }:
        return CompositeTurnSubmitError(
            "validation",
            exc.message,
            http_status=400,
            retryable=False,
        )
    # Crypto / IO / CLI down → unavailable (retryable when CLI says so).
    return CompositeTurnSubmitError(
        "unavailable",
        exc.message,
        http_status=503,
        retryable=exc.retryable,
    )


def _outcome_unknown_receipt(
    *,
    request: CompositeTurnRequest,
    payload_digest: str,
    reason_code: str,
    mutation_enabled: bool,
) -> ActionReceipt:
    # action_digest is unknown when turn never produced a canonical document;
    # surface payload_digest as the stable content identity for FE reconcile.
    return ActionReceipt(
        status="outcome_unknown",
        client_action_id=request.client_action_id,
        action_digest=payload_digest,
        workspace_id=request.workspace_id,
        reason_code=reason_code,
        mutation_enabled=mutation_enabled,
    )


def submit_composite_turn(
    settings: Settings,
    request: CompositeTurnRequest,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
    port: IntentPayloadPort | None = None,
) -> dict[str, object]:
    """Put intent then record conversation.turn. Returns public receipt dict.

    Mid-flight (put ok, turn fail/unknown) → ``outcome_unknown`` receipt body
    with HTTP 200 so FE can retry the same client_action_id.
    """
    _validate_request(request)

    if not mutation_enabled:
        raise CompositeTurnSubmitError(
            "forbidden",
            "authenticated_mutation_bff_unavailable",
            http_status=403,
        )

    try:
        session = require_web_writable_session(
            settings,
            platform_session_id=strip_session_ref(request.managed_session_ref),
        )
    except HermesSessionNotWritable as exc:
        raise CompositeTurnSubmitError(
            "conflict",
            "external_session_not_writable",
            http_status=409,
        ) from exc
    except LookupError as exc:
        raise CompositeTurnSubmitError(
            "conflict",
            "managed_session_missing",
            http_status=409,
        ) from exc
    except HermesSessionRegistryValidationError as exc:
        raise CompositeTurnSubmitError(
            "validation",
            "managed session reference is invalid",
            http_status=400,
        ) from exc
    except HermesSessionRegistryUnavailable as exc:
        raise CompositeTurnSubmitError(
            "unavailable",
            "session registry is unavailable",
            http_status=503,
            retryable=True,
        ) from exc

    if session.workspace_id != request.workspace_id:
        raise CompositeTurnSubmitError(
            "conflict",
            "session_workspace_mismatch",
            http_status=409,
        )
    _require_exact_session_admission(settings, session)
    try:
        require_server_managed_session_policy(
            provider_policy_digest=session.provider_policy_digest,
            payload_ttl_days=session.payload_ttl_days,
        )
    except DarkIdentityProfileError as exc:
        raise CompositeTurnSubmitError(
            "integrity",
            "managed session payload policy is invalid",
            http_status=503,
        ) from exc

    try:
        put_body = build_put_request(
            managed_session_ref=request.managed_session_ref,
            client_intent_id=request.client_action_id,
            prompt=request.prompt,
            payload_ttl_days=session.payload_ttl_days,
            workspace_id=request.workspace_id,
        )
    except DarkIdentityProfileError as exc:
        raise CompositeTurnSubmitError(
            exc.code,
            exc.message,
            http_status=400,
        ) from exc

    active_port = port if port is not None else build_intent_payload_port(settings)
    try:
        put_receipt = active_port.put_intent(put_body)
    except IntentPayloadPortError as exc:
        raise _map_port_error(exc) from exc

    payload_ref = put_receipt["payload_ref"]
    payload_digest = put_receipt["payload_digest"]
    if type(payload_ref) is not str or type(payload_digest) is not str:
        raise CompositeTurnSubmitError(
            "unavailable",
            "intent put receipt missing binding",
            http_status=503,
            retryable=True,
        )
    if (
        put_receipt.get("provider_policy_digest") != session.provider_policy_digest
        or put_receipt.get("ttl_days") != session.payload_ttl_days
    ):
        raise CompositeTurnSubmitError(
            "integrity",
            "intent put receipt does not match managed session policy",
            http_status=503,
            retryable=False,
        )

    action = ConversationTurn(
        client_action_id=request.client_action_id,
        workspace=WorkspaceRef(workspace_id=request.workspace_id),
        managed_session_ref=_managed_session_ref_for_action(request.managed_session_ref),
        payload_ref=payload_ref,
        payload_digest=payload_digest,
    )

    try:
        turn_receipt = submit_conversation_turn(
            settings,
            action,
            mutation_enabled=mutation_enabled,
            actor_owner_user_id=actor_owner_user_id,
        )
    except SubmissionSagaError as exc:
        # Put already committed — do not compensate; FE retries same id.
        unknown = _outcome_unknown_receipt(
            request=request,
            payload_digest=payload_digest,
            reason_code=f"turn_{exc.code}",
            mutation_enabled=mutation_enabled,
        )
        return _public_composite_receipt(
            unknown,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
        )
    except (TypeError, ValueError):
        unknown = _outcome_unknown_receipt(
            request=request,
            payload_digest=payload_digest,
            reason_code="turn_validation",
            mutation_enabled=mutation_enabled,
        )
        return _public_composite_receipt(
            unknown,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
        )

    # Turn returned a structured receipt (accepted/conflict/unavailable/…).
    # Put-ok + non-accepted is still mid-flight from the browser's POV when
    # status is unavailable (authority blip) → map to outcome_unknown so FE
    # retries the same id. Conflict stays conflict (different body / session).
    if turn_receipt.status == "unavailable":
        unknown = _outcome_unknown_receipt(
            request=request,
            payload_digest=payload_digest,
            reason_code=turn_receipt.reason_code or "turn_unavailable",
            mutation_enabled=mutation_enabled,
        )
        return _public_composite_receipt(
            unknown,
            payload_ref=payload_ref,
            payload_digest=payload_digest,
        )

    return _public_composite_receipt(
        turn_receipt,
        payload_ref=payload_ref,
        payload_digest=payload_digest,
    )


def submit_paper_intake_turn(
    settings: Settings,
    request: PaperIntakeTurnRequest,
    *,
    mutation_enabled: bool,
    actor_owner_user_id: UUID | str = ROOT_USER_ID,
    preparation_port: PaperIntakePreparationPort | None = None,
) -> dict[str, object]:
    """Prepare one contract-bound encrypted paper intent, then record its turn.

    This is an internal driver surface, not the browser submit schema.  Full
    paper title, ordered universe, and prompt cross only the local HQA stdin
    pipe; the returned receipt contains digests only.
    """

    if (
        type(request.paper_title) is not str
        or not request.paper_title
        or request.paper_title != request.paper_title.strip()
        or type(request.universe) is not tuple
        or not request.universe
        or any(type(symbol) is not str or not symbol for symbol in request.universe)
        or len(set(request.universe)) != len(request.universe)
    ):
        raise CompositeTurnSubmitError(
            "paper_intake_invalid_request",
            "paper intake claim is invalid",
            http_status=400,
        )
    active_port = preparation_port
    if active_port is None:
        try:
            active_port = SubprocessPaperIntakePreparationPort(
                cli_settings=IntentPayloadCliSettings.from_settings(settings),
            )
        except IntentPayloadPortError as exc:
            raise _map_port_error(exc) from exc
    adapter = _PaperIntakeIntentAdapter(
        preparation_port=active_port,
        paper_request=request,
    )
    public = submit_composite_turn(
        settings,
        CompositeTurnRequest(
            workspace_id=request.workspace_id,
            managed_session_ref=request.managed_session_ref,
            client_action_id=request.client_action_id,
            prompt=request.prompt,
        ),
        mutation_enabled=mutation_enabled,
        actor_owner_user_id=actor_owner_user_id,
        port=adapter,  # type: ignore[arg-type]
    )
    receipt = adapter.receipt
    if receipt is None:
        raise CompositeTurnSubmitError(
            "paper_intake_cli_invalid_receipt",
            "paper intake preparation returned no receipt",
            http_status=503,
            retryable=True,
        )
    public["paper_intake"] = {
        "execution_contract_digest": receipt["execution_contract_digest"],
        "research_claim_digest": receipt["research_claim_digest"],
    }
    return public


def _public_composite_receipt(
    receipt: ActionReceipt,
    *,
    payload_ref: str,
    payload_digest: str,
) -> dict[str, object]:
    payload = receipt.to_public_dict()
    payload["payload_ref"] = payload_ref
    payload["payload_digest"] = payload_digest
    payload["kind"] = "conversation.turn"
    return payload


def parse_submit_turn_body(raw: Mapping[str, Any]) -> CompositeTurnRequest:
    """Parse closed browser body: four fields only."""
    if type(raw) is not dict:
        raise CompositeTurnSubmitError(
            "validation",
            "body must be a JSON object",
            http_status=400,
        )
    allowed = {
        "workspace_id",
        "managed_session_ref",
        "client_action_id",
        "prompt",
    }
    if set(raw) - allowed:
        raise CompositeTurnSubmitError(
            "validation",
            "submit-turn rejects unknown fields",
            http_status=400,
        )
    missing = allowed - set(raw)
    if missing:
        raise CompositeTurnSubmitError(
            "validation",
            "submit-turn requires workspace_id, managed_session_ref, client_action_id, prompt",
            http_status=400,
        )
    return CompositeTurnRequest(
        workspace_id=raw["workspace_id"],  # type: ignore[arg-type]
        managed_session_ref=raw["managed_session_ref"],  # type: ignore[arg-type]
        client_action_id=raw["client_action_id"],  # type: ignore[arg-type]
        prompt=raw["prompt"],  # type: ignore[arg-type]
    )


__all__ = [
    "CompositeTurnRequest",
    "CompositeTurnSubmitError",
    "PaperIntakeTurnRequest",
    "PLATFORM_WORKSPACE_ID",
    "parse_submit_turn_body",
    "submit_composite_turn",
    "submit_paper_intake_turn",
]
