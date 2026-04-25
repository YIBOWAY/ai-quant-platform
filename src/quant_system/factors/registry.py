from __future__ import annotations

from collections.abc import Iterable

from quant_system.factors.base import BaseFactor, FactorMetadata
from quant_system.factors.examples import LiquidityFactor, MomentumFactor, VolatilityFactor


class FactorRegistry:
    def __init__(self) -> None:
        self._factor_classes: dict[str, type[BaseFactor]] = {}

    def register(self, factor_cls: type[BaseFactor]) -> None:
        factor = factor_cls()
        if factor.factor_id in self._factor_classes:
            raise ValueError(f"factor_id {factor.factor_id!r} is already registered")
        self._factor_classes[factor.factor_id] = factor_cls

    def factor_ids(self) -> list[str]:
        return list(self._factor_classes)

    def list_metadata(self) -> list[FactorMetadata]:
        return [factor_cls().metadata for factor_cls in self._factor_classes.values()]

    def create(self, factor_id: str, **kwargs) -> BaseFactor:
        try:
            factor_cls = self._factor_classes[factor_id]
        except KeyError as exc:
            raise KeyError(f"unknown factor_id {factor_id!r}") from exc
        return factor_cls(**kwargs)

    def create_many(self, factor_ids: Iterable[str], **kwargs) -> list[BaseFactor]:
        return [self.create(factor_id, **kwargs) for factor_id in factor_ids]


def build_default_factor_registry() -> FactorRegistry:
    registry = FactorRegistry()
    registry.register(MomentumFactor)
    registry.register(VolatilityFactor)
    registry.register(LiquidityFactor)
    return registry
