from __future__ import annotations

import json
import math
import os
import re
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from quant_system.config.settings import HermesGatewaySettings


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
        return {
            "model": _bounded_text(raw.get("model"), maximum=256),
            "features": features,
            "contract_version": contract_version,
            "durable": durable,
            "managed_session_contract": managed_session_contract,
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
            message_id = str(row.get("id") if row.get("id") is not None else index)
            if not message_id or len(message_id) > 256:
                message_id = str(index)
            messages.append(
                {
                    "id": message_id,
                    "role": str(row["role"]),
                    "content": content,
                    "timestamp": _normalized_timestamp(row.get("timestamp")),
                }
            )
        bounded = messages[-self.settings.max_messages :]
        return {
            "session_id": sid,
            "data": bounded,
            "omitted_message_count": max(0, len(rows) - len(bounded)),
        }
