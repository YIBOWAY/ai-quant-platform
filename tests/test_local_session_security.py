"""V4 local owner session + CSRF fail-closed tests."""

from __future__ import annotations

import re
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_system.api.safety.local_session import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    LocalSessionAuthError,
    LocalSessionForbidden,
    bootstrap_lock_path,
    bootstrap_token_path,
    exchange_bootstrap_token,
    issue_bootstrap_token,
    local_session_security_ready,
    mint_owner_session,
    policy_from_settings,
    require_loopback_peer,
    require_mutation_precheck,
    signing_key_path,
    verify_csrf,
    verify_session_cookie,
)
from quant_system.api.safety.mutation_rate_limit import OwnerMutationRateLimiter
from quant_system.api.server import create_app
from quant_system.config.settings import HermesGatewaySettings, Settings
from quant_system.hermes.command_ledger import ROOT_USER_ID

ORIGIN = "http://127.0.0.1:3001"


def _settings() -> Settings:
    from quant_system.config.settings import LocalMutationSettings

    return Settings(
        hermes_gateway=HermesGatewaySettings(enabled=False),
        local_mutation=LocalMutationSettings(enabled=False, composer_open=False),
        api_cors_origins=[
            ORIGIN,
            "http://127.0.0.1:3000",
            "http://localhost:3001",
        ],
    )


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        settings=_settings(),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    return TestClient(app)


def _browser_headers(*, origin: str = ORIGIN, site: str = "same-origin") -> dict[str, str]:
    return {
        "Origin": origin,
        "Sec-Fetch-Site": site,
        "Host": "testserver",
    }


def test_default_policy_accepts_frontend_port_3001() -> None:
    """Default CORS order must pin accepted_origin to the real FE port."""
    from quant_system.config.settings import Settings

    settings = Settings()
    policy = policy_from_settings(
        cors_origins=list(settings.api_cors_origins),
        bind_address="127.0.0.1",
    )
    assert policy.accepted_origin == "http://127.0.0.1:3001"
    assert policy.accepted_host == "127.0.0.1:3001"


