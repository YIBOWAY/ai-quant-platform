from __future__ import annotations

from fastapi import HTTPException

from quant_system.data.provider_factory import DataProviderUnavailableError


def not_found_404(resource: str, identifier: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "not_found",
            "resource": resource,
            "id": identifier,
            "message": f"{resource.replace('_', ' ')} {identifier!r} not found",
        },
    )


def provider_unavailable_400(exc: DataProviderUnavailableError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "provider_unavailable",
            "provider": exc.provider,
            "message": str(exc),
        },
    )
