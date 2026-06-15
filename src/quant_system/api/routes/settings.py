from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep
from quant_system.api.safety.masking import mask_secret_fields
from quant_system.api.schemas.settings import SettingsResponse

router = APIRouter()


@router.get("/settings", response_model=SettingsResponse)
def settings(settings: SettingsDep) -> dict:
    return mask_secret_fields(settings.model_dump(mode="json"))
