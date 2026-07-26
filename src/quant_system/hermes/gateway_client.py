from __future__ import annotations

import json
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlparse

import httpx

from quant_system.config.settings import HermesGatewaySettings
from quant_system.hermes.approval_release_port import ApprovalReleaseResult
from quant_system.hermes.run_stop_port import StopResult


class HermesApiReadError(RuntimeError):
    """Stable, secret-free failure raised by the Hermes read adapter."""

    def __init__(self, code: str, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


_SESSION_SAFE_KEYS = (
    "id",
    "title",
    "source",
    "model",
    "message_count",
    "last_active",
    "preview",
    "parent_session_id",
    "ended_at",
)
_CAPABILITY_FEATURES = (
    "session_resources",
    "run_submission",
    "run_events_sse",
    "run_status",
    "run_approval_response",
    "run_stop",
    "managed_run_sessions",
)
_DURABLE_CAPABILITIES = (
    "idempotency",
    "event_replay",
    "approval_cas",
    "idempotent_stop",
    "restart_reconcile",
    "run_evidence",
)
_MESSAGE_ROLES = frozenset({"user", "assistant"})
_MAX_TOKEN_BYTES = 4096
_MAX_TEXT_CHARS = 100_000
_CONTROL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_RUN_STATES = frozenset({"queued", "running", "succeeded", "failed", "stopped"})
_RUN_TERMINAL_STATES = frozenset({"succeeded", "failed", "stopped"})
_APPROVAL_TERMINAL_EVENTS = frozenset(
    {
        "approval.decision_recorded",
        "approval.responded",
        "approval.release_committed",
        "approval.signalled",
    }
)

# V1.5 DLP: conservative secret patterns redacted from *retained* transcript
# messages before they are served to the browser. Redaction (``***``), not
# dropping, so a message that mentions a secret still renders with the secret
# removed. Applied before bounding so a truncated secret can never leak.
_SECRET_PATTERNS = (
    re.compile(
        r"(?<!\w)Bearer\b[ \t]+"
        r"(?:"
        r"\.(?:[A-Za-z0-9._~+/=-]*[A-Za-z0-9_~+/=-])?"
        r"|[A-Za-z0-9_~+/=-](?:[A-Za-z0-9._~+/=-]*[A-Za-z0-9_~+/=-])?"
        r")",
        re.IGNORECASE,
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|api[_-]?secret|secret|token|password|passwd"
        r"|access[_-]?key)\b\s*[:=]\s*[^\s,;]+"
    ),
)

# Hermes prepends this Discord-only routing instruction to the model-facing
# user turn. It is transport/control metadata, not user-authored transcript
# content, and must never be rendered in the Web session reader.
_DISCORD_TRIGGER_PREFIX = re.compile(
    r"\A\[Triggering message id: `\d{1,32}`\s+(?:—|-)\s+use as "
    r"`message_id` for reply/react/pin via the discord tools\.\]\s*",
    re.IGNORECASE,
)


def _redact_secrets(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("***", redacted)
    return redacted


def _strip_internal_transport_prefix(text: str, *, role: str) -> str:
    if role != "user":
        return text
    return _DISCORD_TRIGGER_PREFIX.sub("", text, count=1).lstrip()


def _validated_loopback_origin(value: str) -> str:
    try:
        parsed = urlparse(str(value).strip())
        port = parsed.port
    except ValueError as exc:
        raise HermesApiReadError(
            "invalid_endpoint",
            "Hermes API endpoint must be an explicit loopback HTTP origin",
        ) from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or port is None
        or not 1 <= port <= 65535
        or parsed.path not in {"", "/"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise HermesApiReadError(
            "invalid_endpoint",
            "Hermes API endpoint must be an explicit loopback HTTP origin",
        )
    return str(value).strip().rstrip("/")


def _bounded_text(value: object, *, maximum: int = _MAX_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    return value[:maximum]


def _normalized_timestamp(value: object) -> str | None:
    if isinstance(value, str):
        return _bounded_text(value, maximum=128)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    try:
        rendered = datetime.fromtimestamp(numeric, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return None
    return rendered.replace("+00:00", "Z")


def _runtime_build_projection(value: object) -> dict[str, object] | None:
    """Copy only the bounded, non-secret Hermes build identity fields."""

    if not isinstance(value, Mapping):
        return None
    schema_version = value.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        schema_version = None
    ready = value.get("ready")
    clean = value.get("clean")
    return {
        "schema_version": schema_version,
        "source": _bounded_text(value.get("source"), maximum=64),
        "ready": ready if type(ready) is bool else None,
        "root_realpath": _bounded_text(value.get("root_realpath"), maximum=4096),
        "module_realpath": _bounded_text(
            value.get("module_realpath"),
            maximum=4096,
        ),
        "entrypoint_sha256": _bounded_text(
            value.get("entrypoint_sha256"),
            maximum=64,
        ),
        "commit": _bounded_text(value.get("commit"), maximum=64),
        "tree": _bounded_text(value.get("tree"), maximum=64),
        "clean": clean if type(clean) is bool else None,
        "digest": _bounded_text(value.get("digest"), maximum=64),
    }


def validate_hermes_session_id(value: object) -> str:
    sid = str(value or "").strip()
    drive_prefixed = len(sid) >= 2 and sid[0].isalpha() and sid[1] == ":"
    if (
        not sid
        or len(sid) > 256
        or sid == "."
        or ".." in sid
        or "/" in sid
        or "\\" in sid
        or drive_prefixed
        or any(char in sid for char in ("\r", "\n", "\x00"))
    ):
        raise HermesApiReadError(
            "invalid_session_id",
            "session_id is invalid",
            status_code=400,
        )
    return sid


class HermesApiReadClient:
    """Allowlisted GET-only adapter for the official Hermes API Server.

    The upstream Bearer key is full-authority.  This type intentionally has no
    generic request method and exposes no run/chat/approval/stop mutation.
    """

    def __init__(
        self,
        settings: HermesGatewaySettings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.base_url = _validated_loopback_origin(settings.base_url)
        self._transport = transport

    def _api_key(self) -> str:
        path_value = self.settings.api_key_file
        if path_value is None:
            raise HermesApiReadError(
                "api_key_file_missing",
                "Hermes API key file is not configured",
            )
        path = Path(path_value)
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            raise HermesApiReadError(
                "api_key_file_invalid",
                "Hermes API key file is unavailable",
            ) from exc
        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise HermesApiReadError(
                    "api_key_file_invalid",
                    "Hermes API key file must be a regular non-symlink file",
                )
            if stat.S_IMODE(file_stat.st_mode) & 0o077:
                raise HermesApiReadError(
                    "api_key_file_permissions",
                    "Hermes API key file must be owner-only (mode 0600 or stricter)",
                )
            if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
                raise HermesApiReadError(
                    "api_key_file_owner",
                    "Hermes API key file must be owned by the current user",
                )
            chunks: list[bytes] = []
            remaining = _MAX_TOKEN_BYTES + 1
            while remaining > 0:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
        except HermesApiReadError:
            raise
        except OSError as exc:
            raise HermesApiReadError(
                "api_key_file_invalid",
                "Hermes API key file is unavailable",
            ) from exc
        finally:
            os.close(fd)
        if not raw or len(raw) > _MAX_TOKEN_BYTES:
            raise HermesApiReadError(
                "api_key_invalid",
                "Hermes API key must be non-empty and bounded",
            )
        try:
            token = raw.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise HermesApiReadError(
                "api_key_invalid",
                "Hermes API key must be valid UTF-8",
            ) from exc
        if not token or any(char in token for char in ("\r", "\n", "\x00")):
            raise HermesApiReadError(
                "api_key_invalid",
                "Hermes API key contains invalid characters",
            )
        return token

    def _get_json(
        self,
        path: str,
        *,
        params: Mapping[str, int | str | bool] | None = None,
        not_found_code: str = "upstream_endpoint_unavailable",
        not_found_message: str = "Hermes API endpoint is unavailable",
    ) -> dict[str, Any]:
        token = self._api_key()
        timeout = httpx.Timeout(self.settings.timeout_seconds)
        try:
            with (
                httpx.Client(
                    base_url=self.base_url,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                    headers={
                        "accept": "application/json",
                        "authorization": f"Bearer {token}",
                    },
                ) as client,
                client.stream("GET", path, params=params) as response,
            ):
                if response.status_code != 200:
                    if response.status_code == 401:
                        raise HermesApiReadError(
                            "upstream_auth_failed",
                            "Hermes API rejected the configured server credential",
                        )
                    if response.status_code == 404:
                        raise HermesApiReadError(
                            not_found_code,
                            not_found_message,
                            status_code=(404 if not_found_code == "session_not_found" else 503),
                        )
                    raise HermesApiReadError(
                        "upstream_error",
                        "Hermes API returned an unavailable response",
                    )
                advertised_length = response.headers.get("content-length")
                if advertised_length:
                    try:
                        if int(advertised_length) > self.settings.max_response_bytes:
                            raise HermesApiReadError(
                                "response_too_large",
                                "Hermes API response exceeded the configured read bound",
                            )
                    except ValueError:
                        pass
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.settings.max_response_bytes:
                        raise HermesApiReadError(
                            "response_too_large",
                            "Hermes API response exceeded the configured read bound",
                        )
                    chunks.append(chunk)
        except HermesApiReadError:
            raise
        except httpx.TimeoutException as exc:
            raise HermesApiReadError(
                "upstream_timeout",
                "Hermes API did not answer within the configured timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise HermesApiReadError(
                "upstream_unavailable",
                "Hermes API is unavailable on the configured loopback endpoint",
            ) from exc
        try:
            document = json.loads(b"".join(chunks))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HermesApiReadError(
                "invalid_upstream_response",
                "Hermes API returned an invalid JSON response",
            ) from exc
        if not isinstance(document, dict):
            raise HermesApiReadError(
                "invalid_upstream_response",
                "Hermes API returned an invalid response envelope",
            )
        return document

    @staticmethod
    def _session_summary(raw: object) -> dict[str, Any] | None:
        if not isinstance(raw, Mapping):
            return None
        raw_session_id = raw.get("id")
        if not isinstance(raw_session_id, str):
            return None
        try:
            session_id = validate_hermes_session_id(raw_session_id)
        except HermesApiReadError:
            return None
        summary: dict[str, Any] = {}
        for key in _SESSION_SAFE_KEYS:
            value = raw.get(key)
            if key == "id":
                summary[key] = session_id
            elif key == "message_count":
                summary[key] = (
                    value
                    if isinstance(value, int) and not isinstance(value, bool) and value >= 0
                    else None
                )
            elif key in {"last_active", "ended_at"}:
                summary[key] = _normalized_timestamp(value)
            else:
                summary[key] = _bounded_text(value, maximum=1000)
        return summary

    def capabilities(self) -> dict[str, Any]:
        raw = self._get_json("/v1/capabilities")
        if raw.get("object") != "hermes.api_server.capabilities":
            raise HermesApiReadError(
                "invalid_upstream_response",
                "Hermes API capability envelope is not supported",
            )
        raw_features = raw.get("features")
        features = {
            key: raw_features.get(key) is True if isinstance(raw_features, Mapping) else False
            for key in _CAPABILITY_FEATURES
        }
        raw_durable = raw.get("durable")
        durable: dict[str, dict[str, object]] = {}
        for name in _DURABLE_CAPABILITIES:
            raw_fact = (
                raw_durable.get(name)
                if isinstance(raw_durable, Mapping)
                else None
            )
            durable[name] = {
                "supported": (
                    isinstance(raw_fact, Mapping)
                    and raw_fact.get("supported") is True
                ),
                "grounded": (
                    isinstance(raw_fact, Mapping)
                    and raw_fact.get("grounded") is True
                ),
                "evidence": (
                    _bounded_text(raw_fact.get("evidence"), maximum=128)
                    if isinstance(raw_fact, Mapping)
                    else None
                ),
            }
        contract_version = raw.get("contract_version")
        if (
            isinstance(contract_version, bool)
            or not isinstance(contract_version, int)
            or contract_version < 1
        ):
            contract_version = None
        managed_session_contract = {
            "history_authority": (
                _bounded_text(
                    raw_features.get("managed_run_history_authority"),
                    maximum=128,
                )
                if isinstance(raw_features, Mapping)
                else None
            ),
            "fork_mode": (
                _bounded_text(
                    raw_features.get("managed_session_fork_mode"),
                    maximum=128,
                )
                if isinstance(raw_features, Mapping)
                else None
            ),
        }
        raw_runtime = raw.get("runtime")
        runtime_instance_id: str | None = None
        runtime_started_at: str | None = None
        runtime_pid: int | None = None
        runtime_build: dict[str, object] | None = None
        if isinstance(raw_runtime, Mapping):
            candidate_instance = raw_runtime.get("instance_id")
            candidate_started_at = raw_runtime.get("started_at")
            candidate_pid = raw_runtime.get("pid")
            if (
                isinstance(candidate_pid, int)
                and not isinstance(candidate_pid, bool)
                and candidate_pid > 0
            ):
                runtime_pid = candidate_pid
            runtime_build = _runtime_build_projection(raw_runtime.get("build"))
            if (
                isinstance(candidate_instance, str)
                and re.fullmatch(r"[0-9a-f]{32}", candidate_instance)
                and isinstance(candidate_started_at, str)
            ):
                try:
                    parsed_started_at = datetime.fromisoformat(
                        candidate_started_at.replace("Z", "+00:00")
                    )
                except ValueError:
                    parsed_started_at = None
                if (
                    parsed_started_at is not None
                    and parsed_started_at.tzinfo is not None
                    and parsed_started_at.utcoffset() is not None
                ):
                    runtime_instance_id = candidate_instance
                    runtime_started_at = (
                        parsed_started_at.astimezone(UTC)
                        .isoformat(timespec="microseconds")
                        .replace("+00:00", "Z")
                    )
        return {
            "model": _bounded_text(raw.get("model"), maximum=256),
            "features": features,
            "contract_version": contract_version,
            "durable": durable,
            "managed_session_contract": managed_session_contract,
            "runtime": {
                "instance_id": runtime_instance_id,
                "started_at": runtime_started_at,
                "pid": runtime_pid,
                "build": runtime_build,
            },
        }

    def list_sessions(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise HermesApiReadError(
                "invalid_limit",
                "limit must be between 1 and 200",
                status_code=400,
            )
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1_000_000:
            raise HermesApiReadError(
                "invalid_offset",
                "offset is outside the supported range",
                status_code=400,
            )
        raw = self._get_json(
            "/api/sessions",
            params={"limit": limit, "offset": offset},
        )
        rows = raw.get("data")
        if raw.get("object") != "list" or not isinstance(rows, list):
            raise HermesApiReadError(
                "invalid_upstream_response",
                "Hermes session list envelope is invalid",
            )
        sessions = [summary for row in rows if (summary := self._session_summary(row)) is not None]
        return {
            "data": sessions,
            "limit": limit,
            "offset": offset,
            "has_more": raw.get("has_more") is True,
        }

    def session_detail(self, session_id: str) -> dict[str, Any]:
        sid = validate_hermes_session_id(session_id)
        raw = self._get_json(
            f"/api/sessions/{quote(sid, safe='')}",
            not_found_code="session_not_found",
            not_found_message="Hermes session was not found",
        )
        summary = self._session_summary(raw.get("session"))
        if raw.get("object") != "hermes.session" or summary is None:
            raise HermesApiReadError(
                "invalid_upstream_response",
                "Hermes session detail envelope is invalid",
            )
        return summary

    def session_messages(self, session_id: str) -> dict[str, Any]:
        sid = validate_hermes_session_id(session_id)
        raw = self._get_json(
            f"/api/sessions/{quote(sid, safe='')}/messages",
            not_found_code="session_not_found",
            not_found_message="Hermes session was not found",
        )
        rows = raw.get("data")
        if raw.get("object") != "list" or not isinstance(rows, list):
            raise HermesApiReadError(
                "invalid_upstream_response",
                "Hermes message history envelope is invalid",
            )
        messages: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping) or row.get("role") not in _MESSAGE_ROLES:
                continue
            content = _bounded_text(row.get("content"))
            if content is None:
                continue
            # V1.5: drop empty / whitespace-only messages and internal
            # compaction stubs (which surface as blank user/assistant rows) so
            # the transcript never renders an empty bubble. Then redact secrets
            # from the retained text (redact, not drop) before it is served.
            stripped = _strip_internal_transport_prefix(
                content.strip(), role=str(row["role"])
            )
            if stripped == "":
                continue
            content = _redact_secrets(stripped)
            raw_message_id = row.get("id")
            message_id = str(
                raw_message_id if raw_message_id is not None else index
            )
            if not message_id or len(message_id) > 256:
                message_id = str(index)
            # An exact Hermes fork cursor is authority-bearing.  Only the
            # original positive integer SessionDB id qualifies; the display
            # fallback index and numeric-looking strings must never be
            # promoted into a cursor.
            rendered_fork_point = f"message:{raw_message_id}"
            fork_point = (
                rendered_fork_point
                if (
                    type(raw_message_id) is int
                    and raw_message_id > 0
                    and len(rendered_fork_point) <= 256
                )
                else None
            )
            messages.append(
                {
                    "id": message_id,
                    "role": str(row["role"]),
                    "content": content,
                    "timestamp": _normalized_timestamp(row.get("timestamp")),
                    "fork_point": fork_point,
                }
            )
        bounded = messages[-self.settings.max_messages :]
        return {
            "session_id": sid,
            "data": bounded,
            "omitted_message_count": max(0, len(rows) - len(bounded)),
        }


class HermesRunControlError(RuntimeError):
    """Secret-free failure from the narrow official Run-control surface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class HermesRunControlPort(Protocol):
    """Small production seam mounted by AgentWorkspace."""

    def pending_approvals(
        self,
        run_ids: tuple[str, ...],
    ) -> tuple[dict[str, object], ...]: ...

    def respond_approval_exact(
        self,
        run_id: str,
        *,
        choice: str,
        challenge_id: str,
        action_digest: str,
        expected_status: str,
        expected_expires_at: str,
    ) -> ApprovalReleaseResult: ...

    def stop(self, run_id: str) -> StopResult: ...


@dataclass(frozen=True)
class _ApprovalObservation:
    challenge_id: str
    approval_id: str
    run_id: str
    action_digest: str
    expires_at: str
    state: Literal["pending", "decided"]
    choice: str | None = None

    def to_public_pending(self) -> dict[str, object]:
        return {
            # The Web action echoes the durable challenge identity. The
            # upstream approval_id remains the gated waiter/command identity.
            "approval_id": self.challenge_id,
            "run_id": self.run_id,
            "command_id": self.approval_id,
            "digest": self.action_digest,
            "expires_at": self.expires_at,
            "expected_status": "pending",
            "status": "pending",
            "kind": "hermes.command_approval",
        }


def _control_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _CONTROL_ID_RE.fullmatch(value) is None:
        raise HermesRunControlError(
            "run_control_validation",
            f"{field} must be a bounded identifier",
        )
    return value


def _control_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise HermesRunControlError(
            "run_control_validation",
            f"{field} must be a lowercase SHA-256 digest",
        )
    return value


def _canonical_control_timestamp(value: object, field: str) -> str:
    if isinstance(value, bool):
        raise HermesRunControlError(
            "run_control_validation",
            f"{field} must be a timezone-aware timestamp",
        )
    if isinstance(value, int | float):
        if not math.isfinite(float(value)):
            raise HermesRunControlError(
                "invalid_upstream_response",
                "Hermes approval expiry is invalid",
            )
        try:
            parsed = datetime.fromtimestamp(float(value), tz=UTC)
        except (OSError, OverflowError, ValueError) as exc:
            raise HermesRunControlError(
                "invalid_upstream_response",
                "Hermes approval expiry is invalid",
            ) from exc
    elif isinstance(value, str) and len(value) <= 128:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HermesRunControlError(
                "run_control_validation",
                f"{field} must be a timezone-aware timestamp",
            ) from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise HermesRunControlError(
                "run_control_validation",
                f"{field} must be a timezone-aware timestamp",
            )
        parsed = parsed.astimezone(UTC)
    else:
        raise HermesRunControlError(
            "run_control_validation",
            f"{field} must be a timezone-aware timestamp",
        )
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class OfficialHermesRunControlClient(HermesApiReadClient):
    """Exact, capability-gated approval and Run-stop adapter.

    This type deliberately exposes no generic mutation method. Every POST is
    preceded by a fresh durable-capability probe. Approval additionally
    replays the canonical Run event log and verifies the browser's exact
    challenge/digest/expiry tuple before the upstream CAS is attempted.
    """

    def _require_control_ready(self, *, feature: str) -> None:
        if self.settings.enabled is not True:
            raise HermesRunControlError(
                "durable_run_control_unavailable",
                "Hermes Run control is disabled",
            )
        try:
            capabilities = self.capabilities()
        except HermesApiReadError as exc:
            raise HermesRunControlError(exc.code, exc.message) from exc
        if (
            capabilities.get("contract_version") is None
            or not isinstance(capabilities.get("features"), Mapping)
            or capabilities["features"].get(feature) is not True  # type: ignore[index]
        ):
            raise HermesRunControlError(
                "durable_run_control_unavailable",
                "Hermes Run control capability is unavailable",
            )
        durable = capabilities.get("durable")
        if not isinstance(durable, Mapping):
            raise HermesRunControlError(
                "durable_run_control_unavailable",
                "Hermes durable authority is unavailable",
            )
        for name in _DURABLE_CAPABILITIES:
            fact = durable.get(name)
            if (
                not isinstance(fact, Mapping)
                or fact.get("supported") is not True
                or fact.get("grounded") is not True
            ):
                raise HermesRunControlError(
                    "durable_run_control_unavailable",
                    "Hermes durable authority is unavailable",
                )
        runtime = capabilities.get("runtime")
        build = runtime.get("build") if isinstance(runtime, Mapping) else None
        if (
            not isinstance(runtime, Mapping)
            or not isinstance(runtime.get("instance_id"), str)
            or not isinstance(runtime.get("started_at"), str)
            or not isinstance(build, Mapping)
            or build.get("ready") is not True
            or build.get("clean") is not True
            or not isinstance(build.get("digest"), str)
            or _HEX64_RE.fullmatch(str(build["digest"])) is None
        ):
            raise HermesRunControlError(
                "durable_run_control_unavailable",
                "Hermes runtime identity is unavailable",
            )

    def _post_json(self, path: str, body: Mapping[str, object]) -> dict[str, Any]:
        token = self._api_key()
        try:
            encoded = json.dumps(
                dict(body),
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HermesRunControlError(
                "run_control_validation",
                "Hermes Run-control request is invalid",
            ) from exc
        timeout = httpx.Timeout(self.settings.timeout_seconds)
        try:
            with (
                httpx.Client(
                    base_url=self.base_url,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                    headers={
                        "accept": "application/json",
                        "authorization": f"Bearer {token}",
                        "content-type": "application/json",
                    },
                ) as client,
                client.stream("POST", path, content=encoded) as response,
            ):
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > self.settings.max_response_bytes:
                        raise HermesRunControlError(
                            "response_too_large",
                            "Hermes Run-control response exceeded the configured bound",
                        )
                    chunks.append(chunk)
                raw = b"".join(chunks)
                if response.status_code != 200:
                    code = _upstream_error_code(raw)
                    if response.status_code == 404:
                        code = "run_not_found"
                    elif response.status_code == 401:
                        code = "upstream_auth_failed"
                    elif response.status_code == 409 and code is None:
                        code = "run_control_conflict"
                    elif response.status_code >= 500 and code is None:
                        code = "upstream_unavailable"
                    raise HermesRunControlError(
                        code or "invalid_upstream_response",
                        "Hermes Run-control request was not accepted",
                    )
        except HermesRunControlError:
            raise
        except httpx.TimeoutException as exc:
            raise HermesRunControlError(
                "transport_error",
                "Hermes Run-control outcome is unknown",
            ) from exc
        except httpx.HTTPError as exc:
            raise HermesRunControlError(
                "transport_error",
                "Hermes Run-control outcome is unknown",
            ) from exc
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HermesRunControlError(
                "outcome_unknown",
                "Hermes Run-control outcome could not be verified",
            ) from exc
        if not isinstance(document, dict):
            raise HermesRunControlError(
                "outcome_unknown",
                "Hermes Run-control outcome could not be verified",
            )
        return document

    def run_status(self, run_id: str) -> dict[str, object]:
        rid = _control_id(run_id, "run_id")
        try:
            raw = self._get_json(
                f"/v1/runs/{quote(rid, safe='')}",
                not_found_code="run_not_found",
                not_found_message="Hermes Run was not found",
            )
        except HermesApiReadError as exc:
            raise HermesRunControlError(exc.code, exc.message) from exc
        status = raw.get("status")
        if (
            raw.get("object") != "hermes.run"
            or raw.get("run_id") != rid
            or status not in _RUN_STATES
        ):
            raise HermesRunControlError(
                "invalid_upstream_response",
                "Hermes Run status response is invalid",
            )
        return {
            "object": "hermes.run",
            "run_id": rid,
            "status": str(status),
            "session_id": (
                str(raw["session_id"])
                if isinstance(raw.get("session_id"), str)
                else None
            ),
        }

    def run_events(self, run_id: str) -> tuple[dict[str, object], ...]:
        """Read a bounded gap-free durable backlog.

        Live SSE remains open. A short read timeout is an intentional snapshot
        boundary after already-buffered complete frames; zero received bytes is
        still an outage. Candidate/release callers normally use terminal Runs,
        whose official stream closes immediately.
        """

        rid = _control_id(run_id, "run_id")
        token = self._api_key()
        timeout = httpx.Timeout(
            connect=self.settings.timeout_seconds,
            read=min(self.settings.timeout_seconds, 0.25),
            write=self.settings.timeout_seconds,
            pool=self.settings.timeout_seconds,
        )
        chunks: list[bytes] = []
        total = 0
        try:
            with (
                httpx.Client(
                    base_url=self.base_url,
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                    headers={
                        "accept": "text/event-stream",
                        "authorization": f"Bearer {token}",
                    },
                ) as client,
                client.stream(
                    "GET",
                    f"/v1/runs/{quote(rid, safe='')}/events",
                ) as response,
            ):
                if response.status_code != 200:
                    raw_error = response.read()
                    raise HermesRunControlError(
                        _upstream_error_code(raw_error)
                        or (
                            "run_not_found"
                            if response.status_code == 404
                            else "upstream_unavailable"
                        ),
                        "Hermes Run event replay is unavailable",
                    )
                if not response.headers.get("content-type", "").startswith(
                    "text/event-stream"
                ):
                    raise HermesRunControlError(
                        "invalid_upstream_response",
                        "Hermes Run event replay response is invalid",
                    )
                try:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.settings.max_response_bytes:
                            raise HermesRunControlError(
                                "response_too_large",
                                "Hermes Run event replay exceeded the configured bound",
                            )
                        chunks.append(chunk)
                except httpx.TimeoutException:
                    if not chunks:
                        raise
        except HermesRunControlError:
            raise
        except httpx.TimeoutException as exc:
            raise HermesRunControlError(
                "upstream_timeout",
                "Hermes Run event replay timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise HermesRunControlError(
                "upstream_unavailable",
                "Hermes Run event replay is unavailable",
            ) from exc
        events = _parse_run_sse(b"".join(chunks), expected_run_id=rid)
        expected_seq = 1
        for event in events:
            if event["seq"] != expected_seq:
                raise HermesRunControlError(
                    "run_event_replay_incomplete",
                    "Hermes Run event replay is not gap-free",
                )
            expected_seq += 1
        return events

    def _approval_observations(
        self,
        run_id: str,
    ) -> dict[str, _ApprovalObservation]:
        observations: dict[str, _ApprovalObservation] = {}
        for event in self.run_events(run_id):
            event_type = event["event"]
            challenge_value = event.get("challenge_id")
            if event_type == "approval.request":
                challenge_id = _control_id(challenge_value, "challenge_id")
                approval_id = _control_id(event.get("approval_id"), "approval_id")
                action_digest = _control_digest(
                    event.get("action_digest"),
                    "action_digest",
                )
                expires_at = _canonical_control_timestamp(
                    event.get("expires_at"),
                    "expires_at",
                )
                observations[challenge_id] = _ApprovalObservation(
                    challenge_id=challenge_id,
                    approval_id=approval_id,
                    run_id=run_id,
                    action_digest=action_digest,
                    expires_at=expires_at,
                    state="pending",
                )
                continue
            if (
                event_type in _APPROVAL_TERMINAL_EVENTS
                and isinstance(challenge_value, str)
                and challenge_value in observations
            ):
                current = observations[challenge_value]
                choice = event.get("choice")
                if choice not in {"once", "deny"}:
                    raise HermesRunControlError(
                        "invalid_upstream_response",
                        "Hermes approval decision event is invalid",
                    )
                if (
                    event.get("approval_id") != current.approval_id
                    or event.get("action_digest") != current.action_digest
                ):
                    raise HermesRunControlError(
                        "invalid_upstream_response",
                        "Hermes approval decision identity mismatches",
                    )
                observations[challenge_value] = _ApprovalObservation(
                    challenge_id=current.challenge_id,
                    approval_id=current.approval_id,
                    run_id=current.run_id,
                    action_digest=current.action_digest,
                    expires_at=current.expires_at,
                    state="decided",
                    choice=str(choice),
                )
        return observations

    def pending_approvals(
        self,
        run_ids: tuple[str, ...],
    ) -> tuple[dict[str, object], ...]:
        if len(run_ids) > 64 or len(set(run_ids)) != len(run_ids):
            raise HermesRunControlError(
                "run_control_validation",
                "run_ids must be a bounded distinct set",
            )
        self._require_control_ready(feature="run_approval_response")
        pending: list[dict[str, object]] = []
        now = datetime.now(UTC)
        for run_id in sorted(run_ids):
            for observation in self._approval_observations(run_id).values():
                expiry = datetime.fromisoformat(
                    observation.expires_at.replace("Z", "+00:00")
                )
                if observation.state == "pending" and expiry > now:
                    pending.append(observation.to_public_pending())
        return tuple(
            sorted(
                pending,
                key=lambda row: (
                    str(row["expires_at"]),
                    str(row["approval_id"]),
                ),
            )
        )

    def respond_approval_exact(
        self,
        run_id: str,
        *,
        choice: str,
        challenge_id: str,
        action_digest: str,
        expected_status: str,
        expected_expires_at: str,
    ) -> ApprovalReleaseResult:
        rid = _control_id(run_id, "run_id")
        challenge = _control_id(challenge_id, "challenge_id")
        digest = _control_digest(action_digest, "action_digest")
        if choice not in {"once", "deny"} or expected_status != "pending":
            raise HermesRunControlError(
                "run_control_validation",
                "approval choice/status is invalid",
            )
        expiry = _canonical_control_timestamp(
            expected_expires_at,
            "expected_expires_at",
        )
        self._require_control_ready(feature="run_approval_response")
        observation = self._approval_observations(rid).get(challenge)
        if (
            observation is None
            or observation.action_digest != digest
            or observation.expires_at != expiry
            or (
                observation.state == "decided"
                and observation.choice != choice
            )
            or (
                observation.state == "pending"
                and datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                <= datetime.now(UTC)
            )
        ):
            raise HermesRunControlError(
                "approval_exact_binding_conflict",
                "Hermes approval challenge no longer matches the exact action",
            )
        raw = self._post_json(
            f"/v1/runs/{quote(rid, safe='')}/approval",
            {
                "choice": choice,
                "challenge_id": challenge,
                "action_digest": digest,
            },
        )
        signal_status = raw.get("waiter_signal_status")
        if (
            raw.get("object") != "hermes.run.approval_response"
            or raw.get("run_id") != rid
            or raw.get("choice") != choice
            or raw.get("decision_status") != "committed"
            or signal_status not in {"confirmed", "unknown"}
            or raw.get("challenge_id") != challenge
            or raw.get("approval_id") != observation.approval_id
            or raw.get("action_digest") != digest
            or (
                "idempotent_replay" in raw
                and type(raw["idempotent_replay"]) is not bool
            )
        ):
            raise HermesRunControlError(
                "outcome_unknown",
                "Hermes approval committed outcome could not be verified",
            )
        return ApprovalReleaseResult(
            run_id=rid,
            choice=choice,
            decision_status="committed",
            waiter_signal_status=signal_status,
            idempotent_replay=raw.get("idempotent_replay") is True,
            challenge_id=challenge,
            action_digest=digest,
        )

    def stop(self, run_id: str) -> StopResult:
        rid = _control_id(run_id, "run_id")
        self._require_control_ready(feature="run_stop")
        raw = self._post_json(
            f"/v1/runs/{quote(rid, safe='')}/stop",
            {},
        )
        status = raw.get("status")
        if (
            raw.get("run_id") != rid
            or status not in _RUN_STATES
            or (
                "idempotent_replay" in raw
                and type(raw["idempotent_replay"]) is not bool
            )
            or (
                status == "running"
                and raw.get("substate") != "stopping"
            )
        ):
            raise HermesRunControlError(
                "outcome_unknown",
                "Hermes Run-stop outcome could not be verified",
            )
        replay = raw.get("idempotent_replay") is True
        if status == "running":
            try:
                observed = self.run_status(rid)
            except HermesRunControlError:
                # The POST response proves the durable stop intent was
                # accepted. A failed immediate read cannot upgrade it to
                # terminal; callers keep the Run in reconciliation.
                observed = {"status": "running"}
            status = observed["status"]
        return StopResult(
            run_id=rid,
            status=str(status),
            idempotent_replay=(
                replay and status in _RUN_TERMINAL_STATES
            ),
        )


def _upstream_error_code(raw: bytes) -> str | None:
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    error = document.get("error") if isinstance(document, Mapping) else None
    code = error.get("code") if isinstance(error, Mapping) else None
    return (
        str(code)
        if isinstance(code, str) and _CONTROL_ID_RE.fullmatch(code) is not None
        else None
    )


def _parse_run_sse(
    raw: bytes,
    *,
    expected_run_id: str,
) -> tuple[dict[str, object], ...]:
    try:
        text = raw.decode("utf-8", errors="strict").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise HermesRunControlError(
            "invalid_upstream_response",
            "Hermes Run event replay is invalid",
        ) from exc
    events: list[dict[str, object]] = []
    for block in text.split("\n\n"):
        if not block or block.startswith(":"):
            continue
        seq: int | None = None
        event_type: str | None = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("id:"):
                try:
                    seq = int(line[3:].strip())
                except ValueError:
                    seq = None
            elif line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if seq is None or seq < 1 or not event_type or not data_lines:
            raise HermesRunControlError(
                "invalid_upstream_response",
                "Hermes Run event frame is invalid",
            )
        try:
            document = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise HermesRunControlError(
                "invalid_upstream_response",
                "Hermes Run event payload is invalid",
            ) from exc
        if (
            not isinstance(document, dict)
            or document.get("run_id") != expected_run_id
            or document.get("seq") != seq
            or document.get("event") != event_type
        ):
            raise HermesRunControlError(
                "invalid_upstream_response",
                "Hermes Run event identity is invalid",
            )
        events.append(document)
    return tuple(events)
