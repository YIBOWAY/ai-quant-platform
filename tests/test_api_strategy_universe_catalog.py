from __future__ import annotations

from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_strategy_catalog_api_exposes_registered_strategies(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/strategies")

    assert response.status_code == 200
    payload = response.json()
    strategies = {item["id"]: item for item in payload["strategies"]}
    assert {"cross_sectional_top_n", "reversal_momentum"}.issubset(strategies)
    assert strategies["cross_sectional_top_n"]["parameter_schema"]["fields"]["factor_ids"]
    assert strategies["cross_sectional_top_n"]["supports_account_rebalance"] is True
    assert strategies["reversal_momentum"]["paper_source"]
    assert strategies["reversal_momentum"]["supports_account_rebalance"] is False
    assert payload["safety"]["live_trading_enabled"] is False


def test_universe_catalog_api_exposes_registered_universes(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    response = client.get("/api/universes")

    assert response.status_code == 200
    payload = response.json()
    universes = {item["id"]: item for item in payload["universes"]}
    assert {"etf", "technology", "defense", "healthcare"}.issubset(universes)
    assert "QQQ" in universes["etf"]["symbols"]
    assert universes["technology"]["benchmark_symbol"] == "SPY"
