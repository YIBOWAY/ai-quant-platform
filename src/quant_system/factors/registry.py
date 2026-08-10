from __future__ import annotations

from collections.abc import Iterable

from quant_system.factors.base import BaseFactor, FactorMetadata
from quant_system.factors.examples import (
    LiquidityFactor,
    MACDFactor,
    MomentumFactor,
    RSIFactor,
    VolatilityFactor,
)
from quant_system.factors.promoted_qualification import (
    PromotedFactorQualification,
    load_promoted_factor_qualification,
)

_EXAMPLE_FACTORS: tuple[type[BaseFactor], ...] = (
    MomentumFactor,
    VolatilityFactor,
    LiquidityFactor,
    RSIFactor,
    MACDFactor,
)


class FactorRegistry:
    def __init__(self) -> None:
        self._factor_classes: dict[str, type[BaseFactor]] = {}
        self._origins: dict[str, str] = {}
        self._promoted_qualifications: dict[str, PromotedFactorQualification] = {}

    def register(
        self,
        factor_cls: type[BaseFactor],
        *,
        origin: str = "builtin",
        promoted_qualification: PromotedFactorQualification | None = None,
    ) -> None:
        factor = factor_cls()
        if factor.factor_id in self._factor_classes:
            raise ValueError(f"factor_id {factor.factor_id!r} is already registered")
        self._factor_classes[factor.factor_id] = factor_cls
        self._origins[factor.factor_id] = origin
        if promoted_qualification is not None:
            self._promoted_qualifications[factor.factor_id] = promoted_qualification

    def set_origin(self, factor_id: str, origin: str) -> None:
        """Retag the provenance of an already registered factor."""
        if factor_id not in self._factor_classes:
            raise KeyError(f"unknown factor_id {factor_id!r}")
        self._origins[factor_id] = origin

    def origins(self) -> dict[str, str]:
        """Map each registered ``factor_id`` to its provenance origin."""
        return dict(self._origins)

    def promoted_qualifications(self) -> dict[str, dict[str, str | None]]:
        return {
            factor_id: qualification.to_dict()
            for factor_id, qualification in self._promoted_qualifications.items()
        }

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


def build_factor_registry(
    *,
    include_promoted: bool = True,
    purpose: str = "paper",
) -> FactorRegistry:
    """Single construction point for the factor registry.

    Examples are always registered. Promoted, code-reviewed factors
    (``library.promoted.PROMOTED_FACTORS``) are registered by default. Candidate
    source is deliberately outside this factory: one-shot research must call
    ``load_approved_factor_candidate`` with one exact candidate ID and expected
    manifest digest. This keeps every resident caller examples+promoted only
    (D-20 resident-path purity).
    """
    if purpose not in {"paper", "live"}:
        raise ValueError("factor registry purpose must be 'paper' or 'live'")
    registry = FactorRegistry()
    for factor_cls in _EXAMPLE_FACTORS:
        registry.register(factor_cls, origin="builtin")

    if include_promoted:
        # Import the package (not the tuple by value) so promotions and test
        # monkeypatches of PROMOTED_FACTORS are observed at call time.
        from quant_system.factors.library import promoted

        for factor_cls in promoted.PROMOTED_FACTORS:
            qualification = load_promoted_factor_qualification(factor_cls)
            if purpose == "live" and qualification.promotion_scope != "live_eligible":
                continue
            registry.register(
                factor_cls,
                origin="promoted",
                promoted_qualification=qualification,
            )

    return registry


def build_default_factor_registry() -> FactorRegistry:
    """Thin alias of :func:`build_factor_registry` (examples + promoted)."""
    return build_factor_registry()


def register_alpha101_library(registry: FactorRegistry) -> FactorRegistry:
    from quant_system.factors.library.alpha101 import ALPHA101_FACTORS

    for factor_cls in ALPHA101_FACTORS:
        registry.register(factor_cls)
    return registry
