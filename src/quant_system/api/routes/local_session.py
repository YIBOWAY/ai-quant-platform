"""Owner bootstrap and local session routes (V4). Mutation paths stay closed."""

from __future__ import annotations

from contextlib import suppress

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from quant_system.api.dependencies import (
    OutputDirDep,
    SettingsDep,
    consume_owner_mutation_budget,
    get_bind_address,
)
from quant_system.api.safety.local_session import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    LocalSessionAuthError,
    LocalSessionForbidden,
    LocalSessionValidationError,
    enforce_browser_request_gates,
    exchange_bootstrap_token,
    local_session_security_ready,
    policy_from_settings,
    require_loopback_peer,
    session_public_view,
    verify_session_cookie,
)
from quant_system.api.safety.mutation_rate_limit import OWNER_BOOTSTRAP_ROUTE
from quant_system.api.schemas.local_session import (
    OwnerBootstrapResponse,
    OwnerLogoutResponse,
    OwnerSessionStatusResponse,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID

router = APIRouter()


class BootstrapRequest(BaseModel):
    bootstrap_token: str = Field(min_length=32, max_length=256)


def _http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "validation")
    message = getattr(exc, "message", "workspace_validation_failed")
    status = 401 if code == "auth" else 403 if code == "forbidden" else 422
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _policy(settings: SettingsDep, request: Request):
    bind = get_bind_address(request)
    return policy_from_settings(
        cors_origins=list(settings.api_cors_origins),
        bind_address=bind,
    )


def _set_session_cookies(
    response: Response,
    *,
    session_cookie_value: str,
    csrf_token: str,
    secure: bool,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_cookie_value,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )
    # Independent CSRF cookie readable by same-origin JS (double-submit style),
    # still verified against the HMAC-bound session value server-side.
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=False,
        samesite="strict",
        secure=secure,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


@router.post("/auth/owner/bootstrap", response_model=OwnerBootstrapResponse)
def owner_bootstrap(
    body: BootstrapRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    output_dir: OutputDirDep,
) -> dict:
    policy = _policy(settings, request)
    try:
        require_loopback_peer(request.client.host if request.client else None)
        enforce_browser_request_gates(
            policy=policy,
            request_kind="mutation",
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
        )
        consume_owner_mutation_budget(
            request,
            owner_user_id=ROOT_USER_ID,
            route=OWNER_BOOTSTRAP_ROUTE,
        )
        issued = exchange_bootstrap_token(output_dir, body.bootstrap_token)
    except (LocalSessionAuthError, LocalSessionForbidden, LocalSessionValidationError) as exc:
        raise _http_error(exc) from exc

    secure = request.url.scheme == "https"
    _set_session_cookies(
        response,
        session_cookie_value=issued.session_cookie_value,
        csrf_token=issued.session.csrf_token,
        secure=secure,
    )
    mutation_on = bool(getattr(settings.local_mutation, "enabled", False))
    view = session_public_view(issued.session, mutation_enabled=mutation_on)
    view["csrf_token"] = issued.session.csrf_token
    view["csrf_header"] = CSRF_HEADER_NAME
    view["security_ready"] = local_session_security_ready(output_dir)
    response.headers["Cache-Control"] = "no-store"
    return view


@router.get("/auth/owner/session", response_model=OwnerSessionStatusResponse)
def owner_session_status(
    request: Request,
    settings: SettingsDep,
    output_dir: OutputDirDep,
) -> dict:
    policy = _policy(settings, request)
    try:
        require_loopback_peer(request.client.host if request.client else None)
        enforce_browser_request_gates(
            policy=policy,
            request_kind="api_read",
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
        )
        session = verify_session_cookie(
            output_dir, request.cookies.get(SESSION_COOKIE_NAME)
        )
    except (LocalSessionAuthError, LocalSessionForbidden, LocalSessionValidationError) as exc:
        raise _http_error(exc) from exc
    mutation_on = bool(getattr(settings.local_mutation, "enabled", False))
    view = session_public_view(session, mutation_enabled=mutation_on)
    view["security_ready"] = local_session_security_ready(output_dir)
    return view


@router.post("/auth/owner/logout", response_model=OwnerLogoutResponse)
def owner_logout(
    request: Request,
    response: Response,
    settings: SettingsDep,
    output_dir: OutputDirDep,
) -> dict:
    policy = _policy(settings, request)
    try:
        require_loopback_peer(request.client.host if request.client else None)
        enforce_browser_request_gates(
            policy=policy,
            request_kind="mutation",
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
        )
        # Best-effort verify; always clear cookies.
        with suppress(LocalSessionAuthError):
            verify_session_cookie(output_dir, request.cookies.get(SESSION_COOKIE_NAME))
    except (LocalSessionForbidden, LocalSessionValidationError) as exc:
        raise _http_error(exc) from exc
    _clear_session_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    mutation_on = bool(getattr(settings.local_mutation, "enabled", False))
    return {"ok": True, "mutation_enabled": mutation_on}
