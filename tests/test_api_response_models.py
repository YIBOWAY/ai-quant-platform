from fastapi.testclient import TestClient

from quant_system.api.server import create_app


def test_read_only_market_routes_publish_response_models(tmp_path) -> None:
    client = TestClient(create_app(output_dir=tmp_path))

    openapi = client.get("/openapi.json").json()

    expected = {
        "/api/health": "HealthResponse",
        "/api/symbols": "SymbolsResponse",
        "/api/ohlcv": "OHLCVResponse",
        "/api/market-data/history": "MarketDataHistoryResponse",
        "/api/benchmark": "BenchmarkResponse",
        "/api/agent/llm-config": "AgentLLMConfigResponse",
        "/api/options/daily-scan/dates": "OptionsDailyScanDatesResponse",
        "/api/options/daily-scan/status": "OptionsDailyScanStatusResponse",
        "/api/options/tools/strategy/templates": "OptionsStrategyTemplatesResponse",
        "/api/options/tools/watchlist": "OptionsWatchlistResponse",
        "/api/backtests": "BacktestsResponse",
        "/api/backtests/{run_id}": "BacktestDetailResponse",
        "/api/paper": "PaperRunsResponse",
        "/api/agent/candidates": "AgentCandidatesResponse",
        "/api/agent/candidates/{candidate_id}": "AgentCandidateDetailResponse",
        "/api/experiments": "ExperimentsResponse",
        "/api/factors": "FactorCatalogResponse",
        "/api/factors/runs": "FactorRunsResponse",
        "/api/runs/recent": "RecentRunsResponse",
        "/api/strategies": "StrategyCatalogResponse",
        "/api/universes": "UniverseCatalogResponse",
    }
    for path, model_name in expected.items():
        response_schema = openapi["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert response_schema == {"$ref": f"#/components/schemas/{model_name}"}

    components = openapi["components"]["schemas"]
    assert "data_provider" in components["HealthResponse"]["properties"]
    assert "futu_opend" in components["HealthResponse"]["properties"]
    assert "database" in components["HealthResponse"]["properties"]
    assert "metadata" in components["MarketDataHistoryResponse"]["properties"]
    assert "has_api_key" in components["AgentLLMConfigResponse"]["properties"]
    assert "dates" in components["OptionsDailyScanDatesResponse"]["properties"]
    assert "status" in components["OptionsDailyScanStatusResponse"]["properties"]
    assert "templates" in components["OptionsStrategyTemplatesResponse"]["properties"]
    assert "watchlist" in components["OptionsWatchlistResponse"]["properties"]
    assert "backtests" in components["BacktestsResponse"]["properties"]
    assert "benchmark" in components["BacktestDetailResponse"]["properties"]
    assert "paper_runs" in components["PaperRunsResponse"]["properties"]
    assert "candidates" in components["AgentCandidatesResponse"]["properties"]
    assert "source_preview" in components["AgentCandidateDetailResponse"]["properties"]
    assert "experiments" in components["ExperimentsResponse"]["properties"]
    assert "source" in components["OHLCVResponse"]["properties"]
    assert "source" in components["BenchmarkResponse"]["properties"]
    assert "factors" in components["FactorCatalogResponse"]["properties"]
    assert "runs" in components["FactorRunsResponse"]["properties"]
    assert "runs" in components["RecentRunsResponse"]["properties"]
    assert "strategies" in components["StrategyCatalogResponse"]["properties"]
    assert "universes" in components["UniverseCatalogResponse"]["properties"]
