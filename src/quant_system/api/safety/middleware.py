from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from quant_system.config.settings import Settings


def build_safety_footer(*, settings: Settings, bind_address: str) -> dict[str, Any]:
    return {
        "dry_run": settings.safety.dry_run,
        "paper_trading": settings.safety.paper_trading,
        "live_trading_enabled": settings.safety.live_trading_enabled,
        "kill_switch": settings.safety.kill_switch,
        "bind_address": bind_address,
    }


def validate_bind_address(*, bind_address: str, bind_public_confirmed: bool) -> None:
    if bind_address == "0.0.0.0" and not bind_public_confirmed:
        raise ValueError("Binding to 0.0.0.0 requires explicit --bind-public confirmation")


async def attach_safety_footer(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return response

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except json.JSONDecodeError:
        return Response(
            content=body,
            status_code=response.status_code,
            headers=_copy_headers(response),
            media_type=response.media_type,
            background=response.background,
        )

    services = request.app.state.services
    safety = build_safety_footer(
        settings=services["settings"],
        bind_address=services["bind_address"],
    )
    if isinstance(payload, dict):
        payload.setdefault("safety", safety)
    else:
        payload = {"data": payload, "safety": safety}

    return JSONResponse(
        content=payload,
        status_code=response.status_code,
        headers=_copy_headers(response),
        background=response.background,
    )


def _copy_headers(response: Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in {"content-length", "content-type"}
    }
