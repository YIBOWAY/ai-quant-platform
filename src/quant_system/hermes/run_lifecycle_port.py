"""Subprocess boundary to HQA's canonical durable Hermes Run authority.

The sibling orchestration repository owns ``hqa.hermes_run_cli``.  This module
never imports HQA; it exchanges one bounded JSON object over stdin/stdout and
keeps prompts/API credentials out of argv and log-safe exceptions.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from quant_system.hermes.compatibility_contract import (
    HermesCompatibilityContract,
    load_hermes_compatibility_contract,
)
from quant_system.hermes.dispatch_adapter import (
    HermesDispatchRequest,
    HermesDispatchResult,
    HermesRunObservation,
    RunLifecycleStatus,
    evidence_digest_for,
)
from quant_system.hermes.intent_payload_port import (
    IntentPayloadPortError,
    ResolvedIntentPayload,
)

_STDIN_LIMIT = 1_200_000
_STDOUT_LIMIT = 4_194_304
_IDENTIFIER_MAX = 512
_CAPABILITY_HTTP_TIMEOUT_SECONDS = 5.0
_CAPABILITY_PROCESS_TIMEOUT_SECONDS = 7.0


class HermesRunPortError(RuntimeError):
    """Secret-free structured failure at the platform/HQA process boundary."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class HermesRunCliSettings:
    python_executable: Path
    hqa_root: Path
    base_url: str
    api_key: str | None
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not _is_loopback_origin(self.base_url):
            raise ValueError("Hermes durable Run endpoint must be loopback")
        if not 0.1 <= float(self.timeout_seconds) <= 600.0:
            raise ValueError("Hermes durable Run timeout must be in [0.1, 600]")
        if self.api_key is not None and (
            not self.api_key
            or any(char in self.api_key for char in ("\r", "\n", "\x00"))
        ):
            raise ValueError("Hermes API key is invalid")

    def endpoint_document(self) -> dict[str, object]:
        endpoint: dict[str, object] = {
            "base_url": self.base_url,
            "timeout_seconds": float(self.timeout_seconds),
        }
        if self.api_key is not None:
            endpoint["api_key"] = self.api_key
        return endpoint


@dataclass(frozen=True)
class HermesRunCompatibilityReceipt:
    """Bounded, secret-free proof that the real HQA subprocess is compatible."""

    hermes_contract_version: int
    cli_operations: tuple[str, ...]
    evidence_digest: str


