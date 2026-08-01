from __future__ import annotations

from quant_system.strategies.registry import build_default_strategy_registry
from quant_system.universe.registry import build_default_universe_registry


def test_strategy_registry_lists_runnable_catalog_entries() -> None:
    registry = build_default_strategy_registry()

    strategy_ids = registry.strategy_ids()

    assert strategy_ids == [
        "cross_sectional_top_n",
        "reversal_momentum",
        "mean_reversion_top_n",
        "drift_regime_reversal_top_n_v1",
    ]
    metadata = {item.id: item for item in registry.list_metadata()}
    assert metadata["cross_sectional_top_n"].name
    top_n_field = metadata["cross_sectional_top_n"].parameter_schema["fields"]["top_n"]
    assert top_n_field["type"] == "integer"
    assert metadata["reversal_momentum"].paper_source
    assert metadata["reversal_momentum"].run_endpoint == "/api/replications/reversal-momentum/run"
    assert metadata["reversal_momentum"].supports_account_rebalance is False
    # Mean-Reversion is a runnable backtest-engine strategy (same run endpoint).
    assert metadata["cross_sectional_top_n"].supports_account_rebalance is True
    assert metadata["mean_reversion_top_n"].result_type == "backtest"
    assert metadata["mean_reversion_top_n"].run_endpoint == "/api/backtests/run"
    assert metadata["mean_reversion_top_n"].supports_account_rebalance is True


def test_universe_registry_lists_research_presets() -> None:
    registry = build_default_universe_registry()

    universe_ids = registry.universe_ids()

    assert {"etf", "technology", "defense", "healthcare"}.issubset(universe_ids)
    etf = registry.get("etf")
    assert "QQQ" in etf.symbols
    assert etf.benchmark_symbol == "SPY"


def test_strategy_and_factor_metadata_expose_optional_zh_display_names() -> None:
    from quant_system.factors.examples import MomentumFactor

    registry = build_default_strategy_registry()
    metadata = {item.id: item for item in registry.list_metadata()}

    # zh layer is display-only; ids and English names stay canonical.
    assert metadata["cross_sectional_top_n"].name == "Cross-Sectional Top-N"
    assert metadata["cross_sectional_top_n"].display_name_zh == "横截面 Top-N"
    assert metadata["mean_reversion_top_n"].display_name_zh == "均值回归 Top-N"

    momentum = MomentumFactor().metadata
    assert momentum.factor_name == "Momentum"
    assert momentum.display_name_zh == "动量"
