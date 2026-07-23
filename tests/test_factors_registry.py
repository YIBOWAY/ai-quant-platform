import pytest

from quant_system.factors.examples import MomentumFactor
from quant_system.factors.library.promoted import PROMOTED_FACTORS
from quant_system.factors.pipeline import build_default_factors
from quant_system.factors.registry import FactorRegistry, build_default_factor_registry

_EXAMPLE_FACTOR_IDS = ("momentum", "volatility", "liquidity", "rsi", "macd")
_PROMOTED_FACTOR_IDS = tuple(factor_cls().factor_id for factor_cls in PROMOTED_FACTORS)
_RESIDENT_FACTOR_IDS = _EXAMPLE_FACTOR_IDS + _PROMOTED_FACTOR_IDS


def test_default_registry_contains_examples_and_promoted_factors() -> None:
    registry = build_default_factor_registry()

    assert tuple(registry.factor_ids()) == _RESIDENT_FACTOR_IDS
    assert registry.create("momentum", lookback=5).lookback == 5


def test_registry_rejects_duplicate_factor_ids() -> None:
    registry = FactorRegistry()
    registry.register(MomentumFactor)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(MomentumFactor)


def test_registry_lists_metadata_without_exposing_implementation_details() -> None:
    registry = build_default_factor_registry()

    metadata = registry.list_metadata()

    assert tuple(item.factor_id for item in metadata) == _RESIDENT_FACTOR_IDS
    assert all(item.lookback > 0 for item in metadata)


def test_default_factor_builder_can_use_registered_factor_set() -> None:
    class CustomMomentumFactor(MomentumFactor):
        factor_id = "custom_momentum"
        factor_name = "Custom Momentum"

    registry = build_default_factor_registry()
    registry.register(CustomMomentumFactor)

    factors = build_default_factors(lookback=7, registry=registry)

    assert "custom_momentum" in {factor.factor_id for factor in factors}
    assert all(factor.lookback == 7 for factor in factors)
