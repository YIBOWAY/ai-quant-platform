from __future__ import annotations

from fastapi import APIRouter

from quant_system.api.schemas.catalog import StrategyCatalogResponse
from quant_system.strategies.registry import build_default_strategy_registry

router = APIRouter()


@router.get("/strategies", response_model=StrategyCatalogResponse)
def list_strategies() -> dict:
    registry = build_default_strategy_registry()
    return {
        "strategies": [
            metadata.model_dump(mode="json")
            for metadata in registry.list_metadata()
        ]
    }
