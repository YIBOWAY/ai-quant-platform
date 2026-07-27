"""Fixed subprocess seam from Platform to HQA paper-research human gates.

Platform never imports ``hqa``.  The only production argv shapes are:

``python -m hqa.paper_gate_cli confirm-formula|approve|promote``

Exact action values travel in strict JSON stdin.  Source bytes, human notes,
prompts, credentials, and provider secrets never enter argv or Platform logs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quant_system.config.runtime_paths import (
    is_unconfigured_runtime_path,
    unconfigured_runtime_path,
)

PaperGateOperation = Literal["confirm-formula", "approve", "promote"]

_OPERATIONS = frozenset({"confirm-formula", "approve", "promote"})
_STDIN_LIMIT = 64_000
_STDOUT_LIMIT = 256_000
_DEFAULT_TIMEOUT_SECONDS = 120.0
_SAFE_BASE_ENV = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "SSL_CERT_FILE",
        "TMPDIR",
    }
)
_SAFE_HQA_ENV = frozenset(
    {
        "HQA_FACTOR_EXPERIMENT_OUTPUT_DIR",
        "HQA_FACTOR_GATE1_DIR",
        "HQA_RUNTIME_DIR",
        "HQA_WORKFLOW_AUTHORITY_DIR",
        "HQA_WORKFLOW_OWNER_USER_ID",
    }
)
_SAFE_QS_ENV = frozenset({"QS_AGENT_OUTPUT_DIR", "QS_DATA_DIR"})
_MANAGED_SESSION_REF_RE = re.compile(r"^session:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_WORKFLOW_EVENT_RE = re.compile(r"^event:[0-9a-f]{64}$")


class PaperGatePortError(RuntimeError):
    """Secret-free failure from the HQA paper-gate subprocess."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = bool(retryable)


@dataclass(frozen=True)
class PaperGateCliSettings:
    python_executable: Path
    hqa_root: Path
    platform_root: Path
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_settings(cls, settings: object | None) -> PaperGateCliSettings:
        block = getattr(settings, "intent_payload", None)
        hqa_raw = getattr(block, "hqa_root", None)
        hqa_root = (
            Path(hqa_raw)
            if hqa_raw not in (None, "")
            else unconfigured_runtime_path("hqa-runtime-root")
        )
        python_raw = getattr(block, "python_executable", None)
        python = (
            Path(python_raw)
            if python_raw not in (None, "")
            else unconfigured_runtime_path("hqa-python-executable")
        )
        release_block = getattr(settings, "agent_v02_release", None)
        platform_raw = getattr(release_block, "platform_runtime_root", None)
        platform_root = (
            Path(platform_raw)
            if platform_raw not in (None, "")
            else unconfigured_runtime_path("platform-runtime-root")
        )
        timeout_raw = getattr(block, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise PaperGatePortError(
                "paper_gate_port_misconfigured",
                "timeout_seconds must be numeric",
                retryable=False,
            ) from exc
        if not 0 < timeout <= 300:
            raise PaperGatePortError(
                "paper_gate_port_misconfigured",
                "timeout_seconds must be in (0, 300]",
                retryable=False,
            )
        return cls(
            python_executable=python,
            hqa_root=hqa_root,
            platform_root=platform_root,
            timeout_seconds=timeout,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise PaperGatePortError(
                "paper_gate_outcome_unknown",
                "HQA paper gate returned duplicate JSON fields",
                retryable=False,
            )
        document[key] = value
    return document


def _reject_constant(_value: str) -> None:
    raise PaperGatePortError(
        "paper_gate_outcome_unknown",
        "HQA paper gate returned non-finite JSON",
        retryable=False,
    )


def _encode_request(request: Mapping[str, Any]) -> bytes:
    try:
        raw = json.dumps(
            dict(request),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise PaperGatePortError(
            "paper_gate_invalid_request",
            "paper gate request is not strict JSON",
            retryable=False,
        ) from exc
    if not raw or len(raw) > _STDIN_LIMIT:
        raise PaperGatePortError(
            "paper_gate_invalid_request",
            "paper gate request exceeds stdin limit",
            retryable=False,
        )
    return raw


def _require_managed_session_ref(request: Mapping[str, Any]) -> str:
    reference = request.get("managed_session_ref")
    if type(reference) is not str or _MANAGED_SESSION_REF_RE.fullmatch(reference) is None:
        raise PaperGatePortError(
            "paper_gate_invalid_request",
            "paper gate request requires an exact managed Session reference",
            retryable=False,
        )
    return reference


def _parse_stdout(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > _STDOUT_LIMIT:
        raise PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate returned empty or oversized stdout",
            retryable=False,
        )
    try:
        text = raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate stdout is not UTF-8",
            retryable=False,
        ) from exc
    if not text or "\n" in text:
        raise PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate must return exactly one JSON object",
            retryable=False,
        )
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except PaperGatePortError:
        raise
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate stdout is invalid JSON",
            retryable=False,
        ) from exc
    if not isinstance(document, dict):
        raise PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate stdout must be an object",
            retryable=False,
        )
    return document


