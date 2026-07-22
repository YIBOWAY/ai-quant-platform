import pytest

from quant_system.factors.examples import MomentumFactor
from quant_system.factors.pipeline import build_default_factors
from quant_system.factors.registry import FactorRegistry, build_default_factor_registry

_PROMOTED_FACTOR_IDS = (
    "agent_candidate_wave2_sceneb_mom20_v3",
    "paper_short_term_reversal_proxy_v1",
)


def test_default_registry_contains_examples_and_promoted_factors() -> None:
    registry = build_default_factor_registry()

    assert set(registry.factor_ids()) == {
        "momentum",
        "volatility",
        "liquidity",
        "rsi",
        "macd",
        *_PROMOTED_FACTOR_IDS,
    }
    assert registry.create("momentum", lookback=5).lookback == 5


def test_registry_rejects_duplicate_factor_ids() -> None:
    registry = FactorRegistry()
    registry.register(MomentumFactor)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(MomentumFactor)


def test_registry_lists_metadata_without_exposing_implementation_details() -> None:
    registry = build_default_factor_registry()

    metadata = registry.list_metadata()

    assert [item.factor_id for item in metadata] == [
        "momentum",
        "volatility",
        "liquidity",
        "rsi",
        "macd",
        *_PROMOTED_FACTOR_IDS,
    ]
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
