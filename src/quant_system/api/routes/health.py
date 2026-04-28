from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep

router = APIRouter()


@router.get("/health")
def health(settings: SettingsDep) -> dict[str, str]:
    return {
        "status": "ok",
        "app_name": settings.app_name,
        "environment": settings.environment,
    }
