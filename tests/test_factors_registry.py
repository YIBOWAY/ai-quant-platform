import pytest

from quant_system.factors.examples import MomentumFactor
from quant_system.factors.registry import FactorRegistry, build_default_factor_registry


def test_default_registry_contains_phase_2_example_factors() -> None:
    registry = build_default_factor_registry()

    assert set(registry.factor_ids()) == {"momentum", "volatility", "liquidity"}
    assert registry.create("momentum", lookback=5).lookback == 5


def test_registry_rejects_duplicate_factor_ids() -> None:
    registry = FactorRegistry()
    registry.register(MomentumFactor)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(MomentumFactor)


def test_registry_lists_metadata_without_exposing_implementation_details() -> None:
    registry = build_default_factor_registry()

    metadata = registry.list_metadata()

    assert [item.factor_id for item in metadata] == ["momentum", "volatility", "liquidity"]
    assert all(item.lookback > 0 for item in metadata)
