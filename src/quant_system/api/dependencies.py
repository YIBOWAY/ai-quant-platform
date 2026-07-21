from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from quant_system.api.jobs.backtest_jobs import BacktestJobRunner
from quant_system.api.safety.local_session import (
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    LocalSessionAuthError,
    LocalSessionForbidden,
    LocalSessionValidationError,
    OwnerSession,
    enforce_browser_request_gates,
    policy_from_settings,
    require_mutation_precheck,
    verify_session_cookie,
)
from quant_system.config.settings import Settings
from quant_system.hermes.gateway_client import HermesApiReadClient


def get_services(request: Request) -> dict[str, Any]:
    return request.app.state.services


def get_settings(request: Request) -> Settings:
    return request.app.state.services["settings"]


def get_output_dir(request: Request) -> Path:
    return request.app.state.services["output_dir"]


def get_agent_output_dir(request: Request) -> Path:
    return request.app.state.services["agent_output_dir"]


def get_api_runs_dir(request: Request) -> Path:
    return request.app.state.services["api_runs_dir"]


def get_backtest_job_runner(request: Request) -> BacktestJobRunner:
    return request.app.state.services["backtest_job_runner"]


def get_bind_address(request: Request) -> str:
    return request.app.state.services["bind_address"]


def get_hermes_api_read_client(request: Request) -> HermesApiReadClient | None:
    settings = get_settings(request)
    if not settings.hermes_gateway.enabled:
        return None
    return HermesApiReadClient(settings.hermes_gateway)


def require_hermes_loopback_request(request: Request) -> None:
    """Verify the actual ASGI server socket, not the untrusted Host header."""
    settings = get_settings(request)
    if not settings.hermes_gateway.enabled:
        return
    server = request.scope.get("server")
    host = server[0] if isinstance(server, (list, tuple)) and server else None
    try:
        is_loopback = ipaddress.ip_address(str(host)).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "platform_socket_not_loopback",
                "message": "Hermes session reads require an actual loopback server socket",
            },
        )


def _local_session_policy(request: Request):
    settings = get_settings(request)
    return policy_from_settings(
        cors_origins=list(settings.api_cors_origins),
        bind_address=get_bind_address(request),
    )


def _security_http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "validation")
    message = getattr(exc, "message", "workspace_validation_failed")
    status = 401 if code == "auth" else 403 if code == "forbidden" else 422
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def require_owner_session(request: Request) -> OwnerSession:
    """Require signed owner session + api_read browser gates."""
    try:
        policy = _local_session_policy(request)
        enforce_browser_request_gates(
            policy=policy,
            request_kind="api_read",
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
        )
        return verify_session_cookie(
            get_output_dir(request),
            request.cookies.get(SESSION_COOKIE_NAME),
        )
    except (LocalSessionAuthError, LocalSessionForbidden, LocalSessionValidationError) as exc:
        raise _security_http_error(exc) from exc


def require_mutation_security(request: Request) -> OwnerSession:
    """Session + CSRF + origin gates. Still refuses until mutation_enabled is true.

    No public mutation route should call this until the V4/V8 write gate opens.
    """
    try:
        return require_mutation_precheck(
            output_dir=get_output_dir(request),
            policy=_local_session_policy(request),
            cookie_value=request.cookies.get(SESSION_COOKIE_NAME),
            csrf_header=request.headers.get(CSRF_HEADER_NAME),
            host_header=request.headers.get("host"),
            origin_header=request.headers.get("origin"),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
            mutation_enabled=False,
        )
    except (LocalSessionAuthError, LocalSessionForbidden, LocalSessionValidationError) as exc:
        raise _security_http_error(exc) from exc


SettingsDep = Annotated[Settings, Depends(get_settings)]
OutputDirDep = Annotated[Path, Depends(get_output_dir)]
AgentOutputDirDep = Annotated[Path, Depends(get_agent_output_dir)]
ApiRunsDirDep = Annotated[Path, Depends(get_api_runs_dir)]
BacktestJobRunnerDep = Annotated[BacktestJobRunner, Depends(get_backtest_job_runner)]
BindAddressDep = Annotated[str, Depends(get_bind_address)]
HermesApiReadClientDep = Annotated[
    HermesApiReadClient | None,
    Depends(get_hermes_api_read_client),
]
HermesLoopbackRequestDep = Annotated[None, Depends(require_hermes_loopback_request)]
OwnerSessionDep = Annotated[OwnerSession, Depends(require_owner_session)]