def _error_from_document(document: Mapping[str, Any]) -> PaperGatePortError:
    error = document.get("error")
    if not isinstance(error, Mapping):
        return PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate failed without structured error",
            retryable=False,
        )
    code = error.get("code")
    retryable = error.get("retryable")
    return PaperGatePortError(
        code if type(code) is str and code else "paper_gate_failed",
        "HQA paper gate rejected the operation",
        retryable=retryable is True,
    )


def _validate_receipt(
    operation: PaperGateOperation,
    request: Mapping[str, Any],
    document: Mapping[str, Any],
) -> dict[str, Any]:
    if document.get("ok") is not True:
        raise _error_from_document(document)
    operation_id = request.get("operation_id")
    expected_ref = f"hqa-paper-gate:{operation_id}" if type(operation_id) is str else None
    digest = document.get("hqa_receipt_digest")
    managed_session_ref = _require_managed_session_ref(request)
    if (
        document.get("operation_id") != operation_id
        or document.get("managed_session_ref") != managed_session_ref
        or document.get("hqa_receipt_ref") != expected_ref
        or type(digest) is not str
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        raise PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate substituted receipt identity",
            retryable=False,
        )
    if operation == "confirm-formula":
        valid = (
            document.get("task_ref") == request.get("task_ref")
            and document.get("gate_ref") == request.get("gate_ref")
            and document.get("reviewed_source_digest") == request.get("reviewed_source_digest")
            and type(document.get("gate1_confirmation_id")) is str
            and type(document.get("event_id")) is str
        )
    elif operation == "approve":
        expected_version = request.get("expected_task_version")
        note = request.get("note")
        valid = (
            document.get("task_ref") == request.get("task_ref")
            and document.get("gate_ref") == request.get("gate_ref")
            and document.get("gate1_confirmation_id") == request.get("gate1_confirmation_id")
            and document.get("reviewed_source_digest") == request.get("reviewed_source_digest")
            and type(expected_version) is int
            and document.get("task_version") == expected_version + 1
            and document.get("candidate_id") == request.get("candidate_id")
            and document.get("candidate_digest") == request.get("expected_digest")
            and document.get("decision") == "approve"
            and document.get("registration") == "manual_required"
            and type(note) is str
            and document.get("review_note_digest")
            == hashlib.sha256(note.encode("utf-8")).hexdigest()
        )
    else:
        expected_version = request.get("expected_task_version")
        gate_resolution_event_id = document.get("workflow_gate_resolution_event_id")
        gate3_event_id = document.get("workflow_gate3_event_id")
        valid = (
            document.get("task_ref") == request.get("task_ref")
            and document.get("attempt_ref") == request.get("attempt_ref")
            and type(expected_version) is int
            # HQA first resolves Domain Gate 3, then records the observed
            # promotion-review preparation as a second durable workflow event.
            and document.get("task_version") == expected_version + 2
            and type(gate_resolution_event_id) is str
            and _WORKFLOW_EVENT_RE.fullmatch(gate_resolution_event_id) is not None
            and type(gate3_event_id) is str
            and _WORKFLOW_EVENT_RE.fullmatch(gate3_event_id) is not None
            and gate_resolution_event_id != gate3_event_id
            and document.get("run_ref") == request.get("run_ref")
            and document.get("gate_ref") == request.get("gate_ref")
            and document.get("candidate_id") == request.get("candidate_id")
            and document.get("candidate_digest") == request.get("expected_digest")
            and document.get("final_backtest_receipt_id")
            == request.get("final_backtest_receipt_id")
            and document.get("base_commit") == request.get("base_commit")
            and type(document.get("promotion_id")) is str
            and document.get("promotion_status") == "awaiting_human_commit"
            and document.get("human_git_commit_required") is True
            and document.get("auto_commit") is False
        )
    if not valid:
        raise PaperGatePortError(
            "paper_gate_outcome_unknown",
            "HQA paper gate receipt does not match the exact request",
            retryable=False,
        )
    return dict(document)


