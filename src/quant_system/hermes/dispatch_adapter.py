"""Hermes submit-or-recover dispatch port for the supervised connector worker.

Network I/O lives exclusively behind this port so the worker can keep every
PostgreSQL mutation in a short transaction and call Hermes only after commit.
The production path is intentionally pluggable; hermetic tests use
``FakeHermesDispatchAdapter`` (no real network, no provider).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol

DispatchOutcomeKind = Literal[
    "accepted",
    "recovered",
    "rejected",
    "timeout",
    "transport_error",
    "unavailable",
]
RunLifecycleStatus = Literal[
    "accepted",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "outcome_unknown",
]


@dataclass(frozen=True)
class HermesDispatchRequest:
    """Metadata-only dispatch request. Never carries a prompt body."""

    command_id: str
    kind: str
    client_request_id: str
    platform_session_id: str
    canonical_request_digest: str
    payload_ref: str
    provider_policy_digest: str | None = None
    # Exact Hermes managed-session identity resolved from the platform registry.
    # ``wm_*`` is the platform key and must never be sent upstream; ``web_*`` is
    # preallocated for Hermes and is reused by every turn in the conversation.
    hermes_session_id: str | None = None

    def idempotency_key(self) -> str:
        # ``client_request_id`` is unique only inside one platform session.
        # The durable command UUID is globally unique and stable across every
        # ACK-loss recovery attempt for the same ledger row.
        return f"platform-command:{self.command_id}"

    def request_body(self) -> dict[str, object]:
        body: dict[str, object] = {
            "command_id": self.command_id,
            "kind": self.kind,
            "client_request_id": self.client_request_id,
            "platform_session_id": self.platform_session_id,
            "canonical_request_digest": self.canonical_request_digest,
            "payload_ref": self.payload_ref,
        }
        if self.provider_policy_digest is not None:
            body["provider_policy_digest"] = self.provider_policy_digest
        if self.hermes_session_id is not None:
            body["hermes_session_id"] = self.hermes_session_id
        return body


@dataclass(frozen=True)
class HermesDispatchResult:
    kind: DispatchOutcomeKind
    # Stable managed Session identity owned by the workspace registry.
    conversation_hermes_session_id: str | None = None
    # Exact compression tip bound to the immutable Hermes Run.
    hermes_session_id: str | None = None
    hermes_run_id: str | None = None
    error_code: str | None = None
    evidence_digest: str | None = None
    provider_call_count: int = 0
    # True only when the Run mutation seam may have been reached. Payload/
    # registry/capability failures before submission keep this False.
    network_attempted: bool = True

    @property
    def is_success(self) -> bool:
        return self.kind in {"accepted", "recovered"}


@dataclass(frozen=True)
class HermesRunObservation:
    """Replay-backed lifecycle fact for one exact Hermes Run.

    ``accepted`` and ``running`` are deliberately nonterminal. A terminal fact
    is usable only when replay is complete and a content digest is present.
    """

    status: RunLifecycleStatus
    hermes_session_id: str
    hermes_run_id: str
    conversation_hermes_session_id: str | None = None
    evidence_digest: str | None = None
    error_code: str | None = None
    next_cursor: int = 0
    replay_complete: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.status in {"succeeded", "failed", "cancelled"}


class HermesDispatchPort(Protocol):
    """submit-or-recover surface consumed by the supervised worker."""

    def submit_or_recover(self, request: HermesDispatchRequest) -> HermesDispatchResult: ...

    def capabilities(self) -> Mapping[str, object]: ...


class RunLifecyclePort(HermesDispatchPort, Protocol):
    """Durable submit/recover plus replay-backed Run observation surface."""

    def observe(
        self,
        *,
        conversation_hermes_session_id: str | None = None,
        hermes_session_id: str,
        hermes_run_id: str,
        after_cursor: int = 0,
    ) -> HermesRunObservation: ...


def evidence_digest_for(
    *,
    hermes_session_id: str,
    hermes_run_id: str,
    outcome: str,
    conversation_hermes_session_id: str | None = None,
) -> str:
    payload = {
        "hermes_run_id": hermes_run_id,
        "hermes_session_id": hermes_session_id,
        "outcome": outcome,
    }
    if conversation_hermes_session_id is not None:
        payload["conversation_hermes_session_id"] = (
            conversation_hermes_session_id
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass
class FakeHermesDispatchAdapter:
    """In-process submit-or-recover double with scripted fault injection.

    Fault modes (set ``next_fault`` before a call):
    - ``None``: accept / recover by idempotency key
    - ``"timeout"``: raise no exception; return timeout (unknown outcome)
    - ``"transport_error"``: return transport_error (unknown outcome)
    - ``"rejected"``: definitive upstream rejection
    - ``"unavailable"``: durable authority closed
    - ``"accept_drop_ack"``: accept server-side but return timeout to the caller
      (models Hermes-accepted-but-response-lost); recovery uses the same key
    """

    next_fault: str | None = None
    force_provider_calls: bool = False
    submit_calls: int = 0
    provider_calls: int = 0
    _by_key: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    _observations: dict[str, HermesRunObservation] = field(default_factory=dict)

    def capabilities(self) -> Mapping[str, object]:
        return {
            "object": "hermes.api_server.capabilities",
            "features": {"session_resources": True, "run_submission": True},
            "durable": {
                "idempotency": {"supported": True, "grounded": True},
                "event_replay": {"supported": True, "grounded": True},
                "approval_cas": {"supported": True, "grounded": True},
                "idempotent_stop": {"supported": True, "grounded": True},
                "restart_reconcile": {"supported": True, "grounded": True},
                "run_evidence": {"supported": True, "grounded": True},
            },
            "contract_version": 1,
        }

    def submit_or_recover(self, request: HermesDispatchRequest) -> HermesDispatchResult:
        self.submit_calls += 1
        fault = self.next_fault
        self.next_fault = None

        if fault == "unavailable":
            return HermesDispatchResult(
                kind="unavailable",
                error_code="durable_unavailable",
                evidence_digest=_digest({"fault": "unavailable", "key": request.idempotency_key()}),
                network_attempted=False,
            )
        if fault == "rejected":
            return HermesDispatchResult(
                kind="rejected",
                error_code="upstream_rejected",
                evidence_digest=_digest({"fault": "rejected", "key": request.idempotency_key()}),
            )
        if fault == "timeout":
            return HermesDispatchResult(
                kind="timeout",
                error_code="hermes_response_timeout",
            )
        if fault == "transport_error":
            return HermesDispatchResult(
                kind="transport_error",
                error_code="hermes_transport_error",
            )

        key = request.idempotency_key()
        body_digest = _digest(request.request_body())
        existing = self._by_key.get(key)
        provider_delta = 1 if self.force_provider_calls else 0

        if existing is not None:
            session_id, run_id, prior_digest = existing
            if prior_digest != body_digest:
                return HermesDispatchResult(
                    kind="rejected",
                    error_code="idempotency_conflict",
                    evidence_digest=_digest({"fault": "idempotency_conflict", "key": key}),
                )
            # Recovered identity — no second Run, no provider burn by default.
            return HermesDispatchResult(
                kind="recovered",
                conversation_hermes_session_id=(
                    request.hermes_session_id or session_id
                ),
                hermes_session_id=session_id,
                hermes_run_id=run_id,
                evidence_digest=evidence_digest_for(
                    conversation_hermes_session_id=(
                        request.hermes_session_id or session_id
                    ),
                    hermes_session_id=session_id,
                    hermes_run_id=run_id,
                    outcome="recovered",
                ),
                provider_call_count=0,
            )

        session_id = request.hermes_session_id or f"sess_{uuid.uuid4().hex}"
        run_id = f"run_{uuid.uuid4().hex}"
        self._by_key[key] = (session_id, run_id, body_digest)
        self.provider_calls += provider_delta

        if fault == "accept_drop_ack":
            # Upstream accepted; caller only sees timeout. Recovery finds the Run.
            return HermesDispatchResult(
                kind="timeout",
                error_code="hermes_response_timeout",
                provider_call_count=provider_delta,
            )

        return HermesDispatchResult(
            kind="accepted",
            conversation_hermes_session_id=(
                request.hermes_session_id or session_id
            ),
            hermes_session_id=session_id,
            hermes_run_id=run_id,
            evidence_digest=evidence_digest_for(
                conversation_hermes_session_id=(
                    request.hermes_session_id or session_id
                ),
                hermes_session_id=session_id,
                hermes_run_id=run_id,
                outcome="accepted",
            ),
            provider_call_count=provider_delta,
        )

    def set_run_observation(self, observation: HermesRunObservation) -> None:
        self._observations[observation.hermes_run_id] = observation

    def observe(
        self,
        *,
        conversation_hermes_session_id: str | None = None,
        hermes_session_id: str,
        hermes_run_id: str,
        after_cursor: int = 0,
    ) -> HermesRunObservation:
        observation = self._observations.get(hermes_run_id)
        if observation is not None:
            if observation.conversation_hermes_session_id is None:
                return replace(
                    observation,
                    conversation_hermes_session_id=(
                        conversation_hermes_session_id or hermes_session_id
                    ),
                )
            return observation
        return HermesRunObservation(
            status="accepted",
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            conversation_hermes_session_id=(
                conversation_hermes_session_id or hermes_session_id
            ),
            next_cursor=max(0, after_cursor),
            replay_complete=True,
        )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Production loopback HTTP adapter (local supervised path)
# ---------------------------------------------------------------------------


class HermesDispatchAdapterError(RuntimeError):
    """Secret-free failure from the real Hermes dispatch adapter."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fixed_input_resolver(text: str) -> Callable[[HermesDispatchRequest], str]:
    """Return a resolver that always yields the same short smoke/input body."""

    body = str(text)
    if not body or len(body.encode("utf-8")) > 16_384:
        raise ValueError("fixed input must be non-empty and <= 16KiB")

    def _resolve(_request: HermesDispatchRequest) -> str:
        return body

    return _resolve