@dataclass
class SubprocessHermesRunLifecyclePort:
    """Durable submit/recover and observation through ``hermes_run_cli``."""

    cli_settings: HermesRunCliSettings
    input_resolver: Callable[
        [HermesDispatchRequest], str | ResolvedIntentPayload
    ]
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None

    def require_compatible_capabilities(
        self,
        contract: HermesCompatibilityContract | None = None,
    ) -> HermesRunCompatibilityReceipt:
        """Probe HQA itself and validate its exact CLI/Hermes contract."""

        if contract is None:
            try:
                compatibility = load_hermes_compatibility_contract()
            except Exception as exc:  # noqa: BLE001 - normalize manifest details
                raise HermesRunPortError(
                    "run_cli_contract_unavailable",
                    "Hermes durable Run compatibility contract is unavailable",
                    retryable=False,
                ) from exc
        else:
            compatibility = contract
        document = self._invoke("capabilities", {})
        return _validate_compatibility_receipt(document, compatibility)

    def capabilities(self) -> Mapping[str, object]:
        try:
            document = self._invoke("capabilities", {})
        except HermesRunPortError as exc:
            return {
                "features": {"run_submission": False},
                "error_code": exc.code,
            }
        capabilities = document.get("capabilities")
        return dict(capabilities) if isinstance(capabilities, Mapping) else {}

    def submit_or_recover(
        self,
        request: HermesDispatchRequest,
    ) -> HermesDispatchResult:
        session_id = request.hermes_session_id
        if not _is_identifier(session_id) or not str(session_id).startswith("web_"):
            return HermesDispatchResult(
                kind="rejected",
                error_code="managed_session_required",
                network_attempted=False,
            )
        try:
            resolved = self.input_resolver(request)
            if isinstance(resolved, ResolvedIntentPayload):
                prompt = resolved.prompt
            else:
                prompt = resolved
                resolved = ResolvedIntentPayload(prompt=prompt)
            if type(prompt) is not str or not prompt or len(prompt.encode("utf-8")) > 16_384:
                raise HermesRunPortError(
                    "payload_input_invalid",
                    "resolved prompt is invalid",
                    retryable=False,
                )
            metadata: dict[str, object] = {
                "command_id": request.command_id,
                "kind": request.kind,
                "client_request_id": request.client_request_id,
                "platform_session_id": request.platform_session_id,
                "canonical_request_digest": request.canonical_request_digest,
                "payload_ref": request.payload_ref,
                "source": "platform.hqa_hermes_run_port",
            }
            request_body: dict[str, object] = {
                "input": prompt,
                "session_id": session_id,
                "metadata": metadata,
            }
            if resolved.kind == "paper_intake":
                if (
                    resolved.execution_contract is None
                    or resolved.execution_contract_digest is None
                    or resolved.research_claim_digest is None
                    or resolved.execution_instructions is None
                ):
                    raise HermesRunPortError(
                        "payload_input_invalid",
                        "paper intake dispatch contract is incomplete",
                        retryable=False,
                    )
                metadata.update(
                    {
                        "execution_contract": "hqa.paper_intake/v1",
                        "execution_contract_digest": (
                            resolved.execution_contract_digest
                        ),
                        "research_claim_digest": resolved.research_claim_digest,
                    }
                )
                request_body["instructions"] = resolved.execution_instructions
            document = self._invoke(
                "submit",
                {
                    "idempotency_key": request.idempotency_key(),
                    "request_body": request_body,
                },
            )
        except HermesRunPortError as exc:
            if exc.code in {"durable_unavailable", "run_cli_unavailable"}:
                kind = "unavailable"
            elif exc.retryable:
                kind = "transport_error"
            else:
                kind = "rejected"
            return HermesDispatchResult(
                kind=kind,
                error_code=exc.code,
                network_attempted=exc.code not in {
                    "durable_unavailable",
                    "run_cli_unavailable",
                    "payload_input_invalid",
                },
            )
        except IntentPayloadPortError as exc:
            return HermesDispatchResult(
                kind="unavailable" if exc.retryable else "rejected",
                error_code=(
                    exc.code if _is_identifier(exc.code) else "payload_resolve_failed"
                ),
                network_attempted=False,
            )
        except Exception:  # noqa: BLE001 - resolver details may contain prompt data
            return HermesDispatchResult(
                kind="rejected",
                error_code="payload_resolve_failed",
                network_attempted=False,
            )

        run_id = document.get("run_id")
        created = document.get("created")
        requested_session_id = document.get("requested_session_id")
        conversation_session_id = document.get("conversation_session_id")
        resolved_session_id = document.get("resolved_session_id")
        receipt_session_id = document.get("session_id")
        if (
            not _is_identifier(run_id)
            or type(created) is not bool
            or requested_session_id != session_id
            or conversation_session_id != session_id
            or not _is_identifier(resolved_session_id)
            or receipt_session_id != resolved_session_id
        ):
            return HermesDispatchResult(
                kind="transport_error",
                error_code="run_cli_invalid_receipt",
            )
        outcome = "accepted" if created else "recovered"
        return HermesDispatchResult(
            kind=outcome,
            conversation_hermes_session_id=str(conversation_session_id),
            hermes_session_id=str(resolved_session_id),
            hermes_run_id=str(run_id),
            evidence_digest=evidence_digest_for(
                conversation_hermes_session_id=str(conversation_session_id),
                hermes_session_id=str(resolved_session_id),
                hermes_run_id=str(run_id),
                outcome=outcome,
            ),
        )

    def observe(
        self,
        *,
        conversation_hermes_session_id: str | None = None,
        hermes_session_id: str,
        hermes_run_id: str,
        after_cursor: int = 0,
    ) -> HermesRunObservation:
        expected_conversation_session_id = (
            conversation_hermes_session_id or hermes_session_id
        )
        if (
            not _is_identifier(expected_conversation_session_id)
            or not _is_identifier(hermes_session_id)
            or not _is_identifier(hermes_run_id)
            or isinstance(after_cursor, bool)
            or after_cursor < 0
        ):
            raise HermesRunPortError(
                "run_invalid_request",
                "Run observation identity/cursor is invalid",
                retryable=False,
            )
        status_document = self._invoke("status", {"run_id": hermes_run_id})
        events_document = self._invoke(
            "events",
            {"run_id": hermes_run_id, "since_seq": after_cursor},
        )
        if (
            status_document.get("run_id") != hermes_run_id
            or status_document.get("session_id") != hermes_session_id
            or status_document.get("resolved_session_id", hermes_session_id)
            != hermes_session_id
            or status_document.get(
                "conversation_session_id",
                hermes_session_id,
            )
            != expected_conversation_session_id
            or events_document.get("run_id") != hermes_run_id
        ):
            return _unknown_observation(
                conversation_hermes_session_id=(
                    expected_conversation_session_id
                ),
                hermes_session_id=hermes_session_id,
                hermes_run_id=hermes_run_id,
                after_cursor=after_cursor,
                error_code="run_identity_mismatch",
            )

        raw_status = status_document.get("status")
        status = _map_run_status(raw_status)
        rows = events_document.get("events")
        next_cursor = events_document.get("next_seq")
        replay_complete, normalized_events = _validate_event_replay(
            rows,
            hermes_run_id=hermes_run_id,
            after_cursor=after_cursor,
            next_cursor=next_cursor,
        )
        terminal_events = {
            "succeeded": "run.completed",
            "failed": "run.failed",
            "cancelled": "run.cancelled",
        }
        if status in terminal_events:
            replay_complete = replay_complete and any(
                event.get("event_type") == terminal_events[status]
                for event in normalized_events
            )
        if status == "outcome_unknown" or not replay_complete:
            return _unknown_observation(
                conversation_hermes_session_id=(
                    expected_conversation_session_id
                ),
                hermes_session_id=hermes_session_id,
                hermes_run_id=hermes_run_id,
                after_cursor=(
                    int(next_cursor)
                    if type(next_cursor) is int and next_cursor >= after_cursor
                    else after_cursor
                ),
                error_code=(
                    "run_status_unknown"
                    if status == "outcome_unknown"
                    else "run_replay_incomplete"
                ),
            )
        evidence = {
            "status": status_document,
            "events": normalized_events,
            "next_cursor": int(next_cursor),
        }
        return HermesRunObservation(
            status=status,
            conversation_hermes_session_id=(
                expected_conversation_session_id
            ),
            hermes_session_id=hermes_session_id,
            hermes_run_id=hermes_run_id,
            evidence_digest=_evidence_digest(evidence),
            error_code=("hermes_run_failed" if status == "failed" else None),
            next_cursor=int(next_cursor),
            replay_complete=True,
        )

    def _invoke(
        self,
        operation: str,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        python = self.cli_settings.python_executable
        hqa_root = self.cli_settings.hqa_root
        if not python.is_file() or not hqa_root.is_dir():
            raise HermesRunPortError(
                "run_cli_unavailable",
                "Hermes durable Run CLI is unavailable",
                retryable=True,
            )
        endpoint = self.cli_settings.endpoint_document()
        process_timeout = self.cli_settings.timeout_seconds
        if operation == "capabilities":
            endpoint["timeout_seconds"] = min(
                float(endpoint["timeout_seconds"]),
                _CAPABILITY_HTTP_TIMEOUT_SECONDS,
            )
            process_timeout = min(
                process_timeout,
                _CAPABILITY_PROCESS_TIMEOUT_SECONDS,
            )
        document = {"endpoint": endpoint, **dict(request)}
        try:
            raw = json.dumps(
                document,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HermesRunPortError(
                "run_invalid_request",
                "Hermes durable Run request is invalid",
                retryable=False,
            ) from exc
        if not raw or len(raw) > _STDIN_LIMIT:
            raise HermesRunPortError(
                "run_invalid_request",
                "Hermes durable Run request is oversized",
                retryable=False,
            )
        env = os.environ.copy()
        root = str(hqa_root)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = root if not existing else root + os.pathsep + existing
        argv = [str(python), "-m", "hqa.hermes_run_cli", operation]
        run = self.runner or subprocess.run
        try:
            completed = run(
                argv,
                input=raw,
                capture_output=True,
                timeout=process_timeout,
                check=False,
                cwd=str(hqa_root),
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HermesRunPortError(
                "run_cli_timeout",
                "Hermes durable Run CLI timed out",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise HermesRunPortError(
                "run_cli_unavailable",
                "Hermes durable Run CLI could not start",
                retryable=True,
            ) from exc
        response = _parse_stdout(completed.stdout or b"")
        if completed.returncode != 0 or response.get("ok") is not True:
            raise _error_from_document(response)
        return response


def _parse_stdout(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > _STDOUT_LIMIT:
        raise HermesRunPortError(
            "run_cli_invalid_stdout",
            "Hermes durable Run CLI returned empty or oversized output",
            retryable=True,
        )
    try:
        text = raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise HermesRunPortError(
            "run_cli_invalid_stdout",
            "Hermes durable Run CLI returned invalid output",
            retryable=True,
        ) from exc
    if not text or "\n" in text:
        raise HermesRunPortError(
            "run_cli_invalid_stdout",
            "Hermes durable Run CLI must return one JSON object",
            retryable=True,
        )
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise HermesRunPortError(
            "run_cli_invalid_stdout",
            "Hermes durable Run CLI returned invalid JSON",
            retryable=True,
        ) from exc
    if not isinstance(document, dict):
        raise HermesRunPortError(
            "run_cli_invalid_stdout",
            "Hermes durable Run CLI returned a non-object",
            retryable=True,
        )
    return document


def _validate_compatibility_receipt(
    document: Mapping[str, object],
    contract: HermesCompatibilityContract,
) -> HermesRunCompatibilityReceipt:
    """Validate one exact HQA capability envelope without returning its body."""

    if set(document) != {
        "ok",
        "capabilities",
        "cli_contract",
        "durable_ready",
        "managed_session_ready",
    }:
        raise _compatibility_error("run_cli_contract_mismatch")
    if (
        document.get("ok") is not True
        or document.get("durable_ready") is not True
        or document.get("managed_session_ready") is not True
    ):
        raise _compatibility_error("durable_unavailable", retryable=True)

    expected_cli_contract = {
        "schema_version": contract.schema_version,
        "profile": contract.profile,
        "operations": list(contract.hqa_cli_operations),
        "write_contract": dict(contract.write_contract),
    }
    if document.get("cli_contract") != expected_cli_contract:
        raise _compatibility_error("run_cli_contract_mismatch")

    capabilities = document.get("capabilities")
    if not isinstance(capabilities, Mapping):
        raise _compatibility_error("run_cli_contract_mismatch")
    version = capabilities.get("contract_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < contract.hermes_contract_version_min
    ):
        raise _compatibility_error("hermes_contract_mismatch")

    features = capabilities.get("features")
    if not isinstance(features, Mapping):
        raise _compatibility_error("hermes_contract_mismatch")
    for name in contract.required_bool_features:
        if features.get(name) is not True:
            raise _compatibility_error("hermes_contract_mismatch")
    for name, expected in contract.required_exact_features.items():
        if features.get(name) != expected:
            raise _compatibility_error("hermes_contract_mismatch")

    durable = capabilities.get("durable")
    if not isinstance(durable, Mapping):
        raise _compatibility_error("hermes_contract_mismatch")
    for name in contract.required_durable:
        fact = durable.get(name)
        if (
            not isinstance(fact, Mapping)
            or fact.get("supported") is not True
            or fact.get("grounded") is not True
            or fact.get("evidence")
            != contract.durable_evidence_template.format(capability=name)
        ):
            raise _compatibility_error("hermes_contract_mismatch")

    evidence = {
        "capabilities": dict(capabilities),
        "cli_contract": expected_cli_contract,
    }
    return HermesRunCompatibilityReceipt(
        hermes_contract_version=version,
        cli_operations=contract.hqa_cli_operations,
        evidence_digest=_evidence_digest(evidence),
    )


def _compatibility_error(
    code: str,
    *,
    retryable: bool = False,
) -> HermesRunPortError:
    return HermesRunPortError(
        code,
        "Hermes durable Run compatibility preflight failed",
        retryable=retryable,
    )


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON field")
        document[key] = value
    return document


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _error_from_document(document: Mapping[str, object]) -> HermesRunPortError:
    error = document.get("error")
    if not isinstance(error, Mapping):
        return HermesRunPortError(
            "run_cli_failed",
            "Hermes durable Run CLI failed",
            retryable=True,
        )
    code = error.get("code")
    return HermesRunPortError(
        str(code) if _is_identifier(code) else "run_cli_failed",
        # The sibling CLI promises secret-free errors, but this boundary must
        # keep that guarantee even if a drifted implementation echoes prompt
        # text or credentials in its message field.
        "Hermes durable Run CLI failed",
        retryable=error.get("retryable") is True,
    )


def _is_identifier(value: object) -> bool:
    return type(value) is str and 1 <= len(value) <= _IDENTIFIER_MAX and value.isprintable()


def _map_run_status(value: object) -> RunLifecycleStatus:
    if value in {"queued", "pending", "accepted", "created"}:
        return "accepted"
    if value in {"running", "in_progress", "waiting_approval"}:
        return "running"
    if value in {"succeeded", "completed"}:
        return "succeeded"
    if value == "failed":
        return "failed"
    if value in {"stopped", "cancelled"}:
        return "cancelled"
    return "outcome_unknown"


def _validate_event_replay(
    rows: object,
    *,
    hermes_run_id: str,
    after_cursor: int,
    next_cursor: object,
) -> tuple[bool, list[dict[str, object]]]:
    if not isinstance(rows, list) or type(next_cursor) is not int:
        return False, []
    if next_cursor < after_cursor:
        return False, []
    expected = after_cursor + 1
    normalized: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            return False, []
        seq = row.get("seq")
        if type(seq) is not int or seq != expected:
            return False, []
        if row.get("run_id") != hermes_run_id:
            return False, []
        event_type = row.get("event_type")
        if not _is_identifier(event_type):
            return False, []
        normalized.append(dict(row))
        expected += 1
    observed_next = expected - 1 if normalized else after_cursor
    return next_cursor == observed_next, normalized


def _unknown_observation(
    *,
    conversation_hermes_session_id: str,
    hermes_session_id: str,
    hermes_run_id: str,
    after_cursor: int,
    error_code: str,
) -> HermesRunObservation:
    return HermesRunObservation(
        status="outcome_unknown",
        conversation_hermes_session_id=conversation_hermes_session_id,
        hermes_session_id=hermes_session_id,
        hermes_run_id=hermes_run_id,
        error_code=error_code,
        next_cursor=after_cursor,
        replay_complete=False,
    )


def _evidence_digest(document: object) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def build_subprocess_run_lifecycle_port(
    settings: object,
    *,
    input_resolver: Callable[
        [HermesDispatchRequest], str | ResolvedIntentPayload
    ],
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> SubprocessHermesRunLifecyclePort:
    """Build the production HQA subprocess port from existing platform config."""

    from quant_system.hermes.intent_payload_port import (
        IntentPayloadCliSettings,
        IntentPayloadPortError,
    )

    gateway = getattr(settings, "hermes_gateway", None)
    if gateway is None or getattr(gateway, "enabled", False) is not True:
        raise HermesRunPortError(
            "integration_disabled",
            "Hermes gateway integration is disabled",
            retryable=False,
        )
    try:
        process = IntentPayloadCliSettings.from_settings(settings)
    except IntentPayloadPortError as exc:
        raise HermesRunPortError(
            "run_port_misconfigured",
            "Hermes durable Run process settings are invalid",
            retryable=False,
        ) from exc
    timeout = getattr(gateway, "dispatch_timeout_seconds", 120.0)
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError) as exc:
        raise HermesRunPortError(
            "run_port_misconfigured",
            "Hermes durable Run timeout is invalid",
            retryable=False,
        ) from exc
    api_key = _read_api_key(getattr(gateway, "api_key_file", None))
    try:
        cli_settings = HermesRunCliSettings(
            python_executable=process.python_executable,
            hqa_root=process.hqa_root,
            base_url=str(getattr(gateway, "base_url", "")),
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as exc:
        raise HermesRunPortError(
            "run_port_misconfigured",
            "Hermes durable Run settings are invalid",
            retryable=False,
        ) from exc
    return SubprocessHermesRunLifecyclePort(
        cli_settings=cli_settings,
        input_resolver=input_resolver,
        runner=runner,
    )


def _read_api_key(path_value: object) -> str | None:
    if path_value in (None, ""):
        return None
    try:
        path = Path(path_value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise HermesRunPortError(
            "run_port_misconfigured",
            "Hermes API key file is invalid",
            retryable=False,
        ) from exc
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise HermesRunPortError(
            "run_cli_unavailable",
            "Hermes API key file is unavailable",
            retryable=True,
        ) from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise HermesRunPortError(
                "run_port_misconfigured",
                "Hermes API key file must be owner-only",
                retryable=False,
            )
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise HermesRunPortError(
                "run_port_misconfigured",
                "Hermes API key file owner is invalid",
                retryable=False,
            )
        raw = os.read(fd, 4097)
    finally:
        os.close(fd)
    if not raw or len(raw) > 4096:
        raise HermesRunPortError(
            "run_port_misconfigured",
            "Hermes API key is invalid",
            retryable=False,
        )
    try:
        token = raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise HermesRunPortError(
            "run_port_misconfigured",
            "Hermes API key is invalid",
            retryable=False,
        ) from exc
    if not token or any(char in token for char in ("\r", "\n", "\x00")):
        raise HermesRunPortError(
            "run_port_misconfigured",
            "Hermes API key is invalid",
            retryable=False,
        )
    return token


def _is_loopback_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except (TypeError, ValueError):
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.query == ""
        and parsed.fragment == ""
        and parsed.path in {"", "/"}
    )


__all__ = [
    "HermesRunCompatibilityReceipt",
    "HermesRunCliSettings",
    "HermesRunPortError",
    "SubprocessHermesRunLifecyclePort",
    "build_subprocess_run_lifecycle_port",
]
