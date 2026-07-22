"""Intent Payload CLI Port — subprocess boundary to HQA (no ``import hqa``).

BFF calls ``put_intent``; the supervised worker calls ``bind_and_resolve_prompt``.
Prompt plaintext never appears on argv, the environment, or log lines — only
on the parent↔child stdin/stdout pipe.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


_STDIN_SOFT_LIMIT = 600_000
_DEFAULT_TIMEOUT_SECONDS = 15.0
_DEFAULT_HQA_ROOT = (
    Path(__file__).resolve().parents[4] / "Hermes-quant-agent"
)


class IntentPayloadPortError(RuntimeError):
    """Secret-free failure from the HQA intent payload CLI port."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = bool(retryable)


class IntentPayloadPort(Protocol):
    def put_intent(self, request: Mapping[str, Any]) -> dict[str, Any]: ...

    def bind_and_resolve_prompt(
        self, request: Mapping[str, Any]
    ) -> dict[str, Any]: ...


def _as_path(value: object, *, field: str) -> Path:
    if isinstance(value, Path):
        return value
    if type(value) is str and value:
        return Path(value)
    raise IntentPayloadPortError(
        "intent_port_misconfigured",
        f"{field} is not configured",
        retryable=False,
    )


def _settings_field(settings: object, name: str, default: object = None) -> object:
    if settings is None:
        return default
    return getattr(settings, name, default)


