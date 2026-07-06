from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from quant_system.factors.base import BaseFactor, FactorMetadata
from quant_system.factors.examples import (
    LiquidityFactor,
    MACDFactor,
    MomentumFactor,
    RSIFactor,
    VolatilityFactor,
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

    def register(self, factor_cls: type[BaseFactor], *, origin: str = "builtin") -> None:
        factor = factor_cls()
        if factor.factor_id in self._factor_classes:
            raise ValueError(f"factor_id {factor.factor_id!r} is already registered")
        self._factor_classes[factor.factor_id] = factor_cls
        self._origins[factor.factor_id] = origin

    def set_origin(self, factor_id: str, origin: str) -> None:
        """Retag a registered factor's provenance.

        Lets :func:`build_factor_registry` label factors by the registration
        pass that loaded them (e.g. the approved-candidate loader, which does not
        know its own provenance) without re-parsing sources.
        """
        if factor_id not in self._factor_classes:
            raise KeyError(f"unknown factor_id {factor_id!r}")
        self._origins[factor_id] = origin

    def origins(self) -> dict[str, str]:
        """Map each registered ``factor_id`` to its provenance origin."""
        return dict(self._origins)

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
    include_approved_candidates: bool = False,
    candidates_dir: str | Path | None = None,
) -> FactorRegistry:
    """Single construction point for the factor registry.

    Examples are always registered. Promoted, code-reviewed factors
    (``library.promoted.PROMOTED_FACTORS``) are registered by default. Approved
    agent candidates are loaded only when ``include_approved_candidates`` is set
    — that path ``exec``'s candidate source and is reserved for one-shot research
    (``run-config --include-approved-candidates``), NEVER the resident trading
    path (D-20 resident-path purity).
    """
    registry = FactorRegistry()
    for factor_cls in _EXAMPLE_FACTORS:
        registry.register(factor_cls, origin="builtin")

    if include_promoted:
        # Import the package (not the tuple by value) so promotions and test
        # monkeypatches of PROMOTED_FACTORS are observed at call time.
        from quant_system.factors.library import promoted

        for factor_cls in promoted.PROMOTED_FACTORS:
            registry.register(factor_cls, origin="promoted")

    if include_approved_candidates and candidates_dir is not None:
        # Reuse the single approved-candidate loader (SafetyGate + AST check).
        # Lazy import avoids a circular import: promotion imports FactorRegistry.
        from quant_system.agent.promotion import load_approved_factor_candidates

        loaded = load_approved_factor_candidates(registry, candidates_dir=candidates_dir)
        # Origin is tracked from which pass registered the id, not by re-parsing:
        # the loader reports exactly the ids it added, so retag them as candidate.
        for factor_id in loaded:
            registry.set_origin(factor_id, "candidate")

    return registry


def build_default_factor_registry() -> FactorRegistry:
    """Thin alias of :func:`build_factor_registry` (examples + promoted)."""
    return build_factor_registry()


def register_alpha101_library(registry: FactorRegistry) -> FactorRegistry:
    from quant_system.factors.library.alpha101 import ALPHA101_FACTORS

    for factor_cls in ALPHA101_FACTORS:
        registry.register(factor_cls)
    return registry
