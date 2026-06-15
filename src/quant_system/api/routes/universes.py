from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.schemas.catalog import UniverseCatalogResponse
from quant_system.universe.registry import build_default_universe_registry

router = APIRouter()


@router.get("/universes", response_model=UniverseCatalogResponse)
def list_universes() -> dict:
    registry = build_default_universe_registry()
    return {
        "universes": [
            universe.model_dump(mode="json")
            for universe in registry.list_metadata()
        ]
    }
