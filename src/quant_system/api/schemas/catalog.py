from __future__ import annotations

from pydantic import BaseModel

from quant_system.strategies.registry import StrategyMetadata
from quant_system.universe.registry import UniverseDefinition


class StrategyCatalogResponse(BaseModel):
    strategies: list[StrategyMetadata]


class UniverseCatalogResponse(BaseModel):
    universes: list[UniverseDefinition]
