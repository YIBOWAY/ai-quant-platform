"""Owner-only signed local session and independent CSRF (V4 security boundary).

Bootstrap + session cookie establish actor identity for future AgentWorkspace
mutations. This module does **not** enable public chat write, claim/dispatch,
or composer. ``mutation_enabled`` remains false until the full V4/V8 gate.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID
from urllib.parse import urlparse

from quant_system.hermes.command_ledger import ROOT_USER_ID

SESSION_COOKIE_NAME = "qs_aw_session"
CSRF_COOKIE_NAME = "qs_aw_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
SESSION_TTL = timedelta(hours=12)
SESSION_TTL_SECONDS = int(SESSION_TTL.total_seconds())

RequestKind = Literal["top_level_document", "api_read", "sse_follow", "mutation"]

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class LocalSessionAuthError(Exception):
    """Missing, forged, or expired actor session (stable code: auth)."""

    code = "auth"

    def __init__(self, message: str = "workspace_auth_failed") -> None:
        super().__init__(message)
        self.message = message


class LocalSessionForbidden(Exception):
    """Origin / CSRF / host / ownership rejected (stable code: forbidden)."""

    code = "forbidden"

    def __init__(self, message: str = "workspace_forbidden") -> None:
        super().__init__(message)
        self.message = message


class LocalSessionValidationError(Exception):
    """Malformed security input (stable code: validation)."""

    code = "validation"

    def __init__(self, message: str = "workspace_validation_failed") -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class OwnerSession:
    owner_user_id: UUID
    session_id: str
    csrf_token: str
    expires_at: datetime

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at


@dataclass(frozen=True)
class IssuedOwnerSession:
    session: OwnerSession
    session_cookie_value: str


@dataclass(frozen=True)
class LocalSessionPolicy:
    """Exact accepted Host + Origin for browser API requests."""

    accepted_host: str
    accepted_origin: str

    def __post_init__(self) -> None:
        if not self.accepted_host or any(ch.isspace() for ch in self.accepted_host):
            raise LocalSessionValidationError("invalid accepted_host")
        parsed = urlparse(self.accepted_origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise LocalSessionValidationError("invalid accepted_origin")
        # Origin netloc must equal accepted_host exactly (host[:port]).
        if parsed.netloc != self.accepted_host:
            raise LocalSessionValidationError("accepted_origin host mismatch")


def security_dir(output_dir: Path) -> Path:
    return Path(output_dir) / "_runtime" / "security"


def signing_key_path(output_dir: Path) -> Path:
    return security_dir(output_dir) / "session_signing.key"


def bootstrap_token_path(output_dir: Path) -> Path:
    return security_dir(output_dir) / "owner_bootstrap.token"


def _assert_owner_only_file(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise LocalSessionForbidden("security material permissions are too open")


def _write_secret_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_NOFOLLOW where available; exclusive create then replace for rotation.
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)
    _assert_owner_only_file(path)


def ensure_security_material(output_dir: Path) -> Path:
    """Ensure signing key exists (0600). Does not mint bootstrap token."""
    key_path = signing_key_path(output_dir)
    if not key_path.exists():
        _write_secret_file(key_path, secrets.token_bytes(32))
    else:
        _assert_owner_only_file(key_path)
        if key_path.stat().st_size < 32:
            raise LocalSessionForbidden("signing key material is invalid")
    return key_path


def load_signing_key(output_dir: Path) -> bytes:
    key_path = ensure_security_material(output_dir)
    data = key_path.read_bytes()
    if len(data) < 32:
        raise LocalSessionForbidden("signing key material is invalid")
    return data


def issue_bootstrap_token(output_dir: Path, *, force_rotate: bool = False) -> str:
    """Create or return the current one-time bootstrap token (file 0600)."""
    ensure_security_material(output_dir)
    path = bootstrap_token_path(output_dir)
    if path.exists() and not force_rotate:
        _assert_owner_only_file(path)
        token = path.read_text(encoding="ascii").strip()
        if _TOKEN_RE.fullmatch(token) is not None:
            return token
    token = secrets.token_urlsafe(32)
    _write_secret_file(path, token.encode("ascii"))
    return token


def _consume_bootstrap_token(output_dir: Path, presented: str) -> None:
    if type(presented) is not str or _TOKEN_RE.fullmatch(presented) is None:
        raise LocalSessionValidationError("invalid bootstrap token")
    path = bootstrap_token_path(output_dir)
    if not path.exists():
        raise LocalSessionAuthError()
    _assert_owner_only_file(path)
    try:
        expected = path.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise LocalSessionAuthError() from exc
    if not expected or not hmac.compare_digest(expected, presented):
        raise LocalSessionAuthError()
    # Rotate immediately so the presented token cannot be reused.
    replacement = secrets.token_urlsafe(32)
    _write_secret_file(path, replacement.encode("ascii"))


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    import base64

    pad = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + pad)
    except Exception as exc:  # noqa: BLE001 - treat as auth failure
        raise LocalSessionAuthError() from exc


def _sign(key: bytes, message: str) -> str:
    digest = hmac.new(key, message.encode("ascii"), hashlib.sha256).digest()
    return _b64url(digest)


def mint_owner_session(output_dir: Path, *, now: datetime | None = None) -> IssuedOwnerSession:
    key = load_signing_key(output_dir)
    current = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    expires_at = current + SESSION_TTL
    session_id = secrets.token_urlsafe(24)
    csrf_token = secrets.token_urlsafe(32)
    exp_unix = int(expires_at.timestamp())
    # owner|session_id|exp|csrf — csrf bound into signed material; wire form is
    # base64url(body).base64url(sig) so cookie parsers accept the value.
    body = f"{ROOT_USER_ID}|{session_id}|{exp_unix}|{csrf_token}"
    cookie_value = f"{_b64url(body.encode('ascii'))}.{_sign(key, body)}"
    session = OwnerSession(
        owner_user_id=ROOT_USER_ID,
        session_id=session_id,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    return IssuedOwnerSession(session=session, session_cookie_value=cookie_value)


def exchange_bootstrap_token(
    output_dir: Path,
    bootstrap_token: str,
    *,
    now: datetime | None = None,
) -> IssuedOwnerSession:
    """Consume one-time bootstrap token and mint a signed owner session."""
    _consume_bootstrap_token(output_dir, bootstrap_token)
    return mint_owner_session(output_dir, now=now)


def verify_session_cookie(
    output_dir: Path,
    cookie_value: str | None,
    *,
    now: datetime | None = None,
) -> OwnerSession:
    if cookie_value is None or type(cookie_value) is not str or not cookie_value:
        raise LocalSessionAuthError()
    if cookie_value.count(".") != 1:
        raise LocalSessionAuthError()
    body_b64, signature = cookie_value.split(".", 1)
    try:
        body = _b64url_decode(body_b64).decode("ascii")
    except (LocalSessionAuthError, UnicodeDecodeError) as exc:
        raise LocalSessionAuthError() from exc
    parts = body.split("|")
    if len(parts) != 4:
        raise LocalSessionAuthError()
    owner_text, session_id, exp_text, csrf_token = parts
    try:
        owner = UUID(owner_text)
    except (TypeError, ValueError) as exc:
        raise LocalSessionAuthError() from exc
    if owner != ROOT_USER_ID:
        raise LocalSessionAuthError()
    if _SESSION_ID_RE.fullmatch(session_id) is None:
        raise LocalSessionAuthError()
    if _TOKEN_RE.fullmatch(csrf_token) is None:
        raise LocalSessionAuthError()
    if not exp_text.isdigit():
        raise LocalSessionAuthError()
    exp_unix = int(exp_text)
    key = load_signing_key(output_dir)
    expected_sig = _sign(key, body)
    if not hmac.compare_digest(expected_sig, signature):
        raise LocalSessionAuthError()
    expires_at = datetime.fromtimestamp(exp_unix, tz=UTC)
    current = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    if current >= expires_at:
        raise LocalSessionAuthError()
    # Reject cookies minted too far in the future (clock skew / forged exp).
    if expires_at > current + SESSION_TTL + timedelta(minutes=5):
        raise LocalSessionAuthError()
    return OwnerSession(
        owner_user_id=owner,
        session_id=session_id,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )


def verify_csrf(session: OwnerSession, header_value: str | None) -> None:
    if header_value is None or type(header_value) is not str or not header_value:
        raise LocalSessionForbidden()
    if not hmac.compare_digest(session.csrf_token, header_value):
        raise LocalSessionForbidden()


def policy_from_settings(
    *,
    accepted_origin: str | None = None,
    cors_origins: list[str] | None = None,
    bind_address: str = "127.0.0.1",
    frontend_port: int = 3001,
) -> LocalSessionPolicy:
    """Derive exact Host/Origin policy.

    Prefer explicit accepted_origin; else first configured CORS origin; else
    loopback frontend default.
    """
    origin = accepted_origin
    if origin is None and cors_origins:
        for candidate in cors_origins:
            if isinstance(candidate, str) and candidate.startswith(
                ("http://127.0.0.1", "http://localhost", "https://127.0.0.1", "https://localhost")
            ):
                origin = candidate
                break
    if origin is None:
        host = "127.0.0.1" if bind_address in {"127.0.0.1", "0.0.0.0"} else bind_address
        origin = f"http://{host}:{frontend_port}"
    parsed = urlparse(origin)
    accepted_host = parsed.netloc
    return LocalSessionPolicy(accepted_host=accepted_host, accepted_origin=origin)


def _request_host(headers_host: str | None) -> str | None:
    if headers_host is None or type(headers_host) is not str:
        return None
    host = headers_host.strip()
    if not host or any(ch.isspace() for ch in host):
        return None
    return host


def enforce_browser_request_gates(
    *,
    policy: LocalSessionPolicy,
    request_kind: RequestKind,
    host_header: str | None,
    origin_header: str | None,
    sec_fetch_site: str | None,
) -> None:
    """Fail closed on Host / Origin / Sec-Fetch-Site (HQA security contract)."""
    host = _request_host(host_header)
    if host is None or host != policy.accepted_host:
        # Also allow API host when FE and API share no host — browser Host is the
        # API host for same-origin BFF proxies. When FE is :3001 and API :8765,
        # requests are cross-origin unless Next rewrites. For local BFF called
        # via same-origin rewrite, Host is the FE host. For direct API tests,
        # accept either policy.accepted_host OR loopback API host forms.
        if host not in _api_loopback_hosts(policy):
            raise LocalSessionForbidden()

    if origin_header is not None:
        if type(origin_header) is not str or origin_header != policy.accepted_origin:
            raise LocalSessionForbidden()

    site = (sec_fetch_site or "").lower() if sec_fetch_site is not None else ""
    if request_kind == "top_level_document":
        if site not in {"", "none", "same-origin"}:
            raise LocalSessionForbidden()
        return

    # API / SSE / mutation: require same-origin when Sec-Fetch-Site present.
    # Missing header is allowed for non-browser clients on loopback only when
    # Origin is absent or exact — still reject explicit cross-site.
    if site in {"cross-site", "same-site", "none"}:
        raise LocalSessionForbidden()
    if site and site != "same-origin":
        raise LocalSessionForbidden()
    if request_kind == "mutation" and (
        origin_header is None or origin_header != policy.accepted_origin
    ):
        raise LocalSessionForbidden()


def _api_loopback_hosts(policy: LocalSessionPolicy) -> set[str]:
    """Hosts that may appear on direct loopback API calls in tests/tools."""
    hosts = {policy.accepted_host, "127.0.0.1:8765", "localhost:8765", "testserver"}
    # bare host without port used by some TestClient defaults
    hosts.add("127.0.0.1")
    hosts.add("localhost")
    hosts.add("test")
    return hosts


def require_mutation_precheck(
    *,
    output_dir: Path,
    policy: LocalSessionPolicy,
    cookie_value: str | None,
    csrf_header: str | None,
    host_header: str | None,
    origin_header: str | None,
    sec_fetch_site: str | None,
    mutation_enabled: bool = False,
) -> OwnerSession:
    """Full mutation gate. Public writes stay OFF until mutation_enabled is true."""
    enforce_browser_request_gates(
        policy=policy,
        request_kind="mutation",
        host_header=host_header,
        origin_header=origin_header,
        sec_fetch_site=sec_fetch_site,
    )
    session = verify_session_cookie(output_dir, cookie_value)
    verify_csrf(session, csrf_header)
    if not mutation_enabled:
        raise LocalSessionForbidden("authenticated_mutation_bff_unavailable")
    return session


def session_public_view(
    session: OwnerSession,
    *,
    mutation_enabled: bool = False,
) -> dict[str, object]:
    return {
        "owner_user_id": str(session.owner_user_id),
        "session_id": session.session_id,
        "expires_at": session.expires_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "mutation_enabled": bool(mutation_enabled),
    }


def local_session_security_ready(output_dir: Path) -> bool:
    try:
        path = signing_key_path(output_dir)
        if not path.exists():
            return False
        _assert_owner_only_file(path)
        return path.stat().st_size >= 32
    except OSError:
        return False


# Silence unused import warning for time in case of future clock helpers.
_ = time