def test_bootstrap_issues_http_only_session_and_csrf(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = issue_bootstrap_token(tmp_path)
    key = signing_key_path(tmp_path)
    assert key.exists()
    assert stat.S_IMODE(key.stat().st_mode) == 0o600

    response = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["owner_user_id"] == str(ROOT_USER_ID)
    assert payload["mutation_enabled"] is False
    assert payload["csrf_token"]
    assert payload["csrf_header"] == CSRF_HEADER_NAME

    # Cookies — both must survive safety-footer rebuild (multi Set-Cookie).
    assert SESSION_COOKIE_NAME in response.cookies
    assert CSRF_COOKIE_NAME in response.cookies
    get_list = getattr(response.headers, "get_list", None) or getattr(
        response.headers, "getlist", None
    )
    if get_list is not None:
        set_cookie_headers = get_list("set-cookie")
    else:
        raw = response.headers.get("set-cookie", "")
        set_cookie_headers = [raw] if raw else []
    session_header = next(
        (h for h in set_cookie_headers if h.startswith(f"{SESSION_COOKIE_NAME}=")),
        "",
    )
    csrf_header = next(
        (h for h in set_cookie_headers if h.startswith(f"{CSRF_COOKIE_NAME}=")),
        "",
    )
    if session_header:
        assert "httponly" in session_header.lower()
        assert "samesite=strict" in session_header.lower()
    if csrf_header:
        assert "samesite=strict" in csrf_header.lower()

    status = client.get("/api/auth/owner/session", headers=_browser_headers())
    assert status.status_code == 200
    assert status.json()["session_id"] == payload["session_id"]
    assert status.json()["mutation_enabled"] is False


def test_loopback_http_cannot_issue_or_retrieve_bootstrap_token(
    tmp_path: Path,
) -> None:
    """Bootstrap secrets are operator input, never an unauthenticated API."""
    client = _client(tmp_path)

    response = client.post(
        "/api/auth/owner/bootstrap-token/issue",
        headers=_browser_headers(),
    )

    assert response.status_code == 404
    assert "bootstrap_token" not in response.text


def test_bootstrap_token_is_one_time(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = issue_bootstrap_token(tmp_path)
    first = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert first.status_code == 200
    second = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert second.status_code == 401
    assert second.json()["detail"]["code"] == "auth"


def test_secret_rotation_is_atomic_and_refuses_symlink(
    tmp_path: Path,
) -> None:
    token = issue_bootstrap_token(tmp_path)
    token_path = bootstrap_token_path(tmp_path)
    old_inode = token_path.stat().st_ino
    rotated = issue_bootstrap_token(tmp_path, force_rotate=True)
    assert rotated != token
    assert token_path.stat().st_ino != old_inode
    assert stat.S_IMODE(token_path.stat().st_mode) == 0o600

    victim = tmp_path / "must-not-be-overwritten"
    victim.write_text("preserve-me", encoding="utf-8")
    token_path.unlink()
    token_path.symlink_to(victim)
    with pytest.raises(LocalSessionForbidden):
        issue_bootstrap_token(tmp_path, force_rotate=True)
    assert victim.read_text(encoding="utf-8") == "preserve-me"


def test_security_material_must_be_owner_only_regular_file(
    tmp_path: Path,
) -> None:
    issued = mint_owner_session(tmp_path)
    key_path = signing_key_path(tmp_path)
    key_path.chmod(0o640)

    with pytest.raises(LocalSessionForbidden):
        verify_session_cookie(tmp_path, issued.session_cookie_value)

    assert local_session_security_ready(tmp_path) is False


def test_bootstrap_lock_refuses_symlink_without_touching_target(
    tmp_path: Path,
) -> None:
    token = issue_bootstrap_token(tmp_path)
    victim = tmp_path / "must-not-be-locked"
    victim.write_text("preserve-me", encoding="utf-8")
    lock_path = bootstrap_lock_path(tmp_path)
    lock_path.symlink_to(victim)

    with pytest.raises(LocalSessionForbidden):
        exchange_bootstrap_token(tmp_path, token)
    assert victim.read_text(encoding="utf-8") == "preserve-me"


def test_concurrent_bootstrap_exchange_has_exactly_one_winner(
    tmp_path: Path,
) -> None:
    token = issue_bootstrap_token(tmp_path)
    ready = threading.Barrier(8)

    def _exchange(_index: int) -> bool:
        ready.wait(timeout=3)
        try:
            exchange_bootstrap_token(tmp_path, token)
        except LocalSessionAuthError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        winners = list(pool.map(_exchange, range(8)))
    assert winners.count(True) == 1


def test_concurrent_signing_key_initialization_never_invalidates_sessions(
    tmp_path: Path,
) -> None:
    ready = threading.Barrier(8)

    def _mint(_index: int):
        ready.wait(timeout=3)
        return mint_owner_session(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as pool:
        issued = list(pool.map(_mint, range(8)))

    for item in issued:
        assert (
            verify_session_cookie(tmp_path, item.session_cookie_value).owner_user_id
            == ROOT_USER_ID
        )


def test_forged_and_expired_cookie_fail(tmp_path: Path) -> None:
    issued = exchange_bootstrap_token(tmp_path, issue_bootstrap_token(tmp_path))
    with pytest.raises(LocalSessionAuthError):
        verify_session_cookie(tmp_path, issued.session_cookie_value + "x")
    with pytest.raises(LocalSessionAuthError):
        verify_session_cookie(tmp_path, None)
    # Tamper payload while keeping shape
    body_b64, sig = issued.session_cookie_value.split(".", 1)
    with pytest.raises(LocalSessionAuthError):
        verify_session_cookie(tmp_path, f"{body_b64}x.{sig}")


def test_cross_origin_and_sec_fetch_site_fail_closed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = issue_bootstrap_token(tmp_path)
    ok = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert ok.status_code == 200

    cross = client.get(
        "/api/auth/owner/session",
        headers=_browser_headers(origin="http://evil.example", site="cross-site"),
    )
    assert cross.status_code == 403
    assert cross.json()["detail"]["code"] == "forbidden"

    none_site = client.get(
        "/api/auth/owner/session",
        headers=_browser_headers(site="none"),
    )
    assert none_site.status_code == 403


def test_actual_client_peer_must_be_loopback() -> None:
    require_loopback_peer("127.0.0.1")
    require_loopback_peer("::1")
    require_loopback_peer("testclient")
    with pytest.raises(LocalSessionForbidden):
        require_loopback_peer("192.0.2.25")
    with pytest.raises(LocalSessionForbidden):
        require_loopback_peer(None)


def test_owner_http_surface_rejects_non_loopback_asgi_peer(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    remote = TestClient(app, client=("192.0.2.25", 50123))
    token = issue_bootstrap_token(tmp_path)
    denied = remote.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "forbidden"
    assert token not in denied.text

    # The rejected peer did not consume the one-time token.
    loopback = TestClient(app)
    accepted = loopback.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert accepted.status_code == 200


def test_bootstrap_returns_bounded_429_without_disclosing_token(
    tmp_path: Path,
) -> None:
    app = create_app(
        settings=_settings(),
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    app.state.services["owner_mutation_rate_limiter"] = OwnerMutationRateLimiter(
        max_requests=1,
        window_seconds=60,
    )
    client = TestClient(app)
    token = issue_bootstrap_token(tmp_path)
    wrong = "x" * len(token)

    first = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": wrong},
        headers=_browser_headers(),
    )
    assert first.status_code == 401
    limited = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["detail"]["code"] == "mutation_rate_limited"
    assert token not in limited.text
    assert wrong not in limited.text


def test_mutation_precheck_requires_csrf_and_stays_disabled(tmp_path: Path) -> None:
    issued = exchange_bootstrap_token(tmp_path, issue_bootstrap_token(tmp_path))
    policy = policy_from_settings(accepted_origin=ORIGIN, bind_address="127.0.0.1")

    with pytest.raises(LocalSessionForbidden):
        require_mutation_precheck(
            output_dir=tmp_path,
            policy=policy,
            cookie_value=issued.session_cookie_value,
            csrf_header=None,
            host_header="testserver",
            origin_header=ORIGIN,
            sec_fetch_site="same-origin",
            mutation_enabled=False,
        )

    with pytest.raises(LocalSessionForbidden):
        verify_csrf(issued.session, "not-the-token")

    # Correct CSRF still fails closed because mutation_enabled is false.
    with pytest.raises(LocalSessionForbidden) as excinfo:
        require_mutation_precheck(
            output_dir=tmp_path,
            policy=policy,
            cookie_value=issued.session_cookie_value,
            csrf_header=issued.session.csrf_token,
            host_header="testserver",
            origin_header=ORIGIN,
            sec_fetch_site="same-origin",
            mutation_enabled=False,
        )
    assert "authenticated_mutation_bff_unavailable" in str(excinfo.value)


def test_health_mutation_still_false_with_session_module(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/api/health")
    assert response.status_code == 200
    ledger = response.json()["hermes_command_ledger"]
    assert ledger["mutation_enabled"] is False


def test_workspace_act_has_an_independent_owner_route_budget(
    tmp_path: Path,
) -> None:
    from quant_system.config.settings import LocalMutationSettings

    settings = _settings().model_copy(
        update={
            "local_mutation": LocalMutationSettings(
                enabled=True,
                composer_open=False,
            )
        }
    )
    app = create_app(
        settings=settings,
        output_dir=tmp_path,
        bind_address="127.0.0.1",
    )
    app.state.services["owner_mutation_rate_limiter"] = OwnerMutationRateLimiter(
        max_requests=1,
        window_seconds=60,
    )
    client = TestClient(app)
    token = issue_bootstrap_token(tmp_path)
    boot = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    csrf = boot.json()["csrf_token"]
    headers = {**_browser_headers(), CSRF_HEADER_NAME: csrf}
    body = {
        "action": {
            "schema_version": 1,
            "kind": "managed_session.create",
            "client_action_id": "rate-limit-action",
            "workspace": {"workspace_id": "ws-rate-limit"},
            "provider_policy_digest": "a" * 64,
            "payload_ttl_days": 7,
        }
    }

    first = client.post("/api/workspace/ws-rate-limit/act", json=body, headers=headers)
    assert first.status_code != 429
    limited = client.post("/api/workspace/ws-rate-limit/act", json=body, headers=headers)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.json()["detail"]["code"] == "mutation_rate_limited"
    assert token not in limited.text
    assert csrf not in limited.text


def test_logout_clears_cookies(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = issue_bootstrap_token(tmp_path)
    boot = client.post(
        "/api/auth/owner/bootstrap",
        json={"bootstrap_token": token},
        headers=_browser_headers(),
    )
    assert boot.status_code == 200
    logout = client.post("/api/auth/owner/logout", headers=_browser_headers())
    assert logout.status_code == 200
    assert logout.json()["mutation_enabled"] is False
    # After logout, session read fails
    status = client.get("/api/auth/owner/session", headers=_browser_headers())
    assert status.status_code == 401


def test_minted_session_only_root_owner(tmp_path: Path) -> None:
    issued = mint_owner_session(tmp_path)
    session = verify_session_cookie(tmp_path, issued.session_cookie_value)
    assert session.owner_user_id == ROOT_USER_ID
    assert re.fullmatch(r"[A-Za-z0-9_-]+", session.session_id)