@dataclass(frozen=True)
class IntentPayloadCliSettings:
    """Resolved launch parameters for the HQA intent payload CLI."""

    python_executable: Path
    hqa_root: Path
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    extra_env: Mapping[str, str] | None = None

    @classmethod
    def from_settings(cls, settings: object | None = None) -> "IntentPayloadCliSettings":
        """Build from ``Settings.intent_payload`` or safe local defaults."""
        block = None
        if settings is not None:
            block = getattr(settings, "intent_payload", None)

        python_raw = _settings_field(block, "python_executable", None)
        if python_raw in (None, ""):
            # Prefer the sibling HQA venv when present; else current interpreter.
            hqa_guess = _settings_field(block, "hqa_root", None)
            hqa_root_guess = (
                _as_path(hqa_guess, field="hqa_root")
                if hqa_guess not in (None, "")
                else _DEFAULT_HQA_ROOT
            )
            venv_python = hqa_root_guess / ".venv" / "bin" / "python"
            python = venv_python if venv_python.is_file() else Path(sys.executable)
        else:
            python = _as_path(python_raw, field="python_executable")

        hqa_raw = _settings_field(block, "hqa_root", None)
        hqa_root = (
            _as_path(hqa_raw, field="hqa_root")
            if hqa_raw not in (None, "")
            else _DEFAULT_HQA_ROOT
        )

        timeout_raw = _settings_field(block, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        try:
            timeout = float(timeout_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise IntentPayloadPortError(
                "intent_port_misconfigured",
                "timeout_seconds must be a positive number",
                retryable=False,
            ) from exc
        if not (0 < timeout <= 300):
            raise IntentPayloadPortError(
                "intent_port_misconfigured",
                "timeout_seconds must be in (0, 300]",
                retryable=False,
            )

        return cls(
            python_executable=python,
            hqa_root=hqa_root,
            timeout_seconds=timeout,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise IntentPayloadPortError(
                "intent_invalid_json",
                "duplicate JSON field in CLI stdout",
                retryable=False,
            )
        document[key] = value
    return document


def _reject_constant(_value: str) -> None:
    raise IntentPayloadPortError(
        "intent_invalid_json",
        "non-finite JSON number in CLI stdout",
        retryable=False,
    )


def _encode_stdin(request: Mapping[str, Any]) -> bytes:
    try:
        payload = json.dumps(
            dict(request),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise IntentPayloadPortError(
            "intent_invalid_request",
            "request is not JSON-serializable",
            retryable=False,
        ) from exc
    raw = payload.encode("utf-8")
    if not raw or len(raw) > _STDIN_SOFT_LIMIT:
        raise IntentPayloadPortError(
            "intent_invalid_request",
            "request exceeds CLI stdin limit",
            retryable=False,
        )
    return raw


def _parse_stdout(raw: bytes) -> dict[str, Any]:
    if not raw:
        raise IntentPayloadPortError(
            "intent_cli_empty_stdout",
            "intent payload CLI returned empty stdout",
            retryable=True,
        )
    # One JSON object; tolerate a single trailing newline.
    text = raw.decode("utf-8", errors="strict")
    line = text.strip()
    if not line or "\n" in line:
        raise IntentPayloadPortError(
            "intent_cli_invalid_stdout",
            "intent payload CLI must emit exactly one JSON object",
            retryable=True,
        )
    try:
        document = json.loads(
            line,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except IntentPayloadPortError:
        raise
    except (json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise IntentPayloadPortError(
            "intent_cli_invalid_stdout",
            "intent payload CLI stdout is not valid JSON",
            retryable=True,
        ) from exc
    if not isinstance(document, dict):
        raise IntentPayloadPortError(
            "intent_cli_invalid_stdout",
            "intent payload CLI stdout must be a JSON object",
            retryable=True,
        )
    return document


def _map_error_document(document: Mapping[str, Any]) -> IntentPayloadPortError:
    error = document.get("error")
    if not isinstance(error, Mapping):
        return IntentPayloadPortError(
            "intent_cli_failed",
            "intent payload CLI failed without structured error",
            retryable=True,
        )
    code = error.get("code")
    message = error.get("message")
    retryable = bool(error.get("retryable", False))
    if type(code) is not str or not code:
        code = "intent_cli_failed"
    if type(message) is not str or not message:
        message = "intent payload CLI failed"
    # Never surface prompt-bearing detail; CLI messages are already secret-free.
    return IntentPayloadPortError(code, message, retryable=retryable)


@dataclass
class SubprocessIntentPayloadPort:
    """Live port: ``python -m hqa.intent_payload_cli <verb>`` over pipes."""

    cli_settings: IntentPayloadCliSettings
    runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None

    def put_intent(self, request: Mapping[str, Any]) -> dict[str, Any]:
        document = self._invoke("put", request)
        if document.get("ok") is not True:
            raise _map_error_document(document)
        # Metadata only — refuse any accidental prompt echo.
        if "prompt" in document:
            raise IntentPayloadPortError(
                "intent_cli_leaked_prompt",
                "put receipt must not include prompt",
                retryable=False,
            )
        payload_ref = document.get("payload_ref")
        payload_digest = document.get("payload_digest")
        if type(payload_ref) is not str or not payload_ref:
            raise IntentPayloadPortError(
                "intent_cli_invalid_receipt",
                "put receipt missing payload_ref",
                retryable=True,
            )
        if type(payload_digest) is not str or not payload_digest:
            raise IntentPayloadPortError(
                "intent_cli_invalid_receipt",
                "put receipt missing payload_digest",
                retryable=True,
            )
        return dict(document)

    def bind_and_resolve_prompt(self, request: Mapping[str, Any]) -> dict[str, Any]:
        document = self._invoke("bind_resolve", request)
        if document.get("ok") is not True:
            raise _map_error_document(document)
        prompt = document.get("prompt")
        if type(prompt) is not str or not prompt:
            raise IntentPayloadPortError(
                "intent_cli_invalid_receipt",
                "bind_resolve receipt missing prompt",
                retryable=True,
            )
        return dict(document)

    def _invoke(self, command: str, request: Mapping[str, Any]) -> dict[str, Any]:
        stdin_bytes = _encode_stdin(request)
        python = self.cli_settings.python_executable
        hqa_root = self.cli_settings.hqa_root
        if not python.is_file():
            raise IntentPayloadPortError(
                "intent_cli_unavailable",
                "HQA python executable is missing",
                retryable=True,
            )
        if not hqa_root.is_dir():
            raise IntentPayloadPortError(
                "intent_cli_unavailable",
                "HQA root directory is missing",
                retryable=True,
            )

        env = os.environ.copy()
        # Ensure hqa is importable from the sibling checkout.
        existing = env.get("PYTHONPATH", "")
        root_str = str(hqa_root)
        env["PYTHONPATH"] = (
            root_str if not existing else root_str + os.pathsep + existing
        )
        # Never pass prompt via env; strip accidental overrides of secrets.
        if self.cli_settings.extra_env:
            for key, value in self.cli_settings.extra_env.items():
                if type(key) is str and type(value) is str:
                    env[key] = value

        argv = [str(python), "-m", "hqa.intent_payload_cli", command]
        runner = self.runner or subprocess.run
        try:
            completed = runner(
                argv,
                input=stdin_bytes,
                capture_output=True,
                timeout=self.cli_settings.timeout_seconds,
                check=False,
                cwd=str(hqa_root),
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise IntentPayloadPortError(
                "intent_cli_timeout",
                "intent payload CLI timed out",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise IntentPayloadPortError(
                "intent_cli_unavailable",
                "intent payload CLI could not be started",
                retryable=True,
            ) from exc

        # Prefer structured stdout even on non-zero exit.
        try:
            document = _parse_stdout(completed.stdout or b"")
        except IntentPayloadPortError:
            if completed.returncode != 0:
                raise IntentPayloadPortError(
                    "intent_cli_failed",
                    "intent payload CLI exited without structured stdout",
                    retryable=True,
                )
            raise

        if completed.returncode != 0 and document.get("ok") is True:
            raise IntentPayloadPortError(
                "intent_cli_failed",
                "intent payload CLI returned ok with non-zero exit",
                retryable=True,
            )
        if completed.returncode != 0:
            raise _map_error_document(document)
        return document


@dataclass
class FakeIntentPayloadPort:
    """In-process double for M1 tests (no Keychain, no HQA subprocess)."""

    puts: list[dict[str, Any]] | None = None
    resolves: list[dict[str, Any]] | None = None
    put_handler: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None
    resolve_handler: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None
    # Simple content-addressed memory when handlers are absent.
    _store: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.puts is None:
            self.puts = []
        if self.resolves is None:
            self.resolves = []
        if self._store is None:
            self._store = {}

    def put_intent(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(request)
        assert self.puts is not None
        self.puts.append(body)
        if self.put_handler is not None:
            return self.put_handler(body)
        import hashlib

        prompt = body.get("prompt")
        client_intent_id = body.get("client_intent_id")
        if type(prompt) is not str or not prompt:
            raise IntentPayloadPortError(
                "intent_invalid_request",
                "prompt required",
                retryable=False,
            )
        if type(client_intent_id) is not str or not client_intent_id:
            raise IntentPayloadPortError(
                "intent_invalid_request",
                "client_intent_id required",
                retryable=False,
            )
        # Idempotency: same client_intent_id + same prompt → same digest.
        key = client_intent_id
        assert self._store is not None
        existing = self._store.get(key)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "client_intent_id": client_intent_id,
                    "prompt": prompt,
                    "session_id": body.get("session_id"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if existing is not None:
            if existing["payload_digest"] != digest:
                raise IntentPayloadPortError(
                    "intent_idempotency_conflict",
                    "client_intent_id already bound to a different body",
                    retryable=False,
                )
            return dict(existing["receipt"])
        receipt = {
            "ok": True,
            "schema_version": body.get("schema_version", "2.0"),
            "payload_ref": "payload:sha256:" + digest,
            "payload_digest": digest,
            "kind": body.get("kind", "conversation_turn"),
            "owner_id": body.get("owner_id"),
            "workspace_id": body.get("workspace_id"),
            "session_id": body.get("session_id"),
            "client_intent_id": client_intent_id,
            "provider_policy_digest": body.get(
                "provider_policy_digest",
                "be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31",
            ),
            "ttl_days": body.get("ttl_days"),
            "status": "stored",
        }
        self._store[key] = {
            "payload_digest": digest,
            "receipt": receipt,
            "prompt": prompt,
            "body": body,
            "consumer_ref": None,
        }
        return dict(receipt)

    def bind_and_resolve_prompt(self, request: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(request)
        assert self.resolves is not None
        self.resolves.append(body)
        if self.resolve_handler is not None:
            return self.resolve_handler(body)
        payload_ref = body.get("payload_ref")
        consumer_ref = body.get("consumer_ref")
        if type(payload_ref) is not str or type(consumer_ref) is not str:
            raise IntentPayloadPortError(
                "intent_invalid_request",
                "payload_ref and consumer_ref required",
                retryable=False,
            )
        assert self._store is not None
        match = None
        for entry in self._store.values():
            if entry["receipt"]["payload_ref"] == payload_ref:
                match = entry
                break
        if match is None:
            raise IntentPayloadPortError(
                "intent_payload_not_found",
                "payload not found",
                retryable=False,
            )
        bound = match.get("consumer_ref")
        if bound is not None and bound != consumer_ref:
            raise IntentPayloadPortError(
                "intent_consumer_conflict",
                "payload already bound to a different consumer",
                retryable=False,
            )
        match["consumer_ref"] = consumer_ref
        return {
            "ok": True,
            "payload_ref": payload_ref,
            "payload_digest": match["payload_digest"],
            "prompt": match["prompt"],
            "consumer_ref": consumer_ref,
        }


def build_intent_payload_port(
    settings: object | None = None,
    *,
    port: IntentPayloadPort | None = None,
) -> IntentPayloadPort:
    """Factory: inject ``port`` for tests; otherwise live subprocess port."""
    if port is not None:
        return port
    cli = IntentPayloadCliSettings.from_settings(settings)
    return SubprocessIntentPayloadPort(cli_settings=cli)


def intent_payload_input_resolver(
    settings: object | None = None,
    *,
    port: IntentPayloadPort | None = None,
) -> Callable[["object"], str]:
    """Build a dispatch ``input_resolver`` that bind_resolves via the CLI Port.

    ``consumer_ref = command:<ledger_command_id>``. Plaintext exists only inside
    the resolver return value (then Hermes POST body). BFF never calls this.
    """
    from quant_system.hermes.dark_identity_profile import (
        CHAT_PROMPT_MAX_BYTES,
        DarkIdentityProfileError,
        build_bind_resolve_request,
    )

    active = build_intent_payload_port(settings, port=port)

    def _resolve(request: object) -> str:
        command_id = getattr(request, "command_id", None)
        payload_ref = getattr(request, "payload_ref", None)
        platform_session_id = getattr(request, "platform_session_id", None)
        if type(command_id) is not str or not command_id:
            raise IntentPayloadPortError(
                "intent_resolve_invalid_request",
                "dispatch request missing command_id",
                retryable=False,
            )
        if type(payload_ref) is not str or not payload_ref:
            raise IntentPayloadPortError(
                "intent_resolve_invalid_request",
                "dispatch request missing payload_ref",
                retryable=False,
            )
        if type(platform_session_id) is not str or not platform_session_id:
            raise IntentPayloadPortError(
                "intent_resolve_invalid_request",
                "dispatch request missing platform_session_id",
                retryable=False,
            )
        try:
            body = build_bind_resolve_request(
                payload_ref=payload_ref,
                managed_session_ref=platform_session_id,
                consumer_ref="command:" + command_id,
            )
        except DarkIdentityProfileError as exc:
            raise IntentPayloadPortError(
                exc.code,
                exc.message,
                retryable=False,
            ) from exc
        receipt = active.bind_and_resolve_prompt(body)
        prompt = receipt.get("prompt")
        if type(prompt) is not str or not prompt:
            raise IntentPayloadPortError(
                "intent_cli_invalid_receipt",
                "bind_resolve returned empty prompt",
                retryable=True,
            )
        if len(prompt.encode("utf-8")) > CHAT_PROMPT_MAX_BYTES:
            raise IntentPayloadPortError(
                "prompt_too_large",
                "resolved prompt exceeds 16 KiB chat ceiling",
                retryable=False,
            )
        return prompt

    return _resolve


__all__ = [
    "FakeIntentPayloadPort",
    "IntentPayloadCliSettings",
    "IntentPayloadPort",
    "IntentPayloadPortError",
    "SubprocessIntentPayloadPort",
    "build_intent_payload_port",
    "intent_payload_input_resolver",
]