@dataclass
class SubprocessPaperGatePort:
    """Production adapter for the fixed HQA paper-gate subprocess seam."""

    cli_settings: PaperGateCliSettings
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None

    def execute(
        self,
        operation: PaperGateOperation,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        if operation not in _OPERATIONS:
            raise PaperGatePortError(
                "paper_gate_invalid_operation",
                "paper gate operation is unsupported",
                retryable=False,
            )
        _require_managed_session_ref(request)
        stdin_bytes = _encode_request(request)
        python = self.cli_settings.python_executable
        hqa_root = self.cli_settings.hqa_root
        platform_root = self.cli_settings.platform_root
        quant_system = platform_root / "ai-quant" / "bin" / "quant-system"
        if (
            is_unconfigured_runtime_path(python)
            or is_unconfigured_runtime_path(hqa_root)
            or is_unconfigured_runtime_path(platform_root)
            or not python.is_file()
            or not hqa_root.is_dir()
            or not platform_root.is_dir()
            or not quant_system.is_file()
        ):
            raise PaperGatePortError(
                "paper_gate_unavailable",
                "pinned HQA or Platform runtime is unavailable",
                retryable=True,
            )
        argv = [
            str(python),
            "-m",
            "hqa.paper_gate_cli",
            operation,
        ]
        # Do not hand unrelated provider/API/database secrets to the child.
        # Only the authority paths/identity used by these three commands and
        # the two repo-local QS data roots may cross this boundary.
        env = {
            key: value
            for key, value in os.environ.items()
            if key in _SAFE_BASE_ENV or key in _SAFE_HQA_ENV or key in _SAFE_QS_ENV
        }
        env["PYTHONPATH"] = str(hqa_root)
        env["HQA_AIQP_DIR"] = str(platform_root)
        env["HQA_QUANT_SYSTEM_BIN"] = str(quant_system)
        run = self.runner or subprocess.run
        try:
            completed = run(
                argv,
                input=stdin_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(hqa_root),
                env=env,
                timeout=self.cli_settings.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PaperGatePortError(
                "paper_gate_outcome_unknown",
                "HQA paper gate timed out; reconcile the original action",
                retryable=False,
            ) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise PaperGatePortError(
                "paper_gate_unavailable",
                "HQA paper gate process is unavailable",
                retryable=True,
            ) from exc
        document = _parse_stdout(completed.stdout)
        if completed.returncode != 0:
            raise _error_from_document(document)
        return _validate_receipt(operation, request, document)


def build_subprocess_paper_gate_port(
    settings: object | None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> SubprocessPaperGatePort:
    return SubprocessPaperGatePort(
        cli_settings=PaperGateCliSettings.from_settings(settings),
        runner=runner,
    )


__all__ = [
    "PaperGateCliSettings",
    "PaperGateOperation",
    "PaperGatePortError",
    "SubprocessPaperGatePort",
    "build_subprocess_paper_gate_port",
]
