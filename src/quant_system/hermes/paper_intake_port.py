"""Fail-closed platform port to HQA's paper-intake verifier.

This module never imports HQA.  It sends one bounded metadata-only request to
``python -m hqa.paper_intake_cli verify`` and accepts only an exact receipt
bound to the command, Run, replay digest, and source digest.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from quant_system.hermes.command_ledger import HermesCommand
from quant_system.hermes.dark_identity_profile import (
    STORE_OWNER_ID,
    normalize_payload_ref,
)
from quant_system.hermes.dispatch_adapter import HermesRunObservation
from quant_system.hermes.intent_payload_port import IntentPayloadCliSettings
from quant_system.hermes.run_lifecycle_port import HermesRunCliSettings

PaperIntakeDisposition = Literal["accepted", "not_required"]
PaperIntakeCliSettings = HermesRunCliSettings | IntentPayloadCliSettings
_STDIN_LIMIT = 64_000
_STDOUT_LIMIT = 64_000
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_RECEIPT_RE = re.compile(r"paper-intake-receipt:sha256:([0-9a-f]{64})\Z")
_ACCEPTED_FIELDS = {
    "ok",
    "schema_version",
    "disposition",
    "command_id",
    "payload_ref",
    "hermes_session_id",
    "hermes_run_id",
    "observation_evidence_digest",
    "execution_contract_digest",
    "research_claim_digest",
    "discovery_mode",
    "search_result_count",
    "search_results_digest",
    "full_text_mode",
    "full_text_bytes",
    "full_text_sha256",
    "paper_url_sha256",
    "paper_identity_sha256",
    "source_file_ref",
    "source_bytes",
    "source_sha256",
    "receipt_ref",
    "receipt_digest",
}
_NOT_REQUIRED_FIELDS = {
    "ok",
    "disposition",
    "command_id",
    "payload_ref",
    "hermes_run_id",
}
_PREPARE_REQUEST_FIELDS = {
    "schema_version",
    "kind",
    "owner_id",
    "workspace_id",
    "session_id",
    "client_intent_id",
    "provider_policy",
    "prompt",
    "ttl_days",
    "paper_title",
    "universe",
}
_PREPARED_FIELDS = {
    "ok",
    "schema_version",
    "payload_ref",
    "payload_digest",
    "kind",
    "client_intent_id",
    "provider_policy_digest",
    "created_at",
    "expires_at",
    "ttl_days",
    "status",
    "research_claim_digest",
    "execution_contract_digest",
}


class PaperIntakePortError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class PaperIntakeVerification:
    disposition: PaperIntakeDisposition
    receipt_digest: str | None = None
    source_sha256: str | None = None


class PaperIntakeVerificationPort(Protocol):
    def verify(
        self,
        command: HermesCommand,
        observation: HermesRunObservation,
    ) -> PaperIntakeVerification: ...


class PaperIntakePreparationPort(Protocol):
    def prepare(self, request: Mapping[str, object]) -> dict[str, object]: ...


def _canonical_bytes(document: Mapping[str, object]) -> bytes:
    try:
        raw = json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperIntakePortError(
            "paper_intake_invalid_request",
            "paper intake verifier request is invalid",
            retryable=False,
        ) from exc
    if not raw or len(raw) > _STDIN_LIMIT:
        raise PaperIntakePortError(
            "paper_intake_invalid_request",
            "paper intake verifier request is oversized",
            retryable=False,
        )
    return raw


def _parse_stdout(raw: bytes) -> dict[str, object]:
    if not raw or len(raw) > _STDOUT_LIMIT:
        raise PaperIntakePortError(
            "paper_intake_cli_invalid_receipt",
            "paper intake verifier returned invalid output",
            retryable=True,
        )
    try:
        text = raw.decode("utf-8", errors="strict").strip()
        if not text or "\n" in text:
            raise ValueError
        document = json.loads(
            text,
            object_pairs_hook=lambda pairs: _unique_object(pairs),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise PaperIntakePortError(
            "paper_intake_cli_invalid_receipt",
            "paper intake verifier returned invalid output",
            retryable=True,
        ) from exc
    if not isinstance(document, dict):
        raise PaperIntakePortError(
            "paper_intake_cli_invalid_receipt",
            "paper intake verifier returned invalid output",
            retryable=True,
        )
    return document


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON field")
        document[key] = value
    return document


def _error_document(document: Mapping[str, object]) -> PaperIntakePortError:
    error = document.get("error")
    if not isinstance(error, Mapping):
        return PaperIntakePortError(
            "paper_intake_cli_invalid_receipt",
            "paper intake verifier failed without a receipt",
            retryable=True,
        )
    code = error.get("code")
    retryable = error.get("retryable")
    if (
        type(code) is not str
        or not code.startswith("paper_intake_")
        or len(code) > 100
        or type(retryable) is not bool
    ):
        return PaperIntakePortError(
            "paper_intake_cli_invalid_receipt",
            "paper intake verifier failed without a receipt",
            retryable=True,
        )
    return PaperIntakePortError(
        code,
        "paper intake verification did not pass",
        retryable=retryable,
    )


def _is_digest(value: object) -> bool:
    return type(value) is str and _DIGEST_RE.fullmatch(value) is not None


@dataclass
class SubprocessPaperIntakePreparationPort:
    """Create one encrypted, contract-bound paper intent through HQA."""

    cli_settings: PaperIntakeCliSettings
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None

    def prepare(self, request: Mapping[str, object]) -> dict[str, object]:
        if set(request) != _PREPARE_REQUEST_FIELDS:
            raise PaperIntakePortError(
                "paper_intake_invalid_request",
                "paper intake preparation request is invalid",
                retryable=False,
            )
        python = self.cli_settings.python_executable
        hqa_root = self.cli_settings.hqa_root
        if not python.is_file() or not hqa_root.is_dir():
            raise PaperIntakePortError(
                "paper_intake_cli_unavailable",
                "paper intake preparation is unavailable",
                retryable=True,
            )
        env = os.environ.copy()
        root = str(hqa_root)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = root if not existing else root + os.pathsep + existing
        argv = [str(python), "-m", "hqa.paper_intake_cli", "prepare"]
        run = self.runner or subprocess.run
        try:
            completed = run(
                argv,
                input=_canonical_bytes(request),
                capture_output=True,
                timeout=min(float(self.cli_settings.timeout_seconds), 30.0),
                check=False,
                cwd=str(hqa_root),
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PaperIntakePortError(
                "paper_intake_cli_timeout",
                "paper intake preparation timed out",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise PaperIntakePortError(
                "paper_intake_cli_unavailable",
                "paper intake preparation could not start",
                retryable=True,
            ) from exc
        document = _parse_stdout(completed.stdout or b"")
        if completed.returncode != 0 or document.get("ok") is not True:
            raise _error_document(document)
        return self._validate_receipt(document, request=request)

    @staticmethod
    def _validate_receipt(
        document: Mapping[str, object],
        *,
        request: Mapping[str, object],
    ) -> dict[str, object]:
        payload_digest = document.get("payload_digest")
        payload_ref = document.get("payload_ref")
        try:
            policy_digest = hashlib.sha256(
                json.dumps(
                    request.get("provider_policy"),
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8", errors="strict")
            ).hexdigest()
        except (TypeError, ValueError, UnicodeError) as exc:
            raise PaperIntakePortError(
                "paper_intake_invalid_request",
                "paper intake preparation request is invalid",
                retryable=False,
            ) from exc
        if (
            set(document) != _PREPARED_FIELDS
            or document.get("schema_version") != "2.0"
            or document.get("kind") != "paper_intake"
            or document.get("client_intent_id") != request.get("client_intent_id")
            or not _is_digest(payload_digest)
            or payload_ref != f"payload:sha256:{payload_digest}"
            or document.get("provider_policy_digest") != policy_digest
            or document.get("ttl_days") != request.get("ttl_days")
            or document.get("status") != "active"
            or not _is_digest(document.get("research_claim_digest"))
            or not _is_digest(document.get("execution_contract_digest"))
            or type(document.get("created_at")) is not str
            or type(document.get("expires_at")) is not str
        ):
            raise PaperIntakePortError(
                "paper_intake_cli_invalid_receipt",
                "paper intake preparation returned an invalid receipt",
                retryable=False,
            )
        return dict(document)


@dataclass
class SubprocessPaperIntakeVerificationPort:
    cli_settings: HermesRunCliSettings
    workspace_id: str
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None

    def verify(
        self,
        command: HermesCommand,
        observation: HermesRunObservation,
    ) -> PaperIntakeVerification:
        if (
            not observation.is_terminal
            or observation.status != "succeeded"
            or not observation.replay_complete
            or not _is_digest(observation.evidence_digest)
            or observation.hermes_run_id != command.hermes_run_id
            or observation.hermes_session_id != command.resolved_hermes_session_id
        ):
            raise PaperIntakePortError(
                "paper_intake_invalid_request",
                "paper intake verifier identity is invalid",
                retryable=False,
            )
        payload_ref = normalize_payload_ref(command.payload_ref)
        endpoint = self.cli_settings.endpoint_document()
        endpoint["timeout_seconds"] = min(
            float(self.cli_settings.timeout_seconds),
            30.0,
        )
        request = {
            "endpoint": endpoint,
            "owner_id": STORE_OWNER_ID,
            "workspace_id": self.workspace_id,
            "platform_session_id": command.platform_session_id,
            "command_id": str(command.command_id),
            "payload_ref": payload_ref,
            "hermes_session_id": observation.hermes_session_id,
            "hermes_run_id": observation.hermes_run_id,
            "observation_evidence_digest": observation.evidence_digest,
        }
        python = self.cli_settings.python_executable
        hqa_root = self.cli_settings.hqa_root
        if not python.is_file() or not hqa_root.is_dir():
            raise PaperIntakePortError(
                "paper_intake_cli_unavailable",
                "paper intake verifier is unavailable",
                retryable=True,
            )
        env = os.environ.copy()
        root = str(hqa_root)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = root if not existing else root + os.pathsep + existing
        argv = [str(python), "-m", "hqa.paper_intake_cli", "verify"]
        run = self.runner or subprocess.run
        try:
            completed = run(
                argv,
                input=_canonical_bytes(request),
                capture_output=True,
                timeout=min(float(self.cli_settings.timeout_seconds), 30.0),
                check=False,
                cwd=str(hqa_root),
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PaperIntakePortError(
                "paper_intake_cli_timeout",
                "paper intake verifier timed out",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise PaperIntakePortError(
                "paper_intake_cli_unavailable",
                "paper intake verifier could not start",
                retryable=True,
            ) from exc
        document = _parse_stdout(completed.stdout or b"")
        if completed.returncode != 0 or document.get("ok") is not True:
            raise _error_document(document)
        return self._validate_receipt(
            document,
            command=command,
            observation=observation,
            payload_ref=payload_ref,
        )

    @staticmethod
    def _validate_receipt(
        document: Mapping[str, object],
        *,
        command: HermesCommand,
        observation: HermesRunObservation,
        payload_ref: str,
    ) -> PaperIntakeVerification:
        disposition = document.get("disposition")
        if disposition == "not_required":
            if (
                set(document) != _NOT_REQUIRED_FIELDS
                or document.get("command_id") != str(command.command_id)
                or document.get("payload_ref") != payload_ref
                or document.get("hermes_run_id") != observation.hermes_run_id
            ):
                raise PaperIntakePortError(
                    "paper_intake_cli_invalid_receipt",
                    "paper intake verifier substituted identity",
                    retryable=False,
                )
            return PaperIntakeVerification(disposition="not_required")
        if disposition != "accepted" or set(document) != _ACCEPTED_FIELDS:
            raise PaperIntakePortError(
                "paper_intake_cli_invalid_receipt",
                "paper intake verifier returned an invalid receipt",
                retryable=False,
            )
        receipt_ref = document.get("receipt_ref")
        receipt_digest = document.get("receipt_digest")
        receipt_match = _RECEIPT_RE.fullmatch(receipt_ref) if type(receipt_ref) is str else None
        digest_fields = {
            "observation_evidence_digest",
            "execution_contract_digest",
            "research_claim_digest",
            "full_text_sha256",
            "paper_url_sha256",
            "paper_identity_sha256",
            "source_sha256",
            "receipt_digest",
        }
        optional_digest = document.get("search_results_digest")
        if (
            document.get("schema_version") != "hqa.paper_intake/v1"
            or document.get("command_id") != str(command.command_id)
            or document.get("payload_ref") != payload_ref
            or document.get("hermes_session_id") != observation.hermes_session_id
            or document.get("hermes_run_id") != observation.hermes_run_id
            or document.get("observation_evidence_digest") != observation.evidence_digest
            or any(not _is_digest(document.get(field)) for field in digest_fields)
            or optional_digest is not None
            and not _is_digest(optional_digest)
            or receipt_match is None
            or receipt_match.group(1) != receipt_digest
            or document.get("discovery_mode") not in {"web_search", "user_url"}
            or document.get("full_text_mode") not in {"direct_pdf", "web_extract"}
            or type(document.get("search_result_count")) is not int
            or int(document["search_result_count"]) < 0
            or type(document.get("full_text_bytes")) is not int
            or int(document["full_text_bytes"]) < 4096
            or type(document.get("source_bytes")) is not int
            or int(document["source_bytes"]) <= 0
            or type(document.get("source_file_ref")) is not str
            or not str(document["source_file_ref"]).startswith("/")
        ):
            raise PaperIntakePortError(
                "paper_intake_cli_invalid_receipt",
                "paper intake verifier substituted identity",
                retryable=False,
            )
        return PaperIntakeVerification(
            disposition="accepted",
            receipt_digest=str(receipt_digest),
            source_sha256=str(document["source_sha256"]),
        )


@dataclass
class FakePaperIntakeVerificationPort:
    decision: PaperIntakeVerification = field(
        default_factory=lambda: PaperIntakeVerification(disposition="not_required")
    )
    error: PaperIntakePortError | None = None
    calls: list[tuple[HermesCommand, HermesRunObservation]] = field(default_factory=list)

    def verify(
        self,
        command: HermesCommand,
        observation: HermesRunObservation,
    ) -> PaperIntakeVerification:
        self.calls.append((command, observation))
        if self.error is not None:
            raise self.error
        return self.decision


__all__ = [
    "FakePaperIntakeVerificationPort",
    "PaperIntakePortError",
    "PaperIntakePreparationPort",
    "PaperIntakeVerification",
    "PaperIntakeVerificationPort",
    "SubprocessPaperIntakePreparationPort",
    "SubprocessPaperIntakeVerificationPort",
]
