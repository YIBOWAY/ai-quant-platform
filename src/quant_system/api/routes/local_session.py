"""Owner bootstrap and local session routes (V4). Mutation paths stay closed."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from quant_system.api.dependencies import OutputDirDep, SettingsDep, get_bind_address
from quant_system.api.safety.local_session import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    LocalSessionAuthError,
    LocalSessionForbidden,
    LocalSessionValidationError,
    exchange_bootstrap_token,
    enforce_browser_request_gates,
    issue_bootstrap_token,
    local_session_security_ready,
    policy_from_settings,
    session_public_view,
    verify_session_cookie,
)

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


@router.post("/auth/owner/bootstrap")
def owner_bootstrap(
    body: BootstrapRequest,
    request: Request,
    response: Response,
    settings: SettingsDep,
    output_dir: OutputDirDep,
) -> dict:
    policy = _policy(settings, request)
    try:
        enforce_browser_request_gates(
            policy=policy,
            request_kind="mutation",
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
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
    view = session_public_view(issued.session)
    view["csrf_token"] = issued.session.csrf_token
    view["csrf_header"] = CSRF_HEADER_NAME
    view["security_ready"] = local_session_security_ready(output_dir)
    # Never open writes from bootstrap alone.
    view["mutation_enabled"] = False
    response.headers["Cache-Control"] = "no-store"
    return view


@router.get("/auth/owner/session")
def owner_session_status(
    request: Request,
    settings: SettingsDep,
    output_dir: OutputDirDep,
) -> dict:
    policy = _policy(settings, request)
    try:
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
    view = session_public_view(session)
    view["security_ready"] = local_session_security_ready(output_dir)
    return view


@router.post("/auth/owner/logout")
def owner_logout(
    request: Request,
    response: Response,
    settings: SettingsDep,
    output_dir: OutputDirDep,
) -> dict:
    policy = _policy(settings, request)
    try:
        enforce_browser_request_gates(
            policy=policy,
            request_kind="mutation",
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
        )
        # Best-effort verify; always clear cookies.
        try:
            verify_session_cookie(output_dir, request.cookies.get(SESSION_COOKIE_NAME))
        except LocalSessionAuthError:
            pass
    except (LocalSessionForbidden, LocalSessionValidationError) as exc:
        raise _http_error(exc) from exc
    _clear_session_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "mutation_enabled": False}


@router.post("/auth/owner/bootstrap-token/issue")
def issue_owner_bootstrap_token(
    request: Request,
    settings: SettingsDep,
    output_dir: OutputDirDep,
) -> dict:
    """Local operator helper: mint/return bootstrap token path contents.

    Intended for loopback CLI/operator use during single-user local setup.
    Still requires same-origin browser gates when called from a browser.
    Does not enable mutation.
    """
    policy = _policy(settings, request)
    try:
        enforce_browser_request_gates(
            policy=policy,
            request_kind="api_read",
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
        )
        token = issue_bootstrap_token(output_dir)
    except (LocalSessionAuthError, LocalSessionForbidden, LocalSessionValidationError) as exc:
        raise _http_error(exc) from exc
    return {
        "bootstrap_token": token,
        "mutation_enabled": False,
        "note": "one-time; exchange via POST /api/auth/owner/bootstrap",
    }
