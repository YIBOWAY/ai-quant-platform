from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.dependencies import SettingsDep
from quant_system.api.schemas.safety import EffectivePaperSafetyResponse
from quant_system.hermes.paper_safety_authority import PaperSafetyAuthority

router = APIRouter()


@router.get(
    "/safety/effective",
    response_model=EffectivePaperSafetyResponse,
)
def effective_paper_safety(
    settings: SettingsDep,
) -> dict[str, object]:
    observation = PaperSafetyAuthority(settings).observe(
        settings.agent_v02_release.workspace_id
    )
    return observation.to_public_dict()