def metadata_input_resolver(request: HermesDispatchRequest) -> str:
    """Default resolver: never embeds a real user prompt from PG.

    Builds a short deterministic instruction from metadata digests so a local
    ephemeral run can still execute without reading HQA ciphertext. Production
    research cutover should inject a trusted HQA intent-payload resolver.
    """
    return (
        "Platform supervised dispatch (metadata-only). "
        f"command={request.command_id} kind={request.kind} "
        f"digest={request.canonical_request_digest[:16]} "
        "Reply with exactly: ack"
    )


@dataclass
class HttpHermesDispatchAdapter:
    """Deprecated test-only direct POST ``/v1/runs`` adapter.

    Design notes
    ------------
    * Does **not** mutate :class:`~quant_system.hermes.gateway_client.HermesApiReadClient`
      (that type stays GET-only).
    * Production connector construction uses ``RunLifecyclePort`` through HQA,
      never this adapter. Ephemeral mode defaults OFF and exists only for bounded
      hermetic compatibility tests.
    * ``input_resolver`` is the only place prompt text may appear; the ledger
      still stores only ``payload_ref``.
    """

    settings: object  # HermesGatewaySettings (typed loosely to avoid cycles)
    input_resolver: Callable[[HermesDispatchRequest], str] = field(
        default=metadata_input_resolver
    )
    allow_ephemeral_runs: bool = False
    transport: object | None = None  # httpx.BaseTransport | None
    dispatch_timeout_seconds: float | None = None
    _by_key: dict[str, tuple[str, str, str]] = field(default_factory=dict, init=False, repr=False)
    _provider_calls: int = field(default=0, init=False, repr=False)

    def capabilities(self) -> Mapping[str, object]:
        try:
            return self._get_json("/v1/capabilities")
        except HermesDispatchAdapterError as exc:
            return {
                "object": "hermes.api_server.capabilities",
                "features": {"run_submission": False},
                "error_code": exc.code,
            }

    def submit_or_recover(self, request: HermesDispatchRequest) -> HermesDispatchResult:
        if request.hermes_session_id is not None and not request.hermes_session_id.startswith(
            "web_"
        ):
            return HermesDispatchResult(
                kind="rejected",
                error_code="managed_session_required",
                network_attempted=False,
            )
        key = request.idempotency_key()
        body_digest = _digest(request.request_body())
        cached = self._by_key.get(key)
        if cached is not None:
            session_id, run_id, prior_digest = cached
            if prior_digest != body_digest:
                return HermesDispatchResult(
                    kind="rejected",
                    error_code="idempotency_conflict",
                    evidence_digest=_digest({"fault": "idempotency_conflict", "key": key}),
                )
            return HermesDispatchResult(
                kind="recovered",
                hermes_session_id=session_id,
                hermes_run_id=run_id,
                evidence_digest=evidence_digest_for(
                    hermes_session_id=session_id,
                    hermes_run_id=run_id,
                    outcome="recovered",
                ),
                provider_call_count=0,
            )

        try:
            caps = self.capabilities()
            gate = self._run_submission_gate(caps)
            if gate is not None:
                return gate

            try:
                prompt = self.input_resolver(request)
            except Exception:  # noqa: BLE001 - never leak resolver internals
                return HermesDispatchResult(
                    kind="rejected",
                    error_code="payload_resolve_failed",
                    evidence_digest=_digest({"fault": "payload_resolve_failed", "key": key}),
                    network_attempted=False,
                )
            if type(prompt) is not str or not prompt or len(prompt.encode("utf-8")) > 16_384:
                return HermesDispatchResult(
                    kind="rejected",
                    error_code="payload_input_invalid",
                    evidence_digest=_digest({"fault": "payload_input_invalid", "key": key}),
                    network_attempted=False,
                )

            payload = self._post_run(
                input_text=prompt,
                idempotency_key=key,
                session_id=request.hermes_session_id,
                metadata={
                    "command_id": request.command_id,
                    "kind": request.kind,
                    "client_request_id": request.client_request_id,
                    "platform_session_id": request.platform_session_id,
                    "canonical_request_digest": request.canonical_request_digest,
                    "payload_ref": request.payload_ref,
                    "source": "platform.http_hermes_dispatch_adapter",
                },
            )
        except HermesDispatchAdapterError as exc:
            return self._map_transport_error(exc)
        except Exception:  # noqa: BLE001
            return HermesDispatchResult(
                kind="transport_error",
                error_code="hermes_adapter_exception",
            )

        run_id = _as_nonempty_str(payload.get("run_id") or payload.get("id"))
        session_id = _as_nonempty_str(
            payload.get("session_id") or payload.get("hermes_session_id")
        )
        if not run_id or not session_id:
            return HermesDispatchResult(
                kind="transport_error",
                error_code="missing_hermes_ids",
            )
        if request.hermes_session_id is not None and session_id != request.hermes_session_id:
            return HermesDispatchResult(
                kind="transport_error",
                error_code="managed_session_identity_mismatch",
                network_attempted=True,
            )

        self._by_key[key] = (session_id, run_id, body_digest)
        created = payload.get("created")
        if type(created) is not bool:
            return HermesDispatchResult(
                kind="transport_error",
                error_code="missing_created_flag",
            )
        kind: DispatchOutcomeKind = "recovered" if created is False else "accepted"
        provider_calls = 0 if created is False else 1
        self._provider_calls += provider_calls
        return HermesDispatchResult(
            kind=kind,
            hermes_session_id=session_id,
            hermes_run_id=run_id,
            evidence_digest=evidence_digest_for(
                hermes_session_id=session_id,
                hermes_run_id=run_id,
                outcome=kind,
            ),
            provider_call_count=provider_calls,
        )

    # -- internals -----------------------------------------------------------

    def _run_submission_gate(
        self, caps: Mapping[str, object]
    ) -> HermesDispatchResult | None:
        features = caps.get("features")
        if not isinstance(features, Mapping) or features.get("run_submission") is not True:
            return HermesDispatchResult(
                kind="unavailable",
                error_code="run_submission_unavailable",
                evidence_digest=_digest({"fault": "run_submission_unavailable"}),
                network_attempted=False,
            )
        durable = caps.get("durable")
        if isinstance(durable, Mapping):
            # Durable block present: require the six grounded probes (V2 contract).
            required = (
                "idempotency",
                "event_replay",
                "approval_cas",
                "idempotent_stop",
                "restart_reconcile",
                "run_evidence",
            )
            for probe_name in required:
                probe = durable.get(probe_name)
                if not isinstance(probe, Mapping):
                    return HermesDispatchResult(
                        kind="unavailable",
                        error_code="durable_probe_missing",
                        evidence_digest=_digest(
                            {"fault": "durable_probe_missing", "probe": probe_name}
                        ),
                        network_attempted=False,
                    )
                if probe.get("supported") is not True or probe.get("grounded") is not True:
                    return HermesDispatchResult(
                        kind="unavailable",
                        error_code="durable_ungrounded",
                        evidence_digest=_digest(
                            {"fault": "durable_ungrounded", "probe": probe_name}
                        ),
                        network_attempted=False,
                    )
            return None
        # Durable block absent (live 0.18.x default).
        if self.allow_ephemeral_runs:
            return None
        return HermesDispatchResult(
            kind="unavailable",
            error_code="durable_unavailable",
            evidence_digest=_digest({"fault": "durable_block_absent"}),
            network_attempted=False,
        )

    def _map_transport_error(self, exc: HermesDispatchAdapterError) -> HermesDispatchResult:
        code = exc.code
        if code in {"upstream_timeout"}:
            return HermesDispatchResult(kind="timeout", error_code=code)
        if code in {
            "upstream_auth_failed",
            "invalid_endpoint",
            "api_key_file_missing",
            "api_key_file_invalid",
            "api_key_file_permissions",
            "api_key_file_owner",
            "api_key_invalid",
            "integration_disabled",
        }:
            return HermesDispatchResult(kind="unavailable", error_code=code)
        if code in {"upstream_rejected", "idempotency_conflict", "invalid_request"}:
            return HermesDispatchResult(kind="rejected", error_code=code)
        return HermesDispatchResult(kind="transport_error", error_code=code)

    def _api_key(self) -> str:
        # Mirror HermesApiReadClient key loading (owner-only regular file).
        import os
        import stat
        from pathlib import Path

        path_value = getattr(self.settings, "api_key_file", None)
        if path_value is None:
            raise HermesDispatchAdapterError(
                "api_key_file_missing",
                "Hermes API key file is not configured",
            )
        path = Path(path_value)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise HermesDispatchAdapterError(
                "api_key_file_invalid",
                "Hermes API key file is unavailable",
            ) from exc
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise HermesDispatchAdapterError(
                    "api_key_file_invalid",
                    "Hermes API key file must be a regular non-symlink file",
                )
            if stat.S_IMODE(file_stat.st_mode) & 0o077:
                raise HermesDispatchAdapterError(
                    "api_key_file_permissions",
                    "Hermes API key file must be owner-only (mode 0600 or stricter)",
                )
            if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
                raise HermesDispatchAdapterError(
                    "api_key_file_owner",
                    "Hermes API key file must be owned by the current user",
                )
            raw = os.read(fd, 4097)
        except HermesDispatchAdapterError:
            raise
        except OSError as exc:
            raise HermesDispatchAdapterError(
                "api_key_file_invalid",
                "Hermes API key file is unavailable",
            ) from exc
        finally:
            os.close(fd)
        if not raw or len(raw) > 4096:
            raise HermesDispatchAdapterError(
                "api_key_invalid",
                "Hermes API key must be non-empty and bounded",
            )
        try:
            token = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise HermesDispatchAdapterError(
                "api_key_invalid",
                "Hermes API key must be valid UTF-8",
            ) from exc
        if not token or any(char in token for char in ("\r", "\n", "\x00")):
            raise HermesDispatchAdapterError(
                "api_key_invalid",
                "Hermes API key contains invalid characters",
            )
        return token

    def _base_url(self) -> str:
        from quant_system.hermes.gateway_client import (
            HermesApiReadError,
            _validated_loopback_origin,
        )

        try:
            return _validated_loopback_origin(str(getattr(self.settings, "base_url", "")))
        except HermesApiReadError as exc:
            raise HermesDispatchAdapterError(exc.code, exc.message) from exc

    def _timeout(self) -> float:
        if self.dispatch_timeout_seconds is not None:
            return float(self.dispatch_timeout_seconds)
        configured = getattr(self.settings, "dispatch_timeout_seconds", None)
        if configured is not None:
            return float(configured)
        # Runs can take tens of seconds; do not reuse the 2s read timeout.
        return 120.0

    def _client(self):
        import httpx

        token = self._api_key()
        return httpx.Client(
            base_url=self._base_url(),
            timeout=httpx.Timeout(self._timeout()),
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,  # type: ignore[arg-type]
            headers={
                "accept": "application/json",
                "authorization": f"Bearer {token}",
            },
        )

    def _get_json(self, path: str) -> dict[str, object]:
        import httpx

        try:
            with self._client() as client:
                response = client.get(path)
        except httpx.TimeoutException as exc:
            raise HermesDispatchAdapterError(
                "upstream_timeout",
                "Hermes API did not answer within the configured timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise HermesDispatchAdapterError(
                "upstream_unavailable",
                "Hermes API is unavailable on the configured loopback endpoint",
            ) from exc
        return self._parse_json_response(response, allow_statuses=frozenset({200}))

    def _post_run(
        self,
        *,
        input_text: str,
        idempotency_key: str,
        session_id: str | None,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        import httpx

        body: dict[str, object] = {"input": input_text, "metadata": metadata}
        if session_id is not None:
            body["session_id"] = session_id
        headers = {"Idempotency-Key": idempotency_key, "content-type": "application/json"}
        try:
            with self._client() as client:
                response = client.post("/v1/runs", json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise HermesDispatchAdapterError(
                "upstream_timeout",
                "Hermes API did not answer within the configured timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise HermesDispatchAdapterError(
                "upstream_unavailable",
                "Hermes API is unavailable on the configured loopback endpoint",
            ) from exc

        if response.status_code in {200, 201, 202}:
            return self._parse_json_response(
                response, allow_statuses=frozenset({200, 201, 202})
            )
        if response.status_code == 401:
            raise HermesDispatchAdapterError(
                "upstream_auth_failed",
                "Hermes API rejected the configured server credential",
            )
        if response.status_code == 409:
            raise HermesDispatchAdapterError(
                "idempotency_conflict",
                "Hermes API reported an idempotency conflict",
            )
        if response.status_code == 400:
            raise HermesDispatchAdapterError(
                "invalid_request",
                "Hermes API rejected the run submission",
            )
        if response.status_code in {422, 429}:
            raise HermesDispatchAdapterError(
                "upstream_rejected",
                "Hermes API rejected the run submission",
            )
        raise HermesDispatchAdapterError(
            "upstream_error",
            "Hermes API returned an unavailable response",
        )

    def _parse_json_response(
        self,
        response: object,
        *,
        allow_statuses: frozenset[int],
    ) -> dict[str, object]:
        status = int(getattr(response, "status_code", 0))
        if status not in allow_statuses:
            raise HermesDispatchAdapterError(
                "upstream_error",
                "Hermes API returned an unavailable response",
            )
        try:
            document = response.json()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            raise HermesDispatchAdapterError(
                "invalid_upstream_response",
                "Hermes API returned an invalid JSON response",
            ) from exc
        if not isinstance(document, dict):
            raise HermesDispatchAdapterError(
                "invalid_upstream_response",
                "Hermes API returned an invalid response envelope",
            )
        return document  # type: ignore[return-value]


def _as_nonempty_str(value: object) -> str | None:
    if type(value) is not str:
        return None
    text = value.strip()
    if not text or len(text) > 256:
        return None
    return text


def build_http_dispatch_adapter(
    settings: object,
    *,
    input_resolver: Callable[[HermesDispatchRequest], str] | None = None,
    allow_ephemeral_runs: bool | None = None,
    transport: object | None = None,
    fixed_input: str | None = None,
) -> HttpHermesDispatchAdapter:
    """Build the deprecated direct adapter; production connector never calls it."""
    gateway = getattr(settings, "hermes_gateway", settings)
    if not bool(getattr(gateway, "enabled", False)):
        raise HermesDispatchAdapterError(
            "integration_disabled",
            "Hermes gateway integration is disabled",
        )
    if allow_ephemeral_runs is None:
        allow_ephemeral_runs = bool(getattr(gateway, "allow_ephemeral_runs", False))
    resolver: Callable[[HermesDispatchRequest], str]
    if fixed_input is not None:
        resolver = fixed_input_resolver(fixed_input)
    elif input_resolver is not None:
        resolver = input_resolver
    else:
        resolver = metadata_input_resolver
    timeout = getattr(gateway, "dispatch_timeout_seconds", None)
    return HttpHermesDispatchAdapter(
        settings=gateway,
        input_resolver=resolver,
        allow_ephemeral_runs=bool(allow_ephemeral_runs),
        transport=transport,
        dispatch_timeout_seconds=float(timeout) if timeout is not None else None,
    )


__all__ = [
    "FakeHermesDispatchAdapter",
    "HermesDispatchAdapterError",
    "HermesDispatchPort",
    "HermesDispatchRequest",
    "HermesDispatchResult",
    "HermesRunObservation",
    "HttpHermesDispatchAdapter",
    "RunLifecyclePort",
    "build_http_dispatch_adapter",
    "evidence_digest_for",
    "fixed_input_resolver",
    "metadata_input_resolver",
]
