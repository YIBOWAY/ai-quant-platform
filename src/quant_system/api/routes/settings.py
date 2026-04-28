from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep
from quant_system.api.safety.masking import mask_secret_fields

router = APIRouter()


@router.get("/settings")
def settings(settings: SettingsDep) -> dict:
    return mask_secret_fields(settings.model_dump(mode="json"))
